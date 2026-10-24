"""IRIS (Infection Risk from Inundation and Storms): flood-health exposure and leptospirosis alert dashboard.

Reads the small files written by notebooks/01_prepare_data.ipynb and notebooks/02_lag_analysis.ipynb.
Run with:  streamlit run app/app.py
"""
import io
import json
import math
import os
from pathlib import Path

import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

DATA = Path(__file__).resolve().parent.parent / "data" / "processed"
DEFAULT_DEKAD = "2024-07-21"   # Typhoon Carina (Gaemi) and southwest monsoon floods
HDX_API = os.environ.get("HDX_API", "https://data.humdata.org/api/3/action/package_show")
HDX_DATASET = "phl-rainfall-subnational"
HDX_RESOURCE = "phl-rainfall-subnat-5ytd.csv"   # last five years, about 2 MB
TOKEN_FILE = DATA.parent.parent / "hdx_token.txt"   # optional, gitignored

LOGO_DIR = Path(__file__).resolve().parent.parent / "assets"
st.set_page_config(page_title="IRIS", page_icon=str(LOGO_DIR / "iris_mark.png"), layout="wide")


@st.cache_data
def load():
    idx = pd.read_csv(DATA / "province_index.csv")
    rain = pd.read_csv(DATA / "dekad_rain.csv", parse_dates=["date"])
    lag = pd.read_csv(DATA / "lag_results.csv")
    weekly = pd.read_csv(DATA / "weekly_national.csv", parse_dates=["week_start"])
    geo = json.loads((DATA / "provinces.geojson").read_text())
    events = pd.read_csv(DATA / "event_study.csv", parse_dates=["event_week"])
    diseases = pd.read_csv(DATA / "disease_lag.csv")
    return idx, rain, lag, weekly, geo, events, diseases


idx, rain, lag, weekly, geo, events, diseases = load()


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


rain, rain_source = live_rain(rain)
LATEST = rain["date"].max()

@st.cache_data
def load_ncr():
    geo_ncr = json.loads((DATA / "ncr_barangays.geojson").read_text())
    df = pd.DataFrame([f["properties"] for f in geo_ncr["features"]])
    return geo_ncr, df


FC_COEF = pd.read_csv(DATA / "forecast_coefs.csv")
FC_SCORES = pd.read_csv(DATA / "forecast_scores.csv")
FC_BACKTEST = pd.read_csv(DATA / "forecast_backtest.csv", parse_dates=["week_start"])
WEEKLY_P90 = pd.read_csv(DATA / "province_weekly_p90.csv")


@st.cache_data
def weekly_share(dekad_rain):
    """Share of provinces above their own weekly 90th percentile, per ISO week (same steps as notebook 01)."""
    r = dekad_rain[["date", "PCODE", "rfh"]].copy()
    nxt = r["date"] + pd.offsets.MonthBegin(1)
    r["ndays"] = (r["date"].where(r["date"].dt.day != 21, nxt - pd.Timedelta(days=10))
                  + pd.Timedelta(days=10) - r["date"]).dt.days
    daily = r.loc[r.index.repeat(r["ndays"])].copy()
    daily["day"] = daily["date"] + pd.to_timedelta(daily.groupby(level=0).cumcount(), unit="D")
    daily["mm"] = daily["rfh"] / daily["ndays"]
    daily["week_start"] = daily["day"] - pd.to_timedelta(daily["day"].dt.weekday, unit="D")
    wk = daily.groupby(["PCODE", "week_start"])["mm"].agg(["sum", "size"]).reset_index()
    wk = wk[wk["size"] == 7].merge(WEEKLY_P90, on="PCODE")
    wk["above"] = wk["sum"] > wk["weekly_p90_mm"]
    return wk.groupby("week_start")["above"].mean()


