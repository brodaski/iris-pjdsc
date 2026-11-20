# Revisions for the finals (20 November 2026)

This folder is a revised copy of `rain-to-risk/`. The original folder is unchanged, and nothing was pushed to GitHub.

## Robustness and reproducibility
- The Outlook tab always has a forecast. When Open-Meteo cannot be reached and no recent download is saved, the app
  shows a forecast copy that ships with it (`data/processed/forecast_snapshot_*.csv`, fetched 20 Nov 2026), with
  its date. Refresh it before a demo: `python tools/refresh_forecast_snapshot.py`.
- `tools/` is now part of the project: `check_open_meteo.py`, `refresh_forecast_snapshot.py`, and `get_data.py`
  (downloads the HDX raw files and checks them against `SHA256SUMS`; run `--record` once after a fresh download).
- Calculations moved into `app/iris_core.py` and are covered by unit tests. 22 tests, all passing.
- `scipy` added to `requirements.txt` (used for the case ranges); `scikit-learn` added to `requirements-dev.txt`.

## Model
- New `notebooks/00_eda.ipynb`: distributions of rain and cases, missing weeks and outliers in the DOH counts,
  seasonality, and a first look at rain vs cases (they line up best about 3 weeks apart, even after removing season
  and year). Each section says how it shaped notebooks 01 to 05. Needs only `data/processed`.
- New `notebooks/IRIS_full_pipeline.ipynb`: all six notebooks in one, run top to bottom with Run All (01, 03, 00,
  02, 04, 05, so the data is built before it is explored). Saved with its outputs. A full run from the raw files gave
  the same `data/processed` tables and maps as the separate notebooks. `tools/build_full_notebook.py` rebuilds it.
- New `notebooks/05_forecast_backtest.ipynb`: three models (seasonal baseline, seasonal + rain, gradient boosting),
  each tested on 2021, 2022 and 2023 after training only on earlier years. The old backtest scaled predictions to
  the test year's own average, which used test data; the new one scales to cases reported up to 2 weeks earlier.
  The backtest cells were removed from notebook 02.
- Honest result: over the three years the rain models had a lower error than the baseline (41 and 45 vs 46 cases a
  week), but seasonal + rain lost to the baseline in 2022. The README and app now say the case outlook is indicative.
- The case outlook shows an 80% range for each week.

## App
- Rainfall alert tab opens with a forecast warning ("pre-position doxycycline now") when the 16-day forecast
  reaches the alert level.
- "Replay a past flood" (Habagat 2018, Carina 2024) replaces the Carina-only toggle, with what actually happened.
- Plain explanations of the 10-day rainfall, the alert level and the dates; Evidence tab explains the lag model in
  plain words, shows the effect as "% more cases", explains why 1.17 matters for a big storm (about 3 times the cases
  at 70% of provinces), labels the event study as leptospirosis, and shows the other-disease check as one sentence.
- Flood tab: ranking by share of residents in flood zones is now the default; a worked example walks through the
  overlay for any barangay.
- Supply checklist: low, moderate and high exposure regimens from the PhilHealth policy statements; a printable
  one-page brief for any city (download, open in a browser, print or save as PDF).
- Language switch (English / Filipino) for tab names and main alerts. Please check the Filipino wording.
- Sources list in the Evidence tab.

## README and sources
- Cited the Ondoy figures (Rappler, n.d.), the NKTI gym ward (Bosano, 2024) and the 72-hour window (PhilHealth, n.d.);
  added scikit-learn; PNA link uses www.pna.gov.ph. Deploy steps added.
- Still to check by hand: the year of the Rappler article (about 2012), and the Labana (2026) citation details,
  which I could not open.

## Not done
- Public deployment (needs your Streamlit sign-in), a region setting for other cities, 2024 to 2026 cases from DOH
  PDFs, alert subscriptions, and checking the barangay ranking against Carina flood reports.
