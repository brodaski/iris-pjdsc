"""Shared rainfall helpers for the Metro Manila version: live CHIRPS from HDX, the Open-Meteo rainfall forecast,
weekly shares and the case forecast. Same logic as app/app.py."""
import io
import math
import os
import socket
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

DATA = Path(__file__).resolve().parent.parent / "data" / "processed"
HDX_API = os.environ.get("HDX_API", "https://data.humdata.org/api/3/action/package_show")
HDX_DATASET = "phl-rainfall-subnational"
HDX_RESOURCE = "phl-rainfall-subnat-5ytd.csv"
TOKEN_FILE = DATA.parent.parent / "hdx_token.txt"
OPEN_METEO = os.environ.get("OPEN_METEO_API", "https://api.open-meteo.com/v1/forecast")
FC_COEF = pd.read_csv(DATA / "forecast_coefs.csv")
WEEKLY_P90 = pd.read_csv(DATA / "province_weekly_p90.csv")
POINTS = pd.read_csv(DATA / "province_points.csv")


def hdx_token():
    """Optional HDX token: Streamlit secret, environment variable, or hdx_token.txt. Public data works without it."""
    try:
        if "HDX_TOKEN" in st.secrets:
            return st.secrets["HDX_TOKEN"]
    except Exception:
        pass
    if os.environ.get("HDX_TOKEN"):
        return os.environ["HDX_TOKEN"]
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip() or None
    return None


def add_trigger(new, p90):
    """Province rows of a raw CHIRPS file -> trigger rows using each province's stored 90th percentile."""
    new = new[new["adm_level"] == 2][["date", "PCODE", "rfh", "rfh_avg", "version"]].copy()
    new["date"] = pd.to_datetime(new["date"])
    new = new.merge(p90, on="PCODE")
    new["above_p90"] = new["rfh"] > new["p90_mm"]
    return new[["date", "PCODE", "rfh", "rfh_avg", "p90_mm", "above_p90", "version"]]


@st.cache_data(ttl=6 * 3600, show_spinner="Checking HDX for new rainfall data...")
def live_rain(local):
    """Newest CHIRPS dekads from HDX merged onto the repo copy. Falls back to the repo copy on any error."""
    try:
        token = hdx_token()
        headers = {"Authorization": token} if token else {}
        pkg = requests.get(HDX_API, params={"id": HDX_DATASET}, headers=headers, timeout=20).json()["result"]
        url = next(r["url"] for r in pkg["resources"] if r["name"] == HDX_RESOURCE)
        csv = requests.get(url, headers=headers, timeout=60)
        csv.raise_for_status()
        new = add_trigger(pd.read_csv(io.BytesIO(csv.content)), local.groupby("PCODE")["p90_mm"].first().reset_index())
        merged = (pd.concat([local, new]).drop_duplicates(["date", "PCODE"], keep="last")
                  .sort_values(["date", "PCODE"]).reset_index(drop=True))
        return merged, f"Live from HDX, checked {pd.Timestamp.now(tz='Asia/Manila'):%d %b %Y %H:%M}"
    except Exception as e:
        return local, f"Offline copy in the repo (HDX not reachable: {type(e).__name__})"


def daily_share(daily):
    """Share of provinces above their own weekly 90th percentile, per ISO week, from daily rain (PCODE, day, mm).
    Only full 7-day weeks count."""
    daily = daily.assign(week_start=daily["day"] - pd.to_timedelta(daily["day"].dt.weekday, unit="D"))
    wk = daily.groupby(["PCODE", "week_start"])["mm"].agg(["sum", "size"]).reset_index()
    wk = wk[wk["size"] == 7].merge(WEEKLY_P90, on="PCODE")
    wk["above"] = wk["sum"] > wk["weekly_p90_mm"]
    return wk.groupby("week_start")["above"].mean()


@st.cache_data
def weekly_share(dekad_rain):
    """Weekly share from 10-day CHIRPS rain spread evenly over its days (same steps as notebook 01)."""
    r = dekad_rain[["date", "PCODE", "rfh"]].copy()
    nxt = r["date"] + pd.offsets.MonthBegin(1)
    r["ndays"] = (r["date"].where(r["date"].dt.day != 21, nxt - pd.Timedelta(days=10))
                  + pd.Timedelta(days=10) - r["date"]).dt.days
    daily = r.loc[r.index.repeat(r["ndays"])].copy()
    daily["day"] = daily["date"] + pd.to_timedelta(daily.groupby(level=0).cumcount(), unit="D")
    daily["mm"] = daily["rfh"] / daily["ndays"]
    return daily_share(daily[["PCODE", "day", "mm"]])