def forecast(share, as_of, horizon=6):
    """Expected % rise in national cases for the weeks after as_of, versus weeks with no extreme rain.
    Rain after as_of is not yet known and is assumed to be normal (no extreme rain)."""
    known = share[share.index <= as_of]
    rows = []
    for h in range(1, horizon + 1):
        target = as_of + pd.Timedelta(weeks=h)
        z = sum(c * known.get(target - pd.Timedelta(weeks=int(L)), 0) * 10
                for L, c in zip(FC_COEF["lag_weeks"], FC_COEF["coef"]))
        rows.append({"week_start": target, "weeks_ahead": h, "rise_pct": (math.exp(z) - 1) * 100})
    return pd.DataFrame(rows)

main = lag[lag["model"].str.startswith("Main")]
peak = main.loc[main["rr"].idxmax()]
sig = main.loc[main["significant"], "lag_weeks"]
PEAK, RISE_FROM, RISE_TO = int(peak["lag_weeks"]), int(sig.min()), int(sig.max())


def province_map(df, color, title, scale, range_color=None, hover=None):
    # Plain SVG map (no tiles, no WebGL) so it renders anywhere, including offline demos.
    fig = px.choropleth(
        df, geojson=geo, locations="PCODE", featureidkey="properties.PCODE", color=color,
        color_continuous_scale=scale, range_color=range_color, hover_name="province", hover_data=hover,
        labels={"index": "Index", "pct_of_p90": "% of 90th pct", "rfh": "Rain (mm)", "p90_mm": "90th pct (mm)",
                "rank": "Rank"},
    )
    fig.update_geos(visible=False, projection_type="mercator",
                    lonaxis_range=[116.5, 127], lataxis_range=[4.5, 21.2])
    fig.update_traces(marker_line_width=0.4, marker_line_color="white")
    fig.update_layout(height=620, margin=dict(l=0, r=0, t=30, b=0), title=title)
    return fig


# Sidebar: the rainfall period drives the trigger and the checklist.
with st.sidebar:
    st.image(str(LOGO_DIR / "iris_logo.png"), width=260)
    st.caption("Where to prepare for leptospirosis after heavy rain, and when.")
    dekads = sorted(rain["date"].dt.strftime("%Y-%m-%d").unique(), reverse=True)
    example = st.toggle("Show example: Typhoon Carina, July 2024", value=False,
                        help="Off: the latest 10-day period. On: late July 2024, Typhoon Carina and the monsoon.")
    start = DEFAULT_DEKAD if example and DEFAULT_DEKAD in dekads else dekads[0]
    dekad = st.selectbox("10-day rainfall period (start date)", dekads, index=dekads.index(start),
                         help="Newest first. Rainfall is updated from HDX every 10 days.")
    latest = rain[rain["date"] == LATEST]
    st.caption(f"Latest period: **{LATEST:%d %b %Y}** ({int(latest['above_p90'].sum())} provinces above their 90th "
               f"percentile). Rainfall source: {rain_source}.")
    st.divider()
    st.markdown(
        f"**Alert window:** cases peak **{PEAK} weeks** after heavy rain and stay raised "
        f"from week {RISE_FROM} to week {RISE_TO} (national DOH surveillance, 2019 to 2023)."
    )
    with st.expander("About the data"):
        st.markdown(
            "- Rainfall: CHIRPS 10-day rainfall by province, WFP and Climate Hazards Center via HDX, 1981 to "
            f"{rain['date'].max():%b %Y}.\n"
            "- Population: PSA 2020 Census by single-year age and barangay, via HDX.\n"
            "- Boundaries: NAMRIA and PSA, via HDX (COD-AB 2025), merged to the 81 rainfall units.\n"
            "- Cases: weekly national leptospirosis counts, DOH reports compiled by the University of Mindanao "
            "(Mendeley Data).\n\n"
            "**Limits:** exposure, not cases; rain is not flood; one national lag for all provinces; 2020 census."
        )

sel = rain[rain["date"] == pd.Timestamp(dekad)].merge(idx[["PCODE", "province", "rank", "index",
                                                             "population", "under5", "over65", "vulnerable"]],
                                                       on="PCODE")
sel["pct_of_p90"] = (sel["rfh"] / sel["p90_mm"] * 100).round(0)
flagged = sel[sel["above_p90"]].sort_values("rank")
end = pd.Timestamp(dekad) + pd.Timedelta(days=10)

