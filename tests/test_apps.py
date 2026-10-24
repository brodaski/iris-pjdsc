"""Smoke tests: both dashboards run without errors offline, and the processed data is consistent.

Run with:  pytest
The live data sources are pointed at an unreachable address, so the tests check the offline fallbacks.
"""
import json
import os
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "processed"
os.environ["HDX_API"] = "http://127.0.0.1:9/none"
os.environ["OPEN_METEO_API"] = "http://127.0.0.1:9/none"
os.environ["IRIS_CACHE"] = str(ROOT / ".pytest_cache" / "iris")  # no saved forecast


def run(script):
    at = AppTest.from_file(str(ROOT / "app" / script), default_timeout=180).run()
    assert not at.exception, at.exception
    return at


def test_national_app_runs():
    at = run("app.py")
    assert len(at.tabs) == 5


def test_metro_manila_app_runs_and_widgets_work():
    at = run("metro_manila.py")
    assert [t.label for t in at.tabs] == ["Rainfall alert", "Outlook", "Flood exposure by barangay",
                                          "Supply checklist", "Evidence"]
    [s for s in at.selectbox if s.label == "City"][0].set_value("City of Marikina").run()
    assert not at.exception, at.exception
    for r in list(at.radio):
        r.set_value(r.options[-1]).run()
        assert not at.exception, at.exception
    at.toggle[0].set_value(True).run()   # Typhoon Carina example
    assert not at.exception, at.exception
    assert any("ALERT" in e.value for e in at.error)


@pytest.mark.parametrize("mm, expect", [(100, 0), (200, None), (300, None)])
def test_flood_outlook_levels(mm, expect):
    at = run("metro_manila.py")
    [s for s in at.slider if s.label.startswith("10-day rainfall")][0].set_value(mm).run()
    assert not at.exception, at.exception
    at_risk = [m for m in at.metric if m.label == "Barangays with any area in these zones"]
    if expect == 0:
        assert not at_risk
    else:
        assert int(at_risk[0].value.replace(",", "")) > 0


def test_barangay_totals_match_readme():
    geo = json.loads((DATA / "ncr_barangays.geojson").read_text())
    bgy = pd.DataFrame([f["properties"] for f in geo["features"]])
    assert len(bgy) == 1710
    assert round(bgy["people_med_high"].sum(), -3) == 4_244_000
    assert round(bgy["vulnerable_med_high"].sum(), -3) == 607_000


def test_lag_peak_is_three_weeks():
    lag = pd.read_csv(DATA / "lag_results.csv")
    main = lag[lag["model"].str.startswith("Main")]
    assert int(main.loc[main["rr"].idxmax(), "lag_weeks"]) == 3


def test_month_outlook_shape():
    m = pd.read_csv(DATA / "ncr_month_outlook.csv")
    assert list(m["month"]) == list(range(1, 13))
    assert m["chance_alert"].between(0, 1).all() and (m["chance_flood"] <= m["chance_alert"]).all()


def test_flood_tab_rank_options():
    at = run("metro_manila.py")
    pick = next(r for r in at.radio if r.label == "Rank and colour by")
    for option in pick.options:
        pick.set_value(option).run()
        assert not at.exception, at.exception
        pick = next(r for r in at.radio if r.label == "Rank and colour by")