CACHE = Path(os.environ.get("IRIS_CACHE", Path.home() / ".iris"))


def get_open_meteo(params):
    """GET Open-Meteo over IPv4 first. On some home networks Python's default connection to Open-Meteo hangs
    while an IPv4-only one answers in about a second (browsers fall back on their own), so try IPv4, then the
    default, then IPv4 again, each failing fast."""
    import urllib3.util.connection as conn
    old, err = conn.allowed_gai_family, None
    for family in (socket.AF_INET, None, socket.AF_INET):
        if family:
            conn.allowed_gai_family = lambda: family
        try:
            return requests.get(OPEN_METEO, params=params, timeout=(6, 20))
        except requests.exceptions.RequestException as e:
            err = e
        finally:
            conn.allowed_gai_family = old
    raise err


@st.cache_data(ttl=3 * 3600, show_spinner="Getting the 16-day rainfall forecast...")
def rain_forecast():
    """Daily rain at one point per province, from 21 days ago to 16 days ahead (Open-Meteo weather models; no key).
    Returns (DataFrame of PCODE, day, mm, is_forecast, or None, source text). The last good download is kept in
    ~/.iris and used, with its date, when Open-Meteo cannot be reached."""
    saved = CACHE / "open_meteo_forecast.csv"
    try:
        resp = get_open_meteo({
            "latitude": ",".join(map(str, POINTS["lat"])), "longitude": ",".join(map(str, POINTS["lon"])),
            "daily": "precipitation_sum", "past_days": 21, "forecast_days": 16, "timezone": "Asia/Manila"})
        resp.raise_for_status()
        js = resp.json()
        js = js if isinstance(js, list) else [js]
        now = pd.Timestamp.now(tz="Asia/Manila")
        daily = pd.concat([pd.DataFrame({"PCODE": p, "day": pd.to_datetime(j["daily"]["time"]),
                                         "mm": j["daily"]["precipitation_sum"]})
                           for p, j in zip(POINTS["PCODE"], js)], ignore_index=True)
        daily["mm"] = pd.to_numeric(daily["mm"], errors="coerce").fillna(0)
        daily["is_forecast"] = daily["day"] >= now.tz_localize(None).normalize()
        try:
            CACHE.mkdir(parents=True, exist_ok=True)
            daily.assign(fetched=now.tz_localize(None)).to_csv(saved, index=False)
        except OSError:
            pass
        return daily, f"Open-Meteo forecast, fetched {now:%d %b %Y %H:%M}"
    except Exception as e:
        reason = f"Open-Meteo forecast not reachable ({type(e).__name__})"
        if saved.exists():
            daily = pd.read_csv(saved, parse_dates=["day", "fetched"])
            fetched = daily.pop("fetched").iloc[0]
            daily["is_forecast"] = daily["day"] >= pd.Timestamp.now(tz="Asia/Manila").tz_localize(None).normalize()
            if pd.Timestamp.now() - fetched < pd.Timedelta(days=7):
                return daily, f"{reason}; showing the forecast saved on {fetched:%d %b %Y %H:%M}"
        return None, reason


def forecast(share, as_of, horizon=6, future=None):
    """Expected % rise in national cases for the weeks after as_of, versus weeks with no extreme rain.
    Rain after as_of comes from `future` (forecast weekly shares) where given; otherwise it is assumed to be normal
    (no extreme rain)."""
    known = share[share.index <= as_of]
    if future is not None:
        known = pd.concat([known, future[future.index > as_of]])
    rows = []
    for h in range(1, horizon + 1):
        target = as_of + pd.Timedelta(weeks=h)
        z = sum(c * known.get(target - pd.Timedelta(weeks=int(L)), 0) * 10
                for L, c in zip(FC_COEF["lag_weeks"], FC_COEF["coef"]))
        rows.append({"week_start": target, "weeks_ahead": h, "rise_pct": (math.exp(z) - 1) * 100})
    return pd.DataFrame(rows)