tab_rank, tab_trigger, tab_supply, tab_ncr, tab_evidence = st.tabs(
    ["Exposure ranking", "Rainfall trigger", "Supply checklist", "Metro Manila flood drill-down",
     "Leptospirosis evidence"])

with tab_rank:
    st.subheader("Which provinces combine extreme rain with the most vulnerable people?")
    st.caption("Flood-Health Exposure Index = 0.4 hazard + 0.3 vulnerable count + 0.3 vulnerable share "
               "(children under 5 and adults 65 and over). Confidence = share of 1,000 random weight sets "
               "that keep the province in the top 10.")
    left, right = st.columns([3, 2])
    with left:
        st.plotly_chart(province_map(idx, "index", "Flood-Health Exposure Index (0 to 100)", "YlOrRd",
                                     hover={"rank": True, "index": ":.1f", "PCODE": False}),
                        use_container_width=True)
    with right:
        pick = st.selectbox("Find your province", sorted(idx["province"]), index=None,
                            placeholder="Type a province name")
        if pick:
            r = idx[idx["province"] == pick].iloc[0]
            a, b, c = st.columns(3)
            a.metric("Rank", f"{r['rank']} of {len(idx)}")
            b.metric("Index", f"{r['index']:.1f}")
            c.metric("In top 10", f"{r['top10_pct']:.0f}% of runs")
            st.caption(f"Rank range across weight sets: {r['rank_best']} to {r['rank_worst']}. "
                       f"Vulnerable people: {r['vulnerable']:,.0f} ({r['vulnerable_share']:.1%}).")
        table = idx[["rank", "province", "index", "hazard", "vulnerable", "vulnerable_share",
                     "top10_pct", "confidence"]].rename(columns={
            "rank": "Rank", "province": "Province", "index": "Index", "hazard": "Hazard",
            "vulnerable": "Vulnerable people", "vulnerable_share": "Vulnerable share",
            "top10_pct": "Top-10 runs (%)", "confidence": "Confidence"})
        st.dataframe(table, hide_index=True, height=440, use_container_width=True, column_config={
            "Index": st.column_config.ProgressColumn(format="%.1f", min_value=0, max_value=100),
            "Hazard": st.column_config.NumberColumn(format="%.0f"),
            "Vulnerable people": st.column_config.NumberColumn(format="localized"),
            "Vulnerable share": st.column_config.NumberColumn(format="percent"),
            "Top-10 runs (%)": st.column_config.NumberColumn(format="%.0f"),
        })

