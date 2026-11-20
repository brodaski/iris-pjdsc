"""IRIS (Infection Risk from Inundation and Storms), Metro Manila version: when heavy rain hits NCR, which barangays to prepare first.

Run with:  streamlit run app/metro_manila.py
Reads the processed rain and case files (notebooks 01, 02 and 05), data/processed/ncr_barangays.geojson
(notebook 03) and the outlook files from notebook 04. The calculations are in iris_core.py.
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from iris_core import (REGIMENS, alert_dates, city_brief_html, dekad_end, exposed, flood_level, supply,
                       wettest_window)
from rain_data import DATA, case_range, forecast, live_rain, rain_forecast, weekly_share

NCR = "PH13074"
EXAMPLES = {"Habagat floods, August 2018": "2018-08-11", "Typhoon Carina (Gaemi), July 2024": "2024-07-21"}

NO_BAR = {"displayModeBar": False}
LOGO_DIR = Path(__file__).resolve().parent.parent / "assets"
st.set_page_config(page_title="IRIS: Metro Manila", page_icon=str(LOGO_DIR / "iris_mark.png"), layout="wide")

# Key labels in Filipino. English is the default; the sidebar switch changes these labels only.
FIL = {
    "Rainfall alert": "Babala sa ulan", "Outlook": "Darating na linggo", "Flood exposure by barangay":
    "Baha ayon sa barangay", "Supply checklist": "Listahan ng gamot at suplay", "Evidence": "Ebidensya",
    "ALERT": "BABALA", "No alert": "Walang babala",
    "Hospitals ready for cases by": "Handa ang mga ospital bago mag", "Expected case peak": "Inaasahang rurok ng kaso",
    "Stay alert until": "Manatiling alerto hanggang",
    "Forecast warning": "Babala mula sa forecast", "Next 16 days": "Susunod na 16 na araw",
    "Pre-position doxycycline now": "Ihanda na ang doxycycline sa mga barangay ngayon",
}


def t(text):
    return FIL.get(text, text) if st.session_state.get("lang") == "Filipino" else text


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
    controls = pd.read_csv(DATA / "disease_lag.csv")
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
    return rain, lag, events, controls, geo, bgy, months, floods, base, cases, backtest, scores


rain, lag, events, controls, geo, bgy, months, floods, base, cases, backtest, scores = load()
FLOOD = months["flood_mm"].iloc[0]
rain, rain_source = live_rain(rain)
ncr_rain = rain[rain["PCODE"] == NCR].sort_values("date").reset_index(drop=True)
P90 = ncr_rain["p90_mm"].iloc[0]

main = lag[lag["model"].str.startswith("Main")]
peak = main.loc[main["rr"].idxmax()]
sig = main.loc[main["significant"], "lag_weeks"]
PEAK, RISE_FROM, RISE_TO = int(peak["lag_weeks"]), int(sig.min()), int(sig.max())

today = pd.Timestamp.now(tz="Asia/Manila").tz_localize(None).normalize()
om, om_share, om_source, om_status = rain_forecast()
peak10, peak10_end = wettest_window(om, today)

with st.sidebar:
    st.image(str(LOGO_DIR / "iris_logo.png"), width=260)
    st.caption("Metro Manila: which barangays to prepare for leptospirosis after heavy rain, and when.")
    st.radio("Language / Wika", ["English", "Filipino"], horizontal=True, key="lang",
             help="Filipino changes the main labels and alerts; explanations stay in English.")
    dekads = list(ncr_rain["date"].dt.strftime("%Y-%m-%d"))[::-1]
    example = st.selectbox("Replay a past flood", ["None (latest rainfall)"] + list(EXAMPLES),
                           help="Runs the same alert on a past flood. The lag model was fitted on 2019 to 2023 "
                                "cases, so Carina (2024) is a test it had not seen.")
    start = EXAMPLES.get(example, dekads[0])
    start = start if start in dekads else dekads[0]
    dekad = st.selectbox("10-day rainfall period (start date)", dekads, index=dekads.index(start),
                         help="CHIRPS reports rain in three periods a month: the 1st to 10th, the 11th to 20th, and "
                              "the 21st to the end of the month. The total is the rain that fell over all of Metro "
                              "Manila in that period. Newest first; updated from HDX every 10 days.")
    st.caption(f"Rainfall source: {rain_source}.")
    st.divider()
    st.markdown(f"**Alert window:** cases peak **{PEAK} weeks** after heavy rain and stay raised from week "
                f"{RISE_FROM} to week {RISE_TO} (national DOH surveillance, 2019 to 2023).")
    with st.expander("About the data"):
        st.markdown(
            "- Rainfall: CHIRPS 10-day rainfall for Metro Manila, WFP and Climate Hazards Center via HDX.\n"
            "- Forecast: Open-Meteo 16-day forecast; a dated copy ships with the app in case it is unreachable.\n"
            "- Flood hazard: UP NOAH Center, Metro Manila 100-year flood hazard map.\n"
            "- Population: PSA 2020 Census by single-year age and barangay, via HDX.\n"
            "- Boundaries: NAMRIA and PSA barangay boundaries (COD-AB 2025), via HDX.\n"
            "- Cases: weekly national leptospirosis counts, DOH reports compiled by the University of Mindanao.\n\n"
            "**Limits:** people in a flood zone are estimated by area share; rain is averaged over all of Metro "
            "Manila; the alert window is national; no barangay case data is open."
        )

row = ncr_rain[ncr_rain["date"] == pd.Timestamp(dekad)].iloc[0]
flagged = bool(row["above_p90"])
end = dekad_end(dekad)
dates = alert_dates(dekad, RISE_FROM, PEAK, RISE_TO)

tab_alert, tab_outlook, tab_flood, tab_supply, tab_evidence = st.tabs(
    [t("Rainfall alert"), t("Outlook"), t("Flood exposure by barangay"), t("Supply checklist"), t("Evidence")])

with tab_alert:
    # 1. Forward-looking: the 16-day forecast, so doxycycline can be in place before the rain.
    fc_note = f"{om_source}." + (" The bundled copy may be out of date." if om_status == "snapshot" else "")
    if peak10 is not None and peak10 >= P90:
        msg = (f"**{t('Forecast warning')}:** about **{peak10:.0f} mm** of rain is forecast for the 10 days ending "
               f"{peak10_end:%d %b}, above the alert level of {P90:.0f} mm"
               + (f" and the flood level of {FLOOD:.0f} mm" if peak10 >= FLOOD else "")
               + f". **{t('Pre-position doxycycline now')}** in the barangays at the top of the Outlook tab.")
        (st.error if peak10 >= FLOOD else st.warning)(msg)
    elif peak10 is not None:
        st.info(f"**{t('Next 16 days')}:** no alert-level rain forecast for Metro Manila (wettest 10 days: about "
                f"{peak10:.0f} mm, alert level {P90:.0f} mm).")
    st.caption(fc_note + " Weather forecasts several days ahead often miss the heaviest rain, so recheck daily.")

    # 2. The measured rain of the selected period, which times the case surge.
    st.markdown(f"#### Measured rain, {pd.Timestamp(dekad):%d %b} to {end - pd.Timedelta(days=1):%d %b %Y}")
    if flagged:
        st.error(f"**{t('ALERT')}:** Metro Manila got {row['rfh']:.0f} mm in the 10 days from {dekad}, above its 90th "
                 f"percentile of {P90:.0f} mm (only 1 in 10 periods is wetter).")
    else:
        st.success(f"**{t('No alert')}:** Metro Manila got {row['rfh']:.0f} mm in the 10 days from {dekad}, below its "
                   f"90th percentile of {P90:.0f} mm.")
    if row["version"] == "prelim":
        st.caption("Preliminary rainfall: WFP may revise this period when the final CHIRPS data is released.")
    a, b, c = st.columns(3)
    if flagged:
        p0, p1 = dates["peak_from"], dates["peak_to"]
        a.metric(t("Hospitals ready for cases by"), f"{dates['ready_by']:%d %b %Y}")
        b.metric(t("Expected case peak"), f"{p0:%d}–{p1:%d %b %Y}" if p0.month == p1.month else f"{p0:%d %b}–{p1:%d %b}")
        c.metric(t("Stay alert until"), f"{dates['alert_until']:%d %b %Y}")
        st.caption("Doxycycline prophylaxis works only if taken within 24 to 72 hours of wading, or once a week while "
                   "people live in flooded areas, so it must already be in the barangays when the rain comes (see the "
                   "forecast warning above). These dates are for the case surge that follows.")
    else:
        a.metric("Rain this period", f"{row['rfh']:.0f} mm")
        b.metric("Alert threshold (90th percentile)", f"{P90:.0f} mm")
        c.metric("Share of threshold", f"{row['rfh'] / P90:.0%}")
    if example in EXAMPLES:
        if example.startswith("Typhoon Carina"):
            st.info("**What happened:** DOH hospitals reported 523 new cases from 8 to 13 August 2024, 15 to 20 days "
                    "after the 24 July flood (Montemayor, 2024), and the National Kidney and Transplant Institute "
                    "turned its gym into a leptospirosis ward on 9 August (Bosano, 2024).")
        else:
            st.info("**What happened:** 259 mm fell in the period that included the 11 August 2018 monsoon floods. "
                    "Weekly case counts for 2018 are not in the open data, so this replay shows the dates IRIS "
                    "would have given.")

    with st.expander("What do these numbers mean?"):
        st.markdown(
            f"- **10-day rainfall:** CHIRPS combines satellite and rain gauge data into totals for the 1st to 10th, "
            f"11th to 20th and 21st to end of each month, averaged over Metro Manila.\n"
            f"- **Alert level ({P90:.0f} mm):** the 90th percentile of all 10-day periods from 1981 to 2025, so "
            f"about 1 in 10 periods is wetter.\n"
            f"- **Flood level ({FLOOD:.0f} mm):** every major Metro Manila flood since 2009 had at least this much.\n"
            f"- **Dates:** national cases rise from week {RISE_FROM} to week {RISE_TO} after widespread heavy rain and "
            f"peak at week {PEAK} (Evidence tab).")

    st.markdown("**Metro Manila 10-day rainfall, last 3 years** (red = above the alert threshold)")
    recent = ncr_rain[ncr_rain["date"] >= ncr_rain["date"].max() - pd.DateOffset(years=3)]
    rfig = go.Figure(go.Bar(x=recent["date"], y=recent["rfh"],
                            marker_color=["#c1121f" if f else "#9ecae1" for f in recent["above_p90"]],
                            hovertemplate="%{x|%d %b %Y}: %{y:.0f} mm<extra></extra>"))
    rfig.add_hline(y=P90, line_dash="dash", line_color="#333333", annotation_text=f"Alert threshold {P90:.0f} mm",
                   annotation_position="top left")
    if pd.Timestamp(dekad) >= recent["date"].min():
        rfig.add_vline(x=pd.Timestamp(dekad), line_color="#2a6f97", line_width=2)
    rfig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="mm per 10 days")
    st.plotly_chart(rfig, width="stretch", config=NO_BAR)

    share = weekly_share(rain)
    as_of = share.index[share.index <= end].max()
    fc = forecast(share, as_of)
    top = fc.loc[fc["rise_pct"].idxmax()]
    st.markdown(f"**National case outlook:** up to **{top['rise_pct']:.0f}% above** a week without extreme rain, "
                f"highest in the week of {top['week_start']:%d %b %Y}, counting how widespread heavy rain was across "
                f"all provinces in the 6 weeks up to {as_of + pd.Timedelta(days=6):%d %b}.")
    fcfig = go.Figure(go.Bar(x=[f"+{h} wk<br>{d:%d %b}" for h, d in zip(fc["weeks_ahead"], fc["week_start"])],
                             y=fc["rise_pct"], marker_color="#c1121f",
                             text=[f"+{v:.0f}%" for v in fc["rise_pct"]], textposition="outside"))
    fcfig.update_layout(height=220, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="Expected rise (%)",
                        yaxis_range=[0, max(10, fc["rise_pct"].max() * 1.3)])
    st.plotly_chart(fcfig, width="stretch", config=NO_BAR)
    st.caption("Indicative and national: case data by city or barangay is not openly available. See the track "
               "record in the Outlook tab.")

with tab_outlook:
    st.subheader("What the next weeks and months may bring")
    this_week = today - pd.Timedelta(days=today.weekday())

    # 1. Rain forecast for Metro Manila
    st.markdown("#### 1. Rain in the next 16 days")
    st.caption(f"Source: {om_source}, one point in central Metro Manila. Weather models and CHIRPS measure rain "
               "differently, so treat the totals as a guide.")
    dfig = go.Figure(go.Bar(x=om["day"], y=om["mm"], marker_color=["#2a6f97" if f else "#9ecae1" for f in om["is_forecast"]],
                            hovertemplate="%{x|%d %b}: %{y:.0f} mm<extra></extra>"))
    dfig.add_vline(x=today, line_dash="dash", line_color="#333333")
    dfig.update_layout(height=220, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="mm per day")
    st.plotly_chart(dfig, width="stretch", config=NO_BAR)
    if peak10 is not None:
        st.markdown(f"Wettest 10 days in the forecast: **{peak10:.0f} mm**, ending {peak10_end:%d %b} "
                    f"(dark bars are forecast, light bars the past 3 weeks).")
    else:
        st.info("The saved forecast has run out. Use the slider below to plan for a rainfall scenario.")

    # 2. Flood outlook by barangay
    st.markdown("#### 2. Flood outlook by barangay")
    default = int(round(peak10 if peak10 is not None else row["rfh"]))
    plan_mm = st.slider("10-day rainfall to plan for (mm)", 0, 700, min(default, 700), step=10,
                        help=f"Starts at the forecast (or the selected period). Alert level {P90:.0f} mm; "
                             f"flood level {FLOOD:.0f} mm.")
    ev_txt = ", ".join(f"{e} ({mm:.0f} mm)" for e, mm in zip(floods["event"], floods["rfh"]))
    level, share_col = flood_level(plan_mm, P90, FLOOD)
    if level == "widespread":
        cmap = "Reds"
        st.error(f"**Widespread flooding likely.** {plan_mm} mm in 10 days is at or above {FLOOD:.0f} mm, the level "
                 f"reached in all {len(floods)} major Metro Manila floods since 2009. Expect medium and high hazard "
                 "zones to flood.")
        st.caption(f"Past floods (10-day rain): {ev_txt}.")
    elif level:
        cmap = "Oranges"
        st.warning(f"**Flooding likely in high hazard zones.** {plan_mm} mm is above the leptospirosis alert level "
                   f"({P90:.0f} mm) but below the flood level ({FLOOD:.0f} mm). Expect flooding first in high hazard "
                   "zones (over 1.5 m in the 100-year map).")
    else:
        st.success(f"**No widespread flooding expected.** {plan_mm} mm is below the alert level ({P90:.0f} mm). "
                   "Low spots and blocked drains can still flood.")
    if level:
        f = exposed(bgy, share_col)
        # Colour by density, not count: a count map paints large barangays dark and leaves Manila's many small,
        # crowded barangays pale. Density spans 4 orders of magnitude, so the colour uses a log scale.
        f = f.assign(vuln_km2=f["vuln_risk"] / f["area_km2"])
        f = f.assign(log_km2=np.log10(f["vuln_km2"].clip(lower=1)))
        a, b, c = st.columns(3)
        a.metric("Barangays with any area in these zones", f"{len(f):,}")
        b.metric("People in the zones expected to flood", f"{f['people_risk'].sum():,.0f}")
        c.metric("Of them, under 5 or 65+", f"{f['vuln_risk'].sum():,.0f}")
        by_density = st.radio("Colour the map by", ["Vulnerable people per km²", "Number of vulnerable people"],
                              horizontal=True, key="outlook_colour",
                              help="Per km² (default) keeps Manila's many small, crowded barangays from looking "
                                   "safe next to large ones. The number sets how much to stock.") == "Vulnerable people per km²"
        st.caption("Per km²: children under 5 and adults 65+ in the flooding zones per km² of barangay, on a log scale. "
                   "The table gives both, so counts can still size supplies.")
        left, right = st.columns([1, 1])
        with left:
            hover = {"city": True, "people_risk": ":,.0f", "vuln_risk": ":,.0f", "vuln_km2": ":,.0f",
                     "log_km2": False, "bgy_code": False}
            labels = {"vuln_km2": "Under 5 or 65+ at risk per km²", "vuln_risk": "Under 5 or 65+ at risk",
                      "people_risk": "People at risk", "city": "City"}
            if by_density:
                ticks = [v for v in (1, 10, 100, 1000, 10000, 100000) if v <= f["vuln_km2"].max() * 1.5]
                ofig = px.choropleth(f, geojson=geo, locations="bgy_code", featureidkey="properties.bgy_code",
                                     color="log_km2", color_continuous_scale=cmap,
                                     range_color=(0, f["log_km2"].quantile(0.99)), hover_name="barangay",
                                     hover_data=hover, labels=labels)
                ofig.update_coloraxes(colorbar=dict(title="Under 5 or 65+<br>at risk per km²",
                                                    tickvals=[np.log10(v) for v in ticks],
                                                    ticktext=[f"{v:,}" for v in ticks]))
            else:
                ofig = px.choropleth(f, geojson=geo, locations="bgy_code", featureidkey="properties.bgy_code",
                                     color="vuln_risk", color_continuous_scale=cmap,
                                     range_color=(0, f["vuln_risk"].quantile(0.98)), hover_name="barangay",
                                     hover_data=hover, labels=labels)
            ofig.update_geos(visible=False, projection_type="mercator", lonaxis_range=[120.9, 121.14],
                             lataxis_range=[14.34, 14.79])
            ofig.update_traces(marker_line_width=0)   # borders would whiten Manila's tiny barangays
            ofig.update_layout(height=560, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(ofig, width="stretch")
        with right:
            st.dataframe(f.sort_values("vuln_km2" if by_density else "vuln_risk", ascending=False)[["barangay", "city", "vuln_km2", "people_risk", "vuln_risk"]]
                         .round(0).rename(columns={"barangay": "Barangay", "city": "City", "vuln_km2": "Per km²",
                                                   "people_risk": "People", "vuln_risk": "Under 5 or 65+"}),
                         hide_index=True, height=560, width="stretch", column_config={
                             k: st.column_config.NumberColumn(format="localized")
                             for k in ["Per km²", "People", "Under 5 or 65+"]})
    st.caption("A rain trigger on the UP NOAH 100-year hazard map, not a flood model: it does not include river levels, "
               "tides or drainage, and shows where flooding is most likely, not its exact extent.")

    # 3. Leptospirosis case outlook
    st.markdown("#### 3. Leptospirosis cases in the next weeks (national)")
    share = weekly_share(rain)
    as_of = share.index.max()
    horizon = (this_week - as_of).days // 7 + 6
    fc = forecast(share, as_of, horizon=horizon, future=om_share)
    fc = fc[fc["week_start"] >= this_week].copy()
    fc["iso_week"] = fc["week_start"].dt.isocalendar().week.clip(upper=52).astype(int)
    fc = fc.merge(base, on="iso_week", how="left")
    fc["expected"] = fc["baseline_cases"] * (1 + fc["rise_pct"] / 100)
    fc["low"], fc["high"] = case_range(fc["expected"])
    fc["uses_forecast"] = fc["week_start"] - pd.Timedelta(weeks=2) >= this_week
    fc["label"] = "Week of<br>" + fc["week_start"].dt.strftime("%d %b")
    cfig2 = go.Figure()
    cfig2.add_bar(x=fc["label"], y=fc["expected"],
                  marker_color=["#e07a5f" if u else "#c1121f" for u in fc["uses_forecast"]],
                  error_y=dict(type="data", symmetric=False, array=fc["high"] - fc["expected"],
                               arrayminus=fc["expected"] - fc["low"], color="#555555"),
                  text=[f"{e:.0f} ({r:+.0f}%)" for e, r in zip(fc["expected"], fc["rise_pct"])],
                  textposition="inside", insidetextanchor="end", textfont=dict(color="white"),
                  name="Expected cases (80% range)")
    cfig2.add_scatter(x=fc["label"], y=fc["baseline_cases"], mode="lines+markers", line=dict(color="#333333",
                      dash="dash"), name="Without extreme rain")
    past = fc[["label", "iso_week"]].merge(cases[["iso_year", "iso_week", "cases"]], on="iso_week")
    ymax = fc["high"].max()
    if len(past):
        med = past.groupby("label", sort=False)["cases"].median().reindex(fc["label"])
        cfig2.add_scatter(x=med.index, y=med, mode="markers", name="Actual, median of 2019 to 2023",
                          marker=dict(color="#4d4d4d", size=9, symbol="diamond"))
        ymax = max(ymax, med.max())
    cfig2.update_layout(height=320, margin=dict(l=0, r=0, t=40, b=0), yaxis_title="Cases a week (Philippines)",
                        yaxis_range=[0, ymax * 1.1], legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0))
    st.plotly_chart(cfig2, width="stretch", config=NO_BAR)
    st.caption("Bars: expected national cases from how widespread heavy rain was 2 to 6 weeks before (notebook 05). "
               "Whiskers: the range that 8 in 10 weeks with that expected value fall in, from week-to-week noise in "
               "counts. Dashed line: a week with no extreme rain, at 2023 levels. Diamonds: the median of actual cases "
               "in the same weeks of 2019 to 2023. Lighter bars depend on forecast rain. National only, since no city "
               "or barangay case data is open.")

    st.markdown("**Track record: three models, each tested on a year it had not seen**")
    sc = scores.copy()
    pooled = (sc.assign(err=sc["mae"] * sc["weeks"]).groupby("model", sort=False)
              .apply(lambda g: g["err"].sum() / g["weeks"].sum(), include_groups=False))
    table = sc.pivot(index="model", columns="test_year", values="mae").reindex(pooled.index)
    table.columns = [f"{c} error" for c in table.columns]
    table["All three years"] = pooled
    st.dataframe(table.round(0).rename_axis("Model (average error, cases a week)"), width="stretch", column_config={
        c: st.column_config.NumberColumn(format="%.0f") for c in table.columns})
    year = st.radio("Show test year", sorted(backtest["test_year"].unique()), index=2, horizontal=True)
    bt = backtest[backtest["test_year"] == year]
    tfig = go.Figure()
    tfig.add_scatter(x=bt["week_start"], y=bt["cases"], mode="lines+markers", name="Actual cases",
                     line=dict(color="#252525", width=2), marker=dict(size=5))
    for col, color, dash in [("Seasonal + rain", "#c1121f", None), ("Gradient boosting", "#7b2cbf", "dash"),
                             ("Baseline: seasonal", "#9ecae1", "dot")]:
        tfig.add_scatter(x=bt["week_start"], y=bt[col], mode="lines", name=col, line=dict(color=color, width=2, dash=dash))
    tfig.update_layout(height=300, margin=dict(l=0, r=0, t=40, b=0), yaxis_title="Cases a week (Philippines)",
                       legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0))
    st.plotly_chart(tfig, width="stretch", config=NO_BAR)
    st.caption("Each model was trained only on years before the test year. Every forecast is scaled to the cases "
               "reported up to 2 weeks before the target week, never to the test year itself. Both models that use "
               "rain had a lower error than the seasonal baseline over the three years, but the gain is small and "
               "not steady (seasonal + rain did worse in 2022), so treat the case outlook as indicative. The app uses "
               "seasonal + rain because its effect of rain can be read and explained. Cases for 2024 to 2026 are only "
               "in DOH PDF reports, so they are not in the data yet.")

    # 4. Months ahead
    st.markdown("#### 4. The months ahead: chance of an alert in Metro Manila")
    mnames = pd.to_datetime(months["month"], format="%m").dt.strftime("%b")
    nxt = [(today.month - 1 + i) % 12 + 1 for i in range(1, 7)]
    mfig = go.Figure()
    mfig.add_bar(x=mnames, y=months["chance_alert"] * 100, name=f"Alert (over {P90:.0f} mm in 10 days)",
                 marker_color=["#c1121f" if m in nxt else "#e8a0a5" for m in months["month"]])
    mfig.add_bar(x=mnames, y=months["chance_flood"] * 100, name=f"Flood level (over {FLOOD:.0f} mm)",
                 marker_color=["#2a6f97" if m in nxt else "#9ecae1" for m in months["month"]])
    mfig.update_layout(height=300, margin=dict(l=0, r=0, t=40, b=0), yaxis_title="Chance in a year (%)",
                       barmode="group", legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0))
    st.plotly_chart(mfig, width="stretch", config=NO_BAR)
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
            "- **Weeks (best):** the case outlook covers 2 to 6 weeks after rain that has fallen, and about 2 more "
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
    a.metric("People in medium or high flood zones", f"{tot_p:,.0f}",
             delta=f"{tot_p / bgy['population'].sum():.0%} of Metro Manila", delta_color="off", delta_arrow="off")
    b.metric("Of them, under 5 or 65+", f"{tot_v:,.0f}")
    c.metric("Barangays mostly (over 50%) in these zones", f"{(bgy['flood_share_med_high'] > 0.5).sum():,}")
    RANKS = {
        "Share of residents in zones": ("flood_share_med_high", "Blues",
                                        "Where is each resident most likely to be flooded? Fair across barangay sizes."),
        "Number of vulnerable people": ("vulnerable_med_high", "Reds",
                                        "How many doses and check-ins? Favours large barangays."),
        "Vulnerable people per km²": ("vulnerable_per_km2", "Purples",
                                      "Where can one site reach the most people? Favours small, crowded barangays."),
    }
    rank_by = st.radio("Rank and colour by", list(RANKS), horizontal=True)
    col, scale, why = RANKS[rank_by]
    st.caption(f"{why} Barangays range from under 0.01 km² (in Manila) to over 25 km², so no single measure tells the "
               "whole story: use the share to set priorities and the number to size supplies.")
    cities = ["All cities"] + sorted(bgy["city"].unique())
    pick = st.selectbox("City", cities)
    view = bgy if pick == "All cities" else bgy[bgy["city"] == pick]
    left, right = st.columns([1, 1])
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
        st.dataframe(view.assign(city=view["city"].str.replace("City of ", "", regex=False))
            .sort_values([col, "vulnerable_med_high"], ascending=False)[
            ["barangay", "city", "flood_share_med_high", "vulnerable_med_high", "vulnerable_per_km2"]]
            .round({"vulnerable_per_km2": 0}).rename(columns={
                "barangay": "Barangay", "city": "City",
                "flood_share_med_high": "Area in zone", "vulnerable_med_high": "Vulnerable",
                "vulnerable_per_km2": "Per km²"}),
            hide_index=True, height=680, width="stretch", column_config={
                "Area in zone": st.column_config.NumberColumn(format="percent"),
                "Vulnerable": st.column_config.NumberColumn(format="localized"),
                "Per km²": st.column_config.NumberColumn(format="localized")})

    with st.expander("How the overlay works, for one barangay"):
        top_view = view.sort_values("vulnerable_med_high", ascending=False)
        names = (top_view["barangay"] + ", " + top_view["city"].str.replace("City of ", "", regex=False)).tolist()
        who = st.selectbox("Barangay", names, help="Sorted by vulnerable people in flood zones.")
        r = top_view.iloc[names.index(who)]
        st.markdown(
            f"1. **Barangay shape:** {who} covers **{r['area_km2']:.2f} km²** (2025 boundaries).\n"
            f"2. **Flood zones:** the NOAH map's polygons are cut to the barangay's shape (in metres, EPSG:32651). "
            f"**{r['share_var2']:.0%}** of its area is medium hazard (0.5 to 1.5 m) and **{r['share_var3']:.0%}** is "
            f"high hazard (over 1.5 m), so **{r['flood_share_med_high']:.0%}** is medium or high.\n"
            f"3. **People:** the 2020 census counts **{r['population']:,.0f}** residents, of whom "
            f"**{r['under5']:,.0f}** are under 5 and **{r['over65']:,.0f}** are 65 or older.\n"
            f"4. **Result:** ({r['under5']:,.0f} + {r['over65']:,.0f}) × {r['flood_share_med_high']:.1%} ≈ "
            f"**{r['vulnerable_med_high']:,.0f} vulnerable people in flood zones**, assuming people are spread evenly.")

    by_city = (bgy.groupby("city")[["population", "people_med_high", "vulnerable_med_high"]].sum()
               .sort_values("vulnerable_med_high").reset_index())
    st.markdown("**By city: children under 5 and adults 65+ living in medium or high flood zones**")
    cfig = go.Figure(go.Bar(y=by_city["city"], x=by_city["vulnerable_med_high"], orientation="h", marker_color="#c1121f",
                            text=[f"{v:,.0f} ({p / t_:.0%} of residents in zone)" for v, p, t_ in
                                  zip(by_city["vulnerable_med_high"], by_city["people_med_high"], by_city["population"])],
                            textposition="outside"))
    cfig.update_layout(height=480, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="Vulnerable people in zone",
                       xaxis_range=[0, by_city["vulnerable_med_high"].max() * 1.45])
    st.plotly_chart(cfig, width="stretch", config=NO_BAR)

with tab_supply:
    st.subheader("Supply checklist, sized to the people living in flood zones")
    if not flagged:
        st.info(f"No rainfall alert for the period starting {dekad}. Quantities below are for planning ahead.")
    st.caption("Planning quantities only; check them against current DOH guidance before use. Regimens follow the "
               "PhilHealth policy statements based on the Leptospirosis CPG 2010. Doxycycline is generally avoided "
               "in pregnancy, while breastfeeding and in children under 8; plan alternatives with a doctor.")
    a, b, c = st.columns([1.4, 1, 1])
    regimen = a.radio("Exposure risk of the people to cover", list(REGIMENS))
    a.caption(f"Doxycycline {REGIMENS[regimen]['dose']}.")
    zone = b.radio("Cover people in", ["Medium and high zones", "High zone only"])
    cover = b.slider("Share of them expected to wade in floodwater (%)", 1, 100, 20)
    weeks = c.slider("Weeks people stay in flooded areas", 1, 8, 2, disabled=not REGIMENS[regimen]["weekly"],
                     help="Used for the high-risk regimen, which is one dose a week until exposure ends.")
    s = supply(bgy, bgy["flood_share_med_high"] if zone.startswith("Medium") else bgy["share_var3"], cover, regimen, weeks)
    level_ = st.radio("Show by", ["City", "Barangay"], horizontal=True)
    cols = ["to_cover", "doxy_caps", "under5_zone", "over65_zone"]
    names_ = {"to_cover": "People to cover", "doxy_caps": "Doxycycline 100 mg capsules",
              "under5_zone": "Children under 5 in zone", "over65_zone": "Adults 65+ in zone",
              "barangay": "Barangay", "city": "City"}
    if level_ == "City":
        out = s.groupby("city")[cols].sum().sort_values("to_cover", ascending=False).reset_index()
    else:
        out = s.sort_values("to_cover", ascending=False)[["barangay", "city"] + cols]
        out = out[out["to_cover"] > 0]
    out = out.rename(columns=names_)
    st.dataframe(out, hide_index=True, height=460, width="stretch",
                 column_config={names_[k]: st.column_config.NumberColumn(format="localized") for k in cols})
    tot = s[cols].sum()
    st.markdown(
        f"**Totals for Metro Manila:** {tot['to_cover']:,.0f} people to cover, {tot['doxy_caps']:,.0f} doxycycline "
        f"capsules.\n\n**Also check, for the top barangays:**\n"
        "- [ ] Doxycycline at barangay health stations and evacuation centres before the flood, for doses within "
        "72 hours of wading\n"
        f"- [ ] Alternatives for the {tot['under5_zone']:,.0f} children under 5 in flood zones\n"
        f"- [ ] Home visits or check-ins for the {tot['over65_zone']:,.0f} adults 65+ in flood zones\n"
        "- [ ] Leptospirosis rapid tests at city hospitals; antibiotics and IV fluids for severe cases\n"
        "- [ ] Barangay advisories on avoiding floodwater and seeking care early for fever")
    d1, d2 = st.columns(2)
    d1.download_button("Download checklist (CSV)", out.to_csv(index=False).encode(),
                       file_name=f"metro_manila_checklist_{level_.lower()}_{dekad}.csv", mime="text/csv")

    st.markdown("#### Printable brief for one city")
    brief_city = st.selectbox("City for the brief", sorted(bgy["city"].unique()))
    cs = s[s["city"] == brief_city]
    top10 = cs.sort_values(["flood_share_med_high", "vulnerable_med_high"], ascending=False).head(10)
    status_line = (f"ALERT: {row['rfh']:.0f} mm of rain in Metro Manila in the 10 days from {dekad} (alert level "
                   f"{P90:.0f} mm)." if flagged else
                   f"No alert for the 10 days from {dekad} ({row['rfh']:.0f} mm; alert level {P90:.0f} mm).")
    if peak10 is not None:
        status_line += f" Forecast: about {peak10:.0f} mm in the 10 days ending {peak10_end:%d %b %Y}."
    brief_dates = ({"Hospitals ready for cases by": f"{dates['ready_by']:%d %b %Y}",
                    "Expected case peak": f"{dates['peak_from']:%d %b} to {dates['peak_to']:%d %b %Y}",
                    "Stay alert until": f"{dates['alert_until']:%d %b %Y}"} if flagged else
                   {"Doxycycline": "in barangay health stations before any forecast alert-level rain"})
    page = city_brief_html(brief_city, status_line, brief_dates, top10, cs[cols].sum(), regimen,
                           f"IRIS, generated {today:%d %b %Y}. Rain: {rain_source}. Forecast: {om_source}.")
    st.download_button(f"Download brief for {brief_city} (open, then print or save as PDF)", page.encode(),
                       file_name=f"iris_brief_{brief_city.replace(' ', '_').lower()}_{dekad}.html", mime="text/html")

with tab_evidence:
    st.subheader(f"Leptospirosis cases rise {RISE_FROM} to {RISE_TO} weeks after widespread heavy rain")
    st.caption("National weekly DOH surveillance, 2019 to 2023 (227 weeks). Case counts by city or barangay are not "
               "openly available, so the timing is national.")
    with st.expander("How the lag model works, in plain words", expanded=True):
        st.markdown(
            "1. **Rain signal:** for every week, the share of the 81 provinces whose rain was above that province's "
            "own 90th percentile (an *extreme week*). It measures how widespread heavy rain was.\n"
            "2. **One model per delay:** for each delay of 0 to 8 weeks, a negative binomial regression compares "
            "weekly cases with the rain signal that many weeks earlier. It also includes the usual seasonal rise "
            "and fall, and a separate level for each year (which absorbs the COVID drop in reporting).\n"
            "3. **Result:** the delay where rain matters most is 3 weeks. Every 10 more percentage points of "
            f"provinces with an extreme week means **{(peak['rr'] - 1) * 100:.0f}% more cases** 3 weeks later "
            f"(95% CI {(peak['rr_low'] - 1) * 100:.0f}% to {(peak['rr_high'] - 1) * 100:.0f}%).\n"
            f"4. **What that means for a big storm:** a 10-point step is small. When about 70% of provinces have "
            f"an extreme week, as in the largest storms of 2019 to 2023, the model implies about "
            f"**{peak['rr'] ** 7:.1f} times** the usual cases 3 weeks later. The raw counts on the right show about "
            "a doubling, so the model and the raw data point the same way.")
    a, b = st.columns(2)
    with a:
        st.markdown(f"**Extra cases for each week of delay** (per 10 more points of provinces with extreme rain, 95% CI)")
        pct = (main["rr"] - 1) * 100
        lagfig = go.Figure(go.Bar(
            x=main["lag_weeks"], y=pct, marker_color=["#c1121f" if s_ else "#bdbdbd" for s_ in main["significant"]],
            error_y=dict(type="data", symmetric=False, array=(main["rr_high"] - main["rr"]) * 100,
                         arrayminus=(main["rr"] - main["rr_low"]) * 100, color="#555555"),
            hovertemplate="Week %{x}: %{y:+.0f}%<extra></extra>"))
        lagfig.add_hline(y=0, line_color="grey")
        lagfig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="Weeks after heavy rain",
                             yaxis_title="Change in cases (%)")
        st.plotly_chart(lagfig, width="stretch", config=NO_BAR)
        st.caption("Red: the range excludes zero (weeks 3 to 6). Grey: no clear effect.")
    with b:
        n_ev = events["event_week"].nunique()
        st.markdown(f"**Leptospirosis cases after the {n_ev} heaviest rain weeks: about double by week 3**")
        med = events.groupby("weeks_from_event")["ratio_to_before"].median().reset_index()
        efig = go.Figure()
        for ev, g in events.groupby("event_week"):
            efig.add_scatter(x=g["weeks_from_event"], y=g["ratio_to_before"], mode="lines",
                             line=dict(color="#cccccc", width=1), name=f"{ev:%d %b %Y}", showlegend=False)
        efig.add_scatter(x=med["weeks_from_event"], y=med["ratio_to_before"], mode="lines+markers",
                         line=dict(color="#c1121f", width=3), name="Median of events")
        efig.add_vline(x=0, line_dash="dash", line_color="#2a6f97")
        efig.add_hline(y=1, line_color="grey")
        efig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="Weeks from the heavy rain week",
                           yaxis_title="Leptospirosis cases vs the 4 weeks before", yaxis_range=[0, 4], showlegend=False)
        st.plotly_chart(efig, width="stretch", config=NO_BAR)
        st.caption("Raw counts, no model. Grey lines: each event. Red: the median.")

    ctl = controls[controls["lag_weeks"] == PEAK].sort_values("rr")
    others = ctl[ctl["disease"] != "Leptospirosis"]
    st.markdown(f"**Check:** run through the same model, the other {len(others)} diseases in the DOH reports "
                f"({', '.join(others['disease'].str.replace(r' \(.*\)', '', regex=True).str.lower())}) show no rise "
                f"{PEAK} weeks after heavy rain (all between {(others['rr'].min() - 1) * 100:+.0f}% and "
                f"{(others['rr'].max() - 1) * 100:+.0f}%), so the effect is specific to leptospirosis and not a "
                "reporting artefact. The result also holds without 2020 and 2021, and with rain in mm.")

    with st.expander("Sources"):
        st.markdown(
            "- Bosano, R. (2024, August 9). NKTI turns gym into 'leptospirosis ward' as cases rise. *ABS-CBN News*.\n"
            "- Funk, C., et al. (2015). The climate hazards infrared precipitation with stations. *Scientific Data, 2*, "
            "150066. https://doi.org/10.1038/sdata.2015.66\n"
            "- Matsushita, N., et al. (2018). The non-linear and lagged short-term relationship between rainfall and "
            "leptospirosis and the intermediate role of floods in the Philippines. *PLOS Neglected Tropical "
            "Diseases, 12*(4), e0006331. https://doi.org/10.1371/journal.pntd.0006331\n"
            "- Montemayor, M. T. (2024, August 15). DOH reports 43 leptospirosis deaths for past 3 weeks. "
            "*Philippine News Agency*.\n"
            "- Philippine Health Insurance Corporation. (n.d.). *PhilHealth policy recommendations on diagnosis, "
            "management and prevention of leptospirosis*.\n"
            "- University of Mindanao. (2023). *Philippine epidemiological data* (Version 1) [Data set]. Mendeley Data.\n"
            "- UP NOAH Center. (n.d.). *Metro Manila 100-year flood hazard map* [Data set].\n"
            "- World Food Programme & Climate Hazards Center. (2026). *Philippines: Rainfall indicators at "
            "subnational level* [Data set]. Humanitarian Data Exchange.\n\n"
            "The full list, with links, is in the README.")
