"""Update the forecast copy that ships with the app (data/processed/forecast_snapshot_*.csv).

The app shows this copy, with its date, when Open-Meteo cannot be reached and no recent download is saved on the
computer (for example right after a deploy). Run it before a demo or a deploy:

    python tools/refresh_forecast_snapshot.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
from rain_data import DATA, fetch_forecast_daily, save_snapshot  # noqa: E402

daily = fetch_forecast_daily()
now = pd.Timestamp.now(tz="Asia/Manila").tz_localize(None)
save_snapshot(daily, now.strftime("%Y-%m-%d %H:%M"), DATA)
print(f"Saved the forecast for {daily['day'].min():%d %b} to {daily['day'].max():%d %b %Y} into {DATA}")