with tab_trigger:
    st.subheader(f"{len(flagged)} provinces passed their 90th percentile in the period starting {dekad}")
    if (sel["version"] == "prelim").any():
        st.caption("Preliminary rainfall: WFP may revise this period when the final CHIRPS data is released.")
    a, b, c = st.columns(3)
    # The heavy rain can fall on any day of the 10-day period, so prepare from its first day and
    # stand down from its last day.
    a.metric("Hospitals ready for cases by", f"{pd.Timestamp(dekad) + pd.Timedelta(weeks=RISE_FROM - 1):%d %b %Y}")
    p0, p1 = pd.Timestamp(dekad) + pd.Timedelta(weeks=PEAK), end + pd.Timedelta(weeks=PEAK)
    b.metric("Expected case peak", f"{p0:%d}–{p1:%d %b %Y}" if p0.month == p1.month else f"{p0:%d %b}–{p1:%d %b}")
    c.metric("Stay alert until", f"{end + pd.Timedelta(weeks=RISE_TO):%d %b %Y}")
    st.caption("Doxycycline prophylaxis works only if taken within 24 to 72 hours of wading, or once a week while "
               "people live in flooded areas, so it must already be in the barangays when the rain comes (see the "
               "monthly odds and the rain forecast). These dates are for the case surge that follows.")
    share = weekly_share(rain)
    as_of = share.index[share.index <= end].max()
    fc = forecast(share, as_of)
    top = fc.loc[fc["rise_pct"].idxmax()]
    st.markdown(f"**Forecast:** national leptospirosis cases are expected to run up to **{top['rise_pct']:.0f}% "
                f"above** a week without extreme rain, highest in the week of {top['week_start']:%d %b %Y}. "
                f"This counts all extreme rain in the 6 weeks up to {as_of + pd.Timedelta(days=6):%d %b}, "
                "not only the selected period.")
    fcfig = go.Figure(go.Bar(x=[f"+{h} wk<br>{d:%d %b}" for h, d in zip(fc["weeks_ahead"], fc["week_start"])],
                             y=fc["rise_pct"], marker_color="#c1121f",
                             text=[f"+{v:.0f}%" for v in fc["rise_pct"]], textposition="outside"))
    fcfig.update_layout(height=230, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="Expected rise (%)",
                        yaxis_range=[0, max(10, fc["rise_pct"].max() * 1.3)])
    st.plotly_chart(fcfig, use_container_width=True)
    st.caption("Indicative. National model fitted on 2019 to 2023 DOH data; rain after the selected period is "
               "assumed normal. See the Leptospirosis evidence tab for how well it predicted 2023.")
    left, right = st.columns([3, 2])
    with left:
        st.plotly_chart(province_map(sel, "pct_of_p90", "10-day rainfall as % of the province's 90th percentile",
                                     "Blues", range_color=(0, 200),
                                     hover={"rfh": ":.0f", "p90_mm": ":.0f", "PCODE": False}),
                        use_container_width=True)
    with right:
        st.markdown("**Flagged provinces, highest exposure first**")
        st.dataframe(flagged[["rank", "province", "rfh", "p90_mm", "vulnerable"]].rename(columns={
            "rank": "Exposure rank", "province": "Province", "rfh": "Rain (mm)", "p90_mm": "90th pct (mm)",
            "vulnerable": "Vulnerable people"}), hide_index=True, height=520, use_container_width=True,
            column_config={"Rain (mm)": st.column_config.NumberColumn(format="%.0f"),
                           "90th pct (mm)": st.column_config.NumberColumn(format="%.0f"),
                           "Vulnerable people": st.column_config.NumberColumn(format="localized")})

with tab_supply:
    st.subheader(f"Supply checklist for the {len(flagged)} flagged provinces")
    st.caption("Planning quantities only. The rates below are assumptions to adjust; check them against "
               "current DOH guidance before use. Regimen for people living in flooded areas: doxycycline 200 mg "
               "once a week until exposure ends (PhilHealth). Doxycycline is generally avoided in pregnancy and young "
               "children; plan alternatives with a doctor.")
    a, b, c = st.columns(3)
    cover = a.slider("Share of population expected to wade in floodwater (%)", 0.5, 20.0, 2.0, 0.5)
    weeks = b.slider("Weeks people stay in flooded areas (one dose a week)", 1, 8, 2)
    caps = c.number_input("Doxycycline 100 mg capsules per dose", 1, 4, 2)
    if flagged.empty:
        st.info("No province passed its 90th percentile in this period. Pick another period in the sidebar.")
    else:
        sup = flagged[["rank", "province", "population", "under5", "over65"]].copy()
        sup["exposed"] = (sup["population"] * cover / 100).round(0)
        sup["doxy_caps"] = (sup["exposed"] * weeks * caps).round(0)
        sup = sup.rename(columns={"rank": "Exposure rank", "province": "Province", "population": "Population",
                                  "under5": "Children under 5", "over65": "Adults 65+",
                                  "exposed": "People to cover", "doxy_caps": "Doxycycline 100 mg capsules"})
        fmt = {k: st.column_config.NumberColumn(format="localized") for k in sup.columns[2:]}
        st.dataframe(sup, hide_index=True, use_container_width=True, column_config=fmt)
        t = sup[["People to cover", "Doxycycline 100 mg capsules", "Children under 5"]].sum()
        st.markdown(
            f"**Totals:** {t['People to cover']:,.0f} people to cover, "
            f"{t['Doxycycline 100 mg capsules']:,.0f} doxycycline capsules.\n\n"
            "**Also check, for each flagged province:**\n"
            "- [ ] Doxycycline at evacuation centres and rural health units before the flood, for doses within 72 "
            "hours of wading\n"
            f"- [ ] Paediatric alternatives for the {t['Children under 5']:,.0f} children under 5, per clinical guidance\n"
            "- [ ] Leptospirosis rapid diagnostic tests at provincial hospitals\n"
            "- [ ] Antibiotics and IV fluids for severe cases at referral hospitals\n"
            "- [ ] Advisories on avoiding floodwater and seeking care early for fever"
        )
        st.download_button("Download checklist (CSV)", sup.to_csv(index=False).encode(),
                           file_name=f"iris_checklist_{dekad}.csv", mime="text/csv")

