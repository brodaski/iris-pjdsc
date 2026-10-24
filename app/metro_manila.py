"""IRIS (Infection Risk from Inundation and Storms), Metro Manila version: when heavy rain hits NCR, which barangays to prepare first.

Run with:  streamlit run app/metro_manila.py
Uses the same processed files as app/app.py plus data/processed/ncr_barangays.geojson (notebook 03) and the
outlook files from notebook 04.
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from rain_data import DATA, daily_share, forecast, live_rain, rain_forecast, weekly_share

NCR = "PH13074"
CARINA = "2024-07-21"   # Typhoon Carina (Gaemi) and southwest monsoon floods

LOGO_DIR = Path(__file__).resolve().parent.parent / "assets"
st.set_page_config(page_title="IRIS: Metro Manila", page_icon=str(LOGO_DIR / "iris_mark.png"), layout="wide")


def area_km2(geom):
    """Area of a GeoJSON polygon or multipolygon in km², on a flat projection around 14.6° N (well under 1% off
    for barangay-sized shapes)."""
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    kx, ky = 111.320 * math.cos(math.radians(14.6)), 110.574
    total = 0.0
    for poly in polys:
        for i, ring in enumerate(poly):
            x, y = np.array(ring)[:, 0] * kx, np.array(ring)[:, 1] * ky
            a = abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2
            total += -a if i else a   # holes subtract
    return total


@st.cache_data
def load():
    rain = pd.read_csv(DATA / "dekad_rain.csv", parse_dates=["date"])
    lag = pd.read_csv(DATA / "lag_results.csv")
    events = pd.read_csv(DATA / "event_study.csv", parse_dates=["event_week"])
    geo = json.loads((DATA / "ncr_barangays.geojson").read_text())
    bgy = pd.DataFrame([f["properties"] for f in geo["features"]])
    bgy["area_km2"] = [area_km2(f["geometry"]) for f in geo["features"]]
    # Vulnerable people in medium/high zones per km² of barangay: high where many live crowded in the zones.
    bgy["vulnerable_per_km2"] = bgy["vulnerable_med_high"] / bgy["area_km2"]
    months = pd.read_csv(DATA / "ncr_month_outlook.csv")
    floods = pd.read_csv(DATA / "ncr_flood_events.csv")
    base = pd.read_csv(DATA / "weekly_case_baseline.csv")
    cases = pd.read_csv(DATA / "weekly_national.csv").dropna(subset=["cases"])
    backtest = pd.read_csv(DATA / "forecast_backtest.csv", parse_dates=["week_start"])
    scores = pd.read_csv(DATA / "forecast_scores.csv")
    return rain, lag, events, geo, bgy, months, floods, base, cases, backtest, scores


rain, lag, events, geo, bgy, months, floods, base, cases, backtest, scores = load()
FLOOD = months["flood_mm"].iloc[0]
rain, rain_source = live_rain(rain)
ncr_rain = rain[rain["PCODE"] == NCR].sort_values("date").reset_index(drop=True)
P90 = ncr_rain["p90_mm"].iloc[0]

main = lag[lag["model"].str.startswith("Main")]
peak = main.loc[main["rr"].idxmax()]
sig = main.loc[main["significant"], "lag_weeks"]
PEAK, RISE_FROM, RISE_TO = int(peak["lag_weeks"]), int(sig.min()), int(sig.max())

with st.sidebar:
    st.image(str(LOGO_DIR / "iris_logo.png"), width=260)
    st.caption("Metro Manila: which barangays to prepare for leptospirosis after heavy rain, and when.")
    dekads = list(ncr_rain["date"].dt.strftime("%Y-%m-%d"))[::-1]
    example = st.toggle("Show example: Typhoon Carina, July 2024", value=False)
    start = CARINA if example and CARINA in dekads else dekads[0]
    dekad = st.selectbox("10-day rainfall period (start date)", dekads, index=dekads.index(start),
                         help="Newest first. Rainfall is updated from HDX every 10 days.")
    st.caption(f"Rainfall source: {rain_source}.")
    st.divider()
    st.markdown(f"**Alert window:** cases peak **{PEAK} weeks** after heavy rain and stay raised from week "
                f"{RISE_FROM} to week {RISE_TO} (national DOH surveillance, 2019 to 2023).")
    with st.expander("About the data"):
        st.markdown(
            "- Rainfall: CHIRPS 10-day rainfall for Metro Manila, WFP and Climate Hazards Center via HDX.\n"
            "- Flood hazard: UP NOAH Center, Metro Manila 100-year flood hazard map.\n"
            "- Population: PSA 2020 Census by single-year age and barangay, via HDX.\n"
            "- Boundaries: NAMRIA and PSA barangay boundaries (COD-AB 2025), via HDX.\n"
            "- Cases: weekly national leptospirosis counts, DOH reports compiled by the University of Mindanao.\n\n"
            "**Limits:** people in a flood zone are estimated by area share; rain is averaged over all of Metro "
            "Manila; the alert window is national; no barangay case data is open."
        )

row = ncr_rain[ncr_rain["date"] == pd.Timestamp(dekad)].iloc[0]
flagged = bool(row["above_p90"])
end = pd.Timestamp(dekad) + pd.Timedelta(days=10)

tab_alert, tab_outlook, tab_flood, tab_supply, tab_evidence = st.tabs(
    ["Rainfall alert", "Outlook", "Flood exposure by barangay", "Supply checklist", "Evidence"])

with tab_alert:
    if flagged:
        st.error(f"ALERT: Metro Manila got {row['rfh']:.0f} mm in the 10 days from {dekad}, above its 90th percentile "
                 f"of {P90:.0f} mm.")
    else:
        st.success(f"No alert: Metro Manila got {row['rfh']:.0f} mm in the 10 days from {dekad}, below its 90th "
                   f"percentile of {P90:.0f} mm.")
    if row["version"] == "prelim":
        st.caption("Preliminary rainfall: WFP may revise this period when the final CHIRPS data is released.")
    a, b, c = st.columns(3)
    if flagged:
        # The heavy rain can fall on any day of the 10-day period, so prepare from its first day and
        # stand down from its last day.
        a.metric("Hospitals ready for cases by", f"{pd.Timestamp(dekad) + pd.Timedelta(weeks=RISE_FROM - 1):%d %b %Y}")
        p0, p1 = pd.Timestamp(dekad) + pd.Timedelta(weeks=PEAK), end + pd.Timedelta(weeks=PEAK)
        b.metric("Expected case peak", f"{p0:%d}–{p1:%d %b %Y}" if p0.month == p1.month else f"{p0:%d %b}–{p1:%d %b}")
        c.metric("Stay alert until", f"{end + pd.Timedelta(weeks=RISE_TO):%d %b %Y}")
        st.caption("Doxycycline prophylaxis works only if taken within 24 to 72 hours of wading, or once a week while "
                   "people live in flooded areas, so it must already be in the barangays when the rain comes (see the "
                   "16-day forecast in the Outlook tab). These dates are for the case surge that follows.")
    else:
        a.metric("Rain this period", f"{row['rfh']:.0f} mm")
        b.metric("Alert threshold (90th percentile)", f"{P90:.0f} mm")
        c.metric("Share of threshold", f"{row['rfh'] / P90:.0%}")

    st.markdown("**Metro Manila 10-day rainfall, last 3 years** (red = above the alert threshold)")
    recent = ncr_rain[ncr_rain["date"] >= ncr_rain["date"].max() - pd.DateOffset(years=3)]
    rfig = go.Figure(go.Bar(x=recent["date"], y=recent["rfh"],
                            marker_color=["#c1121f" if f else "#9ecae1" for f in recent["above_p90"]],
                            hovertemplate="%{x|%d %b %Y}: %{y:.0f} mm<extra></extra>"))
    rfig.add_hline(y=P90, line_dash="dash", line_color="#333333", annotation_text=f"Alert threshold {P90:.0f} mm")
    if pd.Timestamp(dekad) >= recent["date"].min():
        rfig.add_vline(x=pd.Timestamp(dekad), line_color="#2a6f97", line_width=2)
    rfig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="mm per 10 days")
    st.plotly_chart(rfig, width="stretch")

    share = weekly_share(rain)
    as_of = share.index[share.index <= end].max()
    fc = forecast(share, as_of)
    top = fc.loc[fc["rise_pct"].idxmax()]
    st.markdown(f"**National case forecast:** up to **{top['rise_pct']:.0f}% above** a week without extreme rain, "
                f"highest in the week of {top['week_start']:%d %b %Y}, counting extreme rain across all provinces "
                f"in the 6 weeks up to {as_of + pd.Timedelta(days=6):%d %b}.")
    fcfig = go.Figure(go.Bar(x=[f"+{h} wk<br>{d:%d %b}" for h, d in zip(fc["weeks_ahead"], fc["week_start"])],
                             y=fc["rise_pct"], marker_color="#c1121f",
                             text=[f"+{v:.0f}%" for v in fc["rise_pct"]], textposition="outside"))
    fcfig.update_layout(height=220, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="Expected rise (%)",
                        yaxis_range=[0, max(10, fc["rise_pct"].max() * 1.3)])
    st.plotly_chart(fcfig, width="stretch")
    st.caption("Indicative and national: case data by city or barangay is not openly available.")

with tab_outlook:
    st.subheader("What the next weeks and months may bring")
    om, om_source = rain_forecast()
    today = pd.Timestamp.now(tz="Asia/Manila").tz_localize(None).normalize()
    this_week = today - pd.Timedelta(days=today.weekday())

    # 1. Rain forecast for Metro Manila
    st.markdown("#### 1. Rain in the next 16 days")
    peak10 = None
    if om is not None:
        n = om[om["PCODE"] == NCR].sort_values("day").reset_index(drop=True)
        n["sum10"] = n["mm"].rolling(10).sum()
        ahead = n[n["day"] >= today + pd.Timedelta(days=9)]   # windows that end in the forecast
        top10 = ahead.loc[ahead["sum10"].idxmax()]
        peak10 = float(top10["sum10"])
        st.caption(f"Source: {om_source}, one point in central Metro Manila. Weather models and CHIRPS measure rain "
                   "differently, so treat the totals as a guide.")
        dfig = go.Figure(go.Bar(x=n["day"], y=n["mm"], marker_color=["#2a6f97" if f else "#9ecae1" for f in n["is_forecast"]],
                                hovertemplate="%{x|%d %b}: %{y:.0f} mm<extra></extra>"))
        dfig.add_vline(x=today, line_dash="dash", line_color="#333333")
        dfig.update_layout(height=220, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="mm per day")
        st.plotly_chart(dfig, width="stretch")
        st.markdown(f"Wettest 10 days in the forecast: **{peak10:.0f} mm**, ending {top10['day']:%d %b} "
                    f"(dark bars are forecast, light bars the past 3 weeks).")
    else:
        st.info(f"{om_source}. Use the slider below to plan for a rainfall scenario.")

    # 2. Flood outlook by barangay
    st.markdown("#### 2. Flood outlook by barangay")
    default = int(round(peak10 if peak10 is not None else row["rfh"]))
    plan_mm = st.slider("10-day rainfall to plan for (mm)", 0, 700, min(default, 700), step=10,
                        help=f"Starts at the forecast (or the selected period). Alert level {P90:.0f} mm; "
                             f"flood level {FLOOD:.0f} mm.")
    ev_txt = ", ".join(f"{e} ({mm:.0f} mm)" for e, mm in zip(floods["event"], floods["rfh"]))
    if plan_mm >= FLOOD:
        level, share_col, cmap = "Widespread flooding likely", "flood_share_med_high", "Reds"
        st.error(f"**{level}.** {plan_mm} mm in 10 days is at or above {FLOOD:.0f} mm, the level reached in every "
                 f"major Metro Manila flood since 2009: {ev_txt}. Expect medium and high hazard zones to flood.")
    elif plan_mm >= P90:
        level, share_col, cmap = "Flooding likely in high hazard zones", "share_var3", "Oranges"
        st.warning(f"**{level}.** {plan_mm} mm is above the leptospirosis alert level ({P90:.0f} mm) but below the "
                   f"flood level ({FLOOD:.0f} mm). Expect flooding first in high hazard zones (over 1.5 m in the "
                   "100-year map).")
    else:
        level, share_col, cmap = None, None, None
        st.success(f"**No widespread flooding expected.** {plan_mm} mm is below the alert level ({P90:.0f} mm). "
                   "Low spots and blocked drains can still flood.")
    if level:
        f = bgy.assign(people_risk=bgy["population"] * bgy[share_col],
                       vuln_risk=(bgy["under5"] + bgy["over65"]) * bgy[share_col])
        f = f[f["people_risk"] > 0]
        a, b, c = st.columns(3)
        a.metric("Barangays with any area in these zones", f"{len(f):,}")
        b.metric("People in the zones expected to flood", f"{f['people_risk'].sum():,.0f}")
        c.metric("Of them, under 5 or 65+", f"{f['vuln_risk'].sum():,.0f}")
        left, right = st.columns([3, 2])
        with left:
            ofig = px.choropleth(f, geojson=geo, locations="bgy_code", featureidkey="properties.bgy_code",
                                 color="vuln_risk", color_continuous_scale=cmap,
                                 range_color=(0, f["vuln_risk"].quantile(0.98)), hover_name="barangay",
                                 hover_data={"city": True, "people_risk": ":,.0f", "vuln_risk": ":,.0f", "bgy_code": False},
                                 labels={"vuln_risk": "Under 5 or 65+ at risk", "people_risk": "People at risk",
                                         "city": "City"})
            ofig.update_geos(visible=False, projection_type="mercator", lonaxis_range=[120.9, 121.14],
                             lataxis_range=[14.34, 14.79])
            ofig.update_traces(marker_line_width=0.2, marker_line_color="white")
            ofig.update_layout(height=560, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(ofig, width="stretch")
        with right:
            st.dataframe(f.sort_values("vuln_risk", ascending=False)[["barangay", "city", "people_risk", "vuln_risk"]]
                         .round(0).rename(columns={"barangay": "Barangay", "city": "City", "people_risk": "People at risk",
                                          "vuln_risk": "Under 5 or 65+"}),
                         hide_index=True, height=560, width="stretch", column_config={
                             k: st.column_config.NumberColumn(format="localized") for k in ["People at risk", "Under 5 or 65+"]})
    st.caption("A rain trigger on the UP NOAH 100-year hazard map, not a flood model: it does not include river levels, "
               "tides or drainage, and shows where flooding is most likely, not its exact extent.")

    # 3. Leptospirosis case outlook
    st.markdown("#### 3. Leptospirosis cases in the next weeks (national)")
    share = weekly_share(rain)
    as_of = share.index.max()
    future = daily_share(om[["PCODE", "day", "mm"]]) if om is not None else None
    horizon = (this_week - as_of).days // 7 + 6
    fc = forecast(share, as_of, horizon=horizon, future=future)
    fc = fc[fc["week_start"] >= this_week].copy()
    fc["iso_week"] = fc["week_start"].dt.isocalendar().week.clip(upper=52).astype(int)
    fc = fc.merge(base, on="iso_week", how="left")
    fc["expected"] = fc["baseline_cases"] * (1 + fc["rise_pct"] / 100)
    fc["uses_forecast"] = fc["week_start"] - pd.Timedelta(weeks=2) >= this_week
    fc["label"] = "Week of<br>" + fc["week_start"].dt.strftime("%d %b")
    cfig2 = go.Figure()
    cfig2.add_bar(x=fc["label"], y=fc["expected"],
                  marker_color=["#e07a5f" if u else "#c1121f" for u in fc["uses_forecast"]],
                  text=[f"{e:.0f} ({r:+.0f}%)" for e, r in zip(fc["expected"], fc["rise_pct"])],
                  textposition="outside", name="Expected cases")
    cfig2.add_scatter(x=fc["label"], y=fc["baseline_cases"], mode="lines+markers", line=dict(color="#333333",
                      dash="dash"), name="Without extreme rain")
    past = fc[["label", "iso_week"]].merge(cases[["iso_year", "iso_week", "cases"]], on="iso_week")
    for (yr, g), color in zip(past.groupby("iso_year"), ["#d9d9d9", "#bdbdbd", "#969696", "#636363", "#252525"]):
        cfig2.add_scatter(x=g["label"], y=g["cases"], mode="markers", name=f"Actual {yr}",
                          marker=dict(color=color, size=9, symbol="diamond"))
    cfig2.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="Cases a week (Philippines)",
                        yaxis_range=[0, max(fc["expected"].max(), past["cases"].max() if len(past) else 0) * 1.3],
                        legend=dict(orientation="h", y=1.1))
    st.plotly_chart(cfig2, width="stretch")
    rain_note = ("Lighter bars depend on forecast rain from Open-Meteo." if future is not None else
                 f"Without the rain forecast, rain after {as_of + pd.Timedelta(days=6):%d %b} is assumed normal, so "
                 "later weeks may be underestimated.")
    st.caption(f"Rain in the past 2 to 6 weeks across all 81 provinces drives the forecast (notebook 02; it beat the "
               f"seasonal pattern on 2023). The dashed line is a week with no extreme rain at 2023 case levels. "
               f"{rain_note} Diamonds are actual national cases in the same weeks of 2019 to 2023, the latest "
               f"open data. National only: no city or barangay case data is open.")

    st.markdown("**Track record: forecast vs actual cases in 2023** (the model was trained on 2019 to 2022 only)")
    tfig = go.Figure()
    tfig.add_scatter(x=backtest["week_start"], y=backtest["cases"], mode="lines+markers", name="Actual cases",
                     line=dict(color="#252525", width=2), marker=dict(size=5))
    for col, color, dash in [("Seasonal + rain (lags 2 to 6)", "#c1121f", None), ("Seasonal only", "#9ecae1", "dot")]:
        tfig.add_scatter(x=backtest["week_start"], y=backtest[col], mode="lines", name=col,
                         line=dict(color=color, width=2, dash=dash))
    tfig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="Cases a week (Philippines)",
                       legend=dict(orientation="h", y=1.12))
    st.plotly_chart(tfig, width="stretch")
    sc = scores.set_index("model")
    st.caption(f"With rain, the forecast followed actual 2023 cases more closely: correlation "
               f"{sc.loc['Seasonal + rain (lags 2 to 6)', 'corr']:.2f} vs {sc.loc['Seasonal only', 'corr']:.2f} for the "
               f"seasonal pattern alone, and an average error of {sc.loc['Seasonal + rain (lags 2 to 6)', 'mae']:.0f} vs "
               f"{sc.loc['Seasonal only', 'mae']:.0f} cases a week. Both are scaled to the 2023 average, since the "
               "year's overall level is not known in advance. Cases for 2024 to 2026 are only in DOH PDF reports, so "
               "they are not in the data yet.")

    # 4. Months ahead
    st.markdown("#### 4. The months ahead: chance of an alert in Metro Manila")
    mnames = pd.to_datetime(months["month"], format="%m").dt.strftime("%b")
    nxt = [(today.month - 1 + i) % 12 + 1 for i in range(1, 7)]
    mfig = go.Figure()
    mfig.add_bar(x=mnames, y=months["chance_alert"] * 100, name=f"Alert (over {P90:.0f} mm in 10 days)",
                 marker_color=["#c1121f" if m in nxt else "#e8a0a5" for m in months["month"]])
    mfig.add_bar(x=mnames, y=months["chance_flood"] * 100, name=f"Flood level (over {FLOOD:.0f} mm)",
                 marker_color=["#2a6f97" if m in nxt else "#9ecae1" for m in months["month"]])
    mfig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="Chance in a year (%)",
                       barmode="group", legend=dict(orientation="h", y=1.12))
    st.plotly_chart(mfig, width="stretch")
    nx = months.set_index("month").loc[nxt]
    st.markdown("**Next 6 months:** " + ", ".join(
        f"{pd.Timestamp(2000, m, 1):%b} {r.chance_alert:.0%}" for m, r in nx.iterrows()) +
        " chance of at least one alert period.")
    rainy = months[months["month"].between(6, 9)]
    st.caption(f"Share of years from 1981 to 2025 (CHIRPS) with at least one 10-day period above each level; darker "
               f"bars are the next 6 months. June to September became wetter: alert chance "
               f"{rainy['chance_alert_1981_2003'].mean():.0%} in 1981 to 2003 versus "
               f"{rainy['chance_alert_2004_2025'].mean():.0%} in 2004 to 2025. These are odds from history, not a "
               "forecast for a specific year.")
    with st.expander("How far ahead can this predict?"):
        st.markdown(
            "- **Weeks (best):** the case forecast covers 2 to 6 weeks after rain that has fallen, and about 2 more "
            "weeks with the 16-day rain forecast.\n"
            "- **Months:** chances from 45 years of rainfall, as above. Not a forecast of a particular week.\n"
            "- **Years:** not reliable. Case data covers only 2019 to 2023.\n\n"
            "Better forecasts would need weekly leptospirosis cases for Metro Manila (DOH EDCS, via an FOI "
            "request), 2024 to 2026 national cases, and river and flood gauge data.")

with tab_flood:
    st.subheader("Same rain, different flood: who lives where the water gets deep?")
    st.caption("UP NOAH 100-year flood hazard map overlaid on 1,710 barangays and 2020 census ages. People in a hazard "
               "zone are estimated by the share of the barangay's area in that zone, assuming people are spread "
               "evenly. Medium hazard is 0.5 to 1.5 m of flooding; high is over 1.5 m.")
    tot_p, tot_v = bgy["people_med_high"].sum(), bgy["vulnerable_med_high"].sum()
    a, b, c = st.columns(3)
    a.metric(f"People in medium or high flood zones ({tot_p / bgy['population'].sum():.0%} of NCR)", f"{tot_p:,.0f}")
    b.metric("Of them, under 5 or 65+", f"{tot_v:,.0f}")
    c.metric("Barangays mostly (over 50%) in these zones", f"{(bgy['flood_share_med_high'] > 0.5).sum():,}")
    RANKS = {
        "Number of vulnerable people": ("vulnerable_med_high", "Reds",
                                        "How many doses and check-ins? Favours large barangays."),
        "Share of residents in zones": ("flood_share_med_high", "Blues",
                                        "Where is each resident most likely to be flooded? Fair across barangay sizes."),
        "Vulnerable people per km²": ("vulnerable_per_km2", "Purples",
                                      "Where can one site reach the most people? Favours small, crowded barangays."),
    }
    rank_by = st.radio("Rank and colour by", list(RANKS), horizontal=True)
    col, scale, why = RANKS[rank_by]
    st.caption(f"{why} Barangays range from under 0.01 km² (in Manila) to over 25 km², so no single measure tells the "
               "whole story: use the number to size supplies and the share to set priorities.")
    cities = ["All cities"] + sorted(bgy["city"].unique())
    pick = st.selectbox("City", cities)
    view = bgy if pick == "All cities" else bgy[bgy["city"] == pick]
    left, right = st.columns([3, 2])
    with left:
        fig = px.choropleth(view, geojson=geo, locations="bgy_code", featureidkey="properties.bgy_code",
                            color=col, color_continuous_scale=scale,
                            range_color=(0, bgy[col].quantile(0.98)), hover_name="barangay",
                            hover_data={"city": True, "population": ":,", "flood_share_med_high": ":.0%",
                                        "vulnerable_med_high": ":,.0f", "vulnerable_per_km2": ":,.0f",
                                        "bgy_code": False},
                            labels={"vulnerable_med_high": "Vulnerable in zone", "flood_share_med_high": "Area in zone",
                                    "vulnerable_per_km2": "Vulnerable in zone per km²", "population": "Population",
                                    "city": "City"})
        if pick == "All cities":
            fig.update_geos(visible=False, projection_type="mercator", lonaxis_range=[120.9, 121.14],
                            lataxis_range=[14.34, 14.79])
        else:
            fig.update_geos(visible=False, projection_type="mercator", fitbounds="locations")
        fig.update_traces(marker_line_width=0.2, marker_line_color="white")
        fig.update_layout(height=680, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch")
    with right:
        st.dataframe(view.sort_values([col, "vulnerable_med_high"], ascending=False)[
            ["barangay", "city", "population", "flood_share_med_high", "vulnerable_med_high", "vulnerable_per_km2"]]
            .round({"vulnerable_per_km2": 0}).rename(columns={
                "barangay": "Barangay", "city": "City", "population": "Population",
                "flood_share_med_high": "Area in medium/high zone", "vulnerable_med_high": "Vulnerable in zone",
                "vulnerable_per_km2": "Per km²"}),
            hide_index=True, height=680, width="stretch", column_config={
                "Population": st.column_config.NumberColumn(format="localized"),
                "Area in medium/high zone": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
                "Vulnerable in zone": st.column_config.NumberColumn(format="localized"),
                "Per km²": st.column_config.NumberColumn(format="localized")})
    by_city = (bgy.groupby("city")[["population", "people_med_high", "vulnerable_med_high"]].sum()
               .sort_values("vulnerable_med_high").reset_index())
    st.markdown("**By city: children under 5 and adults 65+ living in medium or high flood zones**")
    cfig = go.Figure(go.Bar(y=by_city["city"], x=by_city["vulnerable_med_high"], orientation="h", marker_color="#c1121f",
                            text=[f"{v:,.0f} ({p / t:.0%} of residents in zone)" for v, p, t in
                                  zip(by_city["vulnerable_med_high"], by_city["people_med_high"], by_city["population"])],
                            textposition="outside"))
    cfig.update_layout(height=480, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="Vulnerable people in zone",
                       xaxis_range=[0, by_city["vulnerable_med_high"].max() * 1.45])
    st.plotly_chart(cfig, width="stretch")

with tab_supply:
    st.subheader("Supply checklist, sized to the people living in flood zones")
    if not flagged:
        st.info(f"No rainfall alert for the period starting {dekad}. Quantities below are for planning ahead.")
    st.caption("Planning quantities only. The rates are assumptions to adjust; check them against current DOH "
               "guidance before use. Regimen for people living in flooded areas: doxycycline 200 mg once a week until "
               "exposure ends (PhilHealth). Doxycycline is generally avoided in pregnancy and young children; plan "
               "alternatives with a doctor.")
    a, b, c, d = st.columns(4)
    zone = a.radio("Cover people in", ["Medium and high zones", "High zone only"])
    cover = b.slider("Share of them expected to wade in floodwater (%)", 1, 100, 20)
    weeks = c.slider("Weeks people stay in flooded areas (one dose a week)", 1, 8, 2)
    caps = d.number_input("Doxycycline 100 mg capsules per dose", 1, 4, 2)
    s = bgy.copy()
    share_col = s["flood_share_med_high"] if zone.startswith("Medium") else s["share_var3"]
    s["in_zone"] = s["population"] * share_col
    s["to_cover"] = (s["in_zone"] * cover / 100).round(0)
    s["doxy_caps"] = (s["to_cover"] * weeks * caps).round(0)
    s["under5_zone"] = (s["under5"] * share_col).round(0)
    s["over65_zone"] = (s["over65"] * share_col).round(0)
    level = st.radio("Show by", ["City", "Barangay"], horizontal=True)
    cols = ["to_cover", "doxy_caps", "under5_zone", "over65_zone"]
    names = {"to_cover": "People to cover", "doxy_caps": "Doxycycline 100 mg capsules",
             "under5_zone": "Children under 5 in zone", "over65_zone": "Adults 65+ in zone",
             "barangay": "Barangay", "city": "City"}
    if level == "City":
        out = s.groupby("city")[cols].sum().sort_values("to_cover", ascending=False).reset_index()
    else:
        out = s.sort_values("to_cover", ascending=False)[["barangay", "city"] + cols]
        out = out[out["to_cover"] > 0]
    out = out.rename(columns=names)
    st.dataframe(out, hide_index=True, height=460, width="stretch",
                 column_config={names[k]: st.column_config.NumberColumn(format="localized") for k in cols})
    t = s[cols].sum()
    st.markdown(
        f"**Totals for Metro Manila:** {t['to_cover']:,.0f} people to cover, {t['doxy_caps']:,.0f} doxycycline "
        f"capsules.\n\n**Also check, for the top barangays:**\n"
        "- [ ] Doxycycline at barangay health stations and evacuation centres before the flood, for doses within "
        "72 hours of wading\n"
        f"- [ ] Paediatric alternatives for the {t['under5_zone']:,.0f} children under 5 in flood zones\n"
        f"- [ ] Home visits or check-ins for the {t['over65_zone']:,.0f} adults 65+ in flood zones\n"
        "- [ ] Leptospirosis rapid tests at city hospitals; antibiotics and IV fluids for severe cases\n"
        "- [ ] Barangay advisories on avoiding floodwater and seeking care early for fever")
    st.download_button("Download checklist (CSV)", out.to_csv(index=False).encode(),
                       file_name=f"metro_manila_checklist_{level.lower()}_{dekad}.csv", mime="text/csv")

with tab_evidence:
    st.subheader(f"Leptospirosis cases rise {RISE_FROM} to {RISE_TO} weeks after widespread heavy rain")
    st.caption("National weekly DOH surveillance, 2019 to 2023. Case counts by city or barangay are not openly "
               "available, so the timing is national.")
    a, b = st.columns(2)
    with a:
        st.markdown(f"**Lag model: risk is highest {PEAK} weeks after heavy rain** (95% CI)")
        lagfig = go.Figure(go.Scatter(
            x=main["lag_weeks"], y=main["rr"], mode="markers", marker=dict(size=9, color="#2a6f97"),
            error_y=dict(type="data", symmetric=False, array=main["rr_high"] - main["rr"],
                         arrayminus=main["rr"] - main["rr_low"])))
        lagfig.add_hline(y=1, line_color="grey")
        lagfig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="Weeks after heavy rain",
                             yaxis_title="Relative risk")
        st.plotly_chart(lagfig, width="stretch")
    with b:
        n_ev = events["event_week"].nunique()
        st.markdown(f"**After the {n_ev} heaviest rain weeks, cases roughly double by week 3**")
        med = events.groupby("weeks_from_event")["ratio_to_before"].median().reset_index()
        efig = go.Figure()
        for ev, g in events.groupby("event_week"):
            efig.add_scatter(x=g["weeks_from_event"], y=g["ratio_to_before"], mode="lines",
                             line=dict(color="#cccccc", width=1), name=f"{ev:%d %b %Y}", showlegend=False)
        efig.add_scatter(x=med["weeks_from_event"], y=med["ratio_to_before"], mode="lines+markers",
                         line=dict(color="#c1121f", width=3), name="Median of events")
        efig.add_vline(x=0, line_dash="dash", line_color="#2a6f97")
        efig.add_hline(y=1, line_color="grey")
        efig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="Weeks from the event",
                           yaxis_title="Cases vs the 4 weeks before", yaxis_range=[0, 4], showlegend=False)
        st.plotly_chart(efig, width="stretch")
