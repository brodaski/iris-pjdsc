"""Unit tests for the calculations in app/iris_core.py and app/rain_data.py, with answers worked out by hand."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from iris_core import alert_dates, dekad_end, exposed, flood_level, supply, wettest_window  # noqa: E402
from rain_data import case_range, daily_share, forecast  # noqa: E402


@pytest.mark.parametrize("start, end", [("2024-07-01", "2024-07-11"), ("2024-07-11", "2024-07-21"),
                                        ("2024-07-21", "2024-08-01"), ("2024-02-21", "2024-03-01")])
def test_dekad_end(start, end):
    assert dekad_end(start) == pd.Timestamp(end)


def test_alert_dates_carina():
    d = alert_dates("2024-07-21", rise_from=3, peak=3, rise_to=6)
    assert d["ready_by"] == pd.Timestamp("2024-08-04")
    assert (d["peak_from"], d["peak_to"]) == (pd.Timestamp("2024-08-11"), pd.Timestamp("2024-08-22"))
    assert d["alert_until"] == pd.Timestamp("2024-09-12")


def test_flood_levels():
    assert flood_level(100, 166, 250) == (None, None)
    assert flood_level(200, 166, 250) == ("high zones", "share_var3")
    assert flood_level(250, 166, 250) == ("widespread", "flood_share_med_high")


def test_exposed_and_supply():
    bgy = pd.DataFrame({"population": [1000, 500], "under5": [100, 50], "over65": [50, 20],
                        "share_var3": [0.5, 0.0], "flood_share_med_high": [0.8, 0.1]})
    e = exposed(bgy, "share_var3")
    assert len(e) == 1 and e["people_risk"].iloc[0] == 500 and e["vuln_risk"].iloc[0] == 75
    low = supply(bgy, bgy["flood_share_med_high"], 50, "Low risk: waded once, no wounds")
    assert list(low["to_cover"]) == [400, 25] and list(low["doxy_caps"]) == [800, 50]
    high = supply(bgy, bgy["flood_share_med_high"], 50, "High risk: living in flooded areas, rescuers, relief workers", 3)
    assert list(high["doxy_caps"]) == [2400, 150]


def test_wettest_window():
    days = pd.date_range("2024-07-01", periods=20)
    daily = pd.DataFrame({"day": days, "mm": [0] * 12 + [30] * 8})
    mm, last = wettest_window(daily, pd.Timestamp("2024-07-05"))
    assert mm == 240 and last == pd.Timestamp("2024-07-20")


def test_daily_share_counts_only_full_weeks():
    days = pd.date_range("2024-07-01", periods=10)   # Monday 1 July; the second week is incomplete
    daily = pd.concat([pd.DataFrame({"PCODE": "PH13074", "day": days, "mm": 40.0}),
                       pd.DataFrame({"PCODE": "PH03014", "day": days, "mm": 1.0})])
    share = daily_share(daily)
    assert list(share.index) == [pd.Timestamp("2024-07-01")] and share.iloc[0] == 0.5


def test_forecast_no_rain_means_no_rise():
    weeks = pd.date_range("2024-01-01", periods=20, freq="W-MON")
    fc = forecast(pd.Series(0.0, index=weeks), weeks[-1])
    assert (fc["rise_pct"] == 0).all() and len(fc) == 6


def test_case_range_brackets_the_mean():
    low, high = case_range([50.0, 100.0])
    assert (low < [50, 100]).all() and (high > [50, 100]).all()