with tab_evidence:
    st.subheader(f"Leptospirosis cases rise {RISE_FROM} to {RISE_TO} weeks after widespread heavy rain")
    st.caption("National weekly DOH surveillance counts, 2019 to 2023. Case counts are not available by province, "
               "and no open flood-event data exists, so widespread extreme rain stands in for flooding.")
    lep = weekly.dropna(subset=["cases"])
    yearly = lep.groupby("iso_year")["cases"].agg(["sum", "count"]).reset_index()
    seasonal = lep.groupby("iso_week")["cases"].mean().rolling(3, center=True, min_periods=1).mean().reset_index()
    a, b = st.columns(2)
    with a:
        st.markdown("**Cases per year** (weeks reported in brackets)")
        yfig = go.Figure(go.Bar(x=yearly["iso_year"].astype(str), y=yearly["sum"], marker_color="#c1121f",
                                text=[f"{v:,.0f} ({n} wk)" for v, n in zip(yearly["sum"], yearly["count"])],
                                textposition="outside"))
        yfig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="Cases",
                           yaxis_range=[0, yearly["sum"].max() * 1.2])
        st.plotly_chart(yfig, use_container_width=True)
    with b:
        st.markdown("**Average cases by week of the year** (3-week moving average)")
        sfig = go.Figure(go.Scatter(x=seasonal["iso_week"], y=seasonal["cases"], mode="lines",
                                    line=dict(color="#c1121f", width=2), fill="tozeroy",
                                    fillcolor="rgba(193,18,31,0.1)"))
        sfig.add_vrect(x0=22, x1=48, fillcolor="#9ecae1", opacity=0.2, line_width=0,
                       annotation_text="June to November", annotation_position="top left")
        sfig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="Week of year",
                           yaxis_title="Average cases")
        st.plotly_chart(sfig, use_container_width=True)
    st.markdown("**Weekly cases against the share of provinces with extreme rain** (cases end in 2023; rainfall runs to the latest period)")
    w = weekly.dropna(subset=["cases"])
    fig = go.Figure()
    fig.add_bar(x=weekly["week_start"], y=weekly["share_prov_above_p90"] * 100, name="Provinces with extreme rain (%)",
                marker_color="#9ecae1", yaxis="y2")
    fig.add_scatter(x=w["week_start"], y=w["cases"], name="Leptospirosis cases per week", mode="lines",
                    line=dict(color="#c1121f", width=2))
    fig.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0), legend=dict(orientation="h", y=1.1),
                      xaxis=dict(range=[w["week_start"].min(), weekly["week_start"].max()]),
                      yaxis=dict(title="Cases"), yaxis2=dict(title="% provinces", overlaying="y", side="right",
                                                              showgrid=False))
    st.plotly_chart(fig, use_container_width=True)
    st.markdown(f"**Lag model: risk is highest {PEAK} weeks after heavy rain** (negative binomial, 95% CI)")
    lagfig = go.Figure(go.Scatter(
        x=main["lag_weeks"], y=main["rr"], mode="markers", marker=dict(size=9, color="#2a6f97"),
        error_y=dict(type="data", symmetric=False, array=main["rr_high"] - main["rr"],
                     arrayminus=main["rr"] - main["rr_low"])))
    lagfig.add_hline(y=1, line_color="grey")
    lagfig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="Weeks after heavy rain",
                         yaxis_title="Relative risk (95% CI)")
    st.plotly_chart(lagfig, use_container_width=True)

    a, b = st.columns(2)
    with a:
        n_ev = events["event_week"].nunique()
        st.markdown(f"**After the {n_ev} heaviest rain weeks, cases roughly double by week 3**")
        med = events.groupby("weeks_from_event")["ratio_to_before"].median().reset_index()
        efig = go.Figure()
        for ev, g in events.groupby("event_week"):
            efig.add_scatter(x=g["weeks_from_event"], y=g["ratio_to_before"], mode="lines",
                             line=dict(color="#cccccc", width=1), name=f"{ev:%d %b %Y}", showlegend=False)
        efig.add_scatter(x=med["weeks_from_event"], y=med["ratio_to_before"], mode="lines+markers",
                         line=dict(color="#c1121f", width=3), name="Median of events")
        efig.add_vline(x=0, line_dash="dash", line_color="#2a6f97", annotation_text="heavy rain week")
        efig.add_hline(y=1, line_color="grey")
        efig.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="Weeks from the event",
                           yaxis_title="Cases vs the 4 weeks before", yaxis_range=[0, 4],
                           legend=dict(orientation="h", y=1.1))
        st.plotly_chart(efig, use_container_width=True)
        st.caption("Grey lines are individual events (hover for dates); red is the median.")
    with b:
        st.markdown("**Only leptospirosis follows heavy rain this way**")
        order = list(dict.fromkeys(diseases["disease"]))
        piv = diseases.pivot(index="disease", columns="lag_weeks", values="rr").loc[order]
        sig = diseases.pivot(index="disease", columns="lag_weeks", values="significant").loc[order].fillna("")
        txt = [[f"{v:.2f}{'*' if s == 'higher' else ''}" for v, s in zip(r1, r2)] for r1, r2 in zip(piv.values, sig.values)]
        hfig = go.Figure(go.Heatmap(z=piv.values, x=[f"{c} wk" for c in piv.columns], y=piv.index, text=txt,
                                    texttemplate="%{text}", textfont=dict(size=11), colorscale="RdBu_r", zmid=1, zmin=0.8, zmax=1.2,
                                    colorbar=dict(title="RR")))
        hfig.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0), yaxis_autorange="reversed",
                           xaxis_title="Weeks after heavy rain")
        st.plotly_chart(hfig, use_container_width=True)
        st.caption("Relative risk per 10-point rise in provinces with extreme rain; * = 95% CI above 1. "
                   "Rabies and acute flaccid paralysis are negative controls.")

    sc = FC_SCORES.set_index("model")
    st.markdown("**Forecast test: trained on 2019 to 2022, predicting 2023 without seeing it**")
    btfig = go.Figure()
    btfig.add_scatter(x=FC_BACKTEST["week_start"], y=FC_BACKTEST["cases"], name="Actual cases", mode="lines+markers",
                      line=dict(color="#333333", width=1.5), marker=dict(size=4))
    btfig.add_scatter(x=FC_BACKTEST["week_start"], y=FC_BACKTEST["Seasonal only"], name="Seasonal pattern only",
                      mode="lines", line=dict(color="#9ecae1", width=2, dash="dot"))
    btfig.add_scatter(x=FC_BACKTEST["week_start"], y=FC_BACKTEST["Seasonal + rain (lags 2 to 6)"],
                      name="Seasonal + recent rain", mode="lines", line=dict(color="#c1121f", width=2.5))
    btfig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="Weekly cases",
                        legend=dict(orientation="h", y=1.12))
    st.plotly_chart(btfig, use_container_width=True)
    s_only, s_rain = sc.loc["Seasonal only"], sc.loc["Seasonal + rain (lags 2 to 6)"]
    st.caption(f"Adding recent rain raises the correlation with actual 2023 cases from {s_only['corr']:.2f} to "
               f"{s_rain['corr']:.2f} and cuts the average weekly error from {s_only['mae']:.0f} to "
               f"{s_rain['mae']:.0f} cases ({(1 - s_rain['mae'] / s_only['mae']):.0%} better). Both are rescaled to "
               "the 2023 average, since a new year's overall level is not known in advance.")

with tab_ncr:
    geo_ncr, ncr = load_ncr()
    st.subheader("Same rain, different flood: who in Metro Manila lives where the water gets deep?")
    st.caption("UP NOAH 100-year flood hazard map overlaid on 1,710 barangays and 2020 census ages. People in a hazard "
               "zone are estimated by the share of the barangay's area in that zone, assuming people are spread "
               "evenly. Medium hazard is 0.5 to 1.5 m of flooding; high is over 1.5 m.")
    ncr_flag = sel.loc[sel["PCODE"] == "PH13074", "above_p90"]
    if len(ncr_flag) and bool(ncr_flag.iloc[0]):
        st.error(f"Metro Manila passed its 90th percentile in the period starting {dekad}. "
                 "Start with the barangays at the top of the list below.")
    else:
        st.info(f"Metro Manila did not pass its 90th percentile in the period starting {dekad}. "
                "This view is for planning ahead.")
    tot_p, tot_v = ncr["people_med_high"].sum(), ncr["vulnerable_med_high"].sum()
    a, b, c = st.columns(3)
    a.metric(f"People in medium or high flood zones ({tot_p / ncr['population'].sum():.0%} of NCR)", f"{tot_p:,.0f}")
    b.metric("Of them, under 5 or 65+", f"{tot_v:,.0f}")
    c.metric("Barangays mostly (over 50%) in these zones", f"{(ncr['flood_share_med_high'] > 0.5).sum():,}")
    metric = st.radio("Colour the map by", ["Vulnerable people in medium/high zones", "Share of area in medium/high zones"],
                      horizontal=True)
    col = "vulnerable_med_high" if metric.startswith("Vulnerable") else "flood_share_med_high"
    left, right = st.columns([3, 2])
    with left:
        fig = px.choropleth(ncr, geojson=geo_ncr, locations="bgy_code", featureidkey="properties.bgy_code",
                            color=col, color_continuous_scale="Reds" if col.startswith("vul") else "Blues",
                            range_color=(0, ncr[col].quantile(0.98)), hover_name="barangay",
                            hover_data={"city": True, "population": ":,", "flood_share_med_high": ":.0%",
                                        "vulnerable_med_high": ":,.0f", "bgy_code": False},
                            labels={"vulnerable_med_high": "Vulnerable in zone", "flood_share_med_high": "Area in zone",
                                    "population": "Population", "city": "City"})
        fig.update_geos(visible=False, projection_type="mercator", lonaxis_range=[120.9, 121.14],
                        lataxis_range=[14.34, 14.79])
        fig.update_traces(marker_line_width=0.2, marker_line_color="white")
        fig.update_layout(height=680, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)
    with right:
        cities = ["All cities"] + sorted(ncr["city"].unique())
        pick = st.selectbox("City", cities)
        view = ncr if pick == "All cities" else ncr[ncr["city"] == pick]
        st.dataframe(view.sort_values("vulnerable_med_high", ascending=False)[
            ["barangay", "city", "population", "flood_share_med_high", "vulnerable_med_high"]].rename(columns={
                "barangay": "Barangay", "city": "City", "population": "Population",
                "flood_share_med_high": "Area in medium/high zone", "vulnerable_med_high": "Vulnerable in zone"}),
            hide_index=True, height=600, use_container_width=True, column_config={
                "Population": st.column_config.NumberColumn(format="localized"),
                "Area in medium/high zone": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                "Vulnerable in zone": st.column_config.NumberColumn(format="localized")})
    by_city = (ncr.groupby("city")[["population", "people_med_high", "vulnerable_med_high"]].sum()
               .sort_values("vulnerable_med_high").reset_index())
    st.markdown("**By city: children under 5 and adults 65+ living in medium or high flood zones**")
    cfig = go.Figure(go.Bar(y=by_city["city"], x=by_city["vulnerable_med_high"], orientation="h", marker_color="#c1121f",
                            text=[f"{v:,.0f} ({p / t:.0%} of residents in zone)" for v, p, t in
                                  zip(by_city["vulnerable_med_high"], by_city["people_med_high"], by_city["population"])],
                            textposition="outside"))
    cfig.update_layout(height=480, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="Vulnerable people in zone",
                       xaxis_range=[0, by_city["vulnerable_med_high"].max() * 1.45])
    st.plotly_chart(cfig, use_container_width=True)
