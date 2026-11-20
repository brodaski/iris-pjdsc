"""Plain calculations behind the dashboard, kept out of the Streamlit script so they can be tested on their own.

Nothing here reads files or draws anything: each function takes data frames or numbers and returns numbers.
"""
import html

import pandas as pd

# Post-exposure doxycycline by exposure risk (PhilHealth policy statements, after the Leptospirosis CPG 2010).
# capsules = 100 mg capsules per person; the high-risk regimen repeats every week of exposure.
REGIMENS = {
    "Low risk: waded once, no wounds": dict(
        dose="200 mg once, within 24 to 72 hours of wading", capsules=2, weekly=False),
    "Moderate risk: waded with wounds, or swallowed floodwater": dict(
        dose="200 mg once a day for 3 to 5 days, started within 24 to 72 hours (stock for 5 days)", capsules=10,
        weekly=False),
    "High risk: living in flooded areas, rescuers, relief workers": dict(
        dose="200 mg once a week until exposure ends", capsules=2, weekly=True),
}


def dekad_end(start):
    """First day after a CHIRPS 10-day period. Periods run 1st to 10th, 11th to 20th and 21st to the month's end."""
    start = pd.Timestamp(start)
    if start.day == 21:
        return start + pd.offsets.MonthBegin(1)
    return start + pd.Timedelta(days=10)


def alert_dates(start, rise_from, peak, rise_to):
    """Dates for the case surge after an alert period that starts on `start`. The heavy rain can fall on any day of
    the period, so prepare from its first day and stand down from its last day."""
    start = pd.Timestamp(start)
    end = dekad_end(start)
    return {"ready_by": start + pd.Timedelta(weeks=rise_from - 1),
            "peak_from": start + pd.Timedelta(weeks=peak), "peak_to": end + pd.Timedelta(weeks=peak),
            "alert_until": end + pd.Timedelta(weeks=rise_to)}


def flood_level(mm, alert_mm, flood_mm):
    """Which hazard zones a 10-day rain total is expected to flood: (level name, barangay share column)."""
    if mm >= flood_mm:
        return "widespread", "flood_share_med_high"
    if mm >= alert_mm:
        return "high zones", "share_var3"
    return None, None


def exposed(bgy, share_col):
    """People and under-5 or 65+ residents in the zones expected to flood, by barangay (area-share estimate)."""
    out = bgy.assign(people_risk=bgy["population"] * bgy[share_col],
                     vuln_risk=(bgy["under5"] + bgy["over65"]) * bgy[share_col])
    return out[out["people_risk"] > 0]


def wettest_window(ncr_daily, today, days=10):
    """Wettest `days`-day total in the forecast part of a daily series: (mm, last day), or (None, None)."""
    n = ncr_daily.sort_values("day").reset_index(drop=True)
    n = n.assign(total=n["mm"].rolling(days).sum())
    ahead = n[(n["day"] >= today + pd.Timedelta(days=days - 1)) & n["total"].notna()]
    if ahead.empty:
        return None, None
    top = ahead.loc[ahead["total"].idxmax()]
    return float(top["total"]), top["day"]


def supply(bgy, zone_share, wade_pct, regimen, weeks=1):
    """People to cover and doxycycline capsules per barangay for one regimen."""
    r = REGIMENS[regimen]
    s = bgy.copy()
    s["in_zone"] = s["population"] * zone_share
    s["to_cover"] = (s["in_zone"] * wade_pct / 100).round(0)
    s["doxy_caps"] = (s["to_cover"] * r["capsules"] * (weeks if r["weekly"] else 1)).round(0)
    s["under5_zone"] = (s["under5"] * zone_share).round(0)
    s["over65_zone"] = (s["over65"] * zone_share).round(0)
    return s


def city_brief_html(city, status_line, dates, top, totals, regimen, source_note):
    """A one-page HTML brief for a city health office, ready to print or save as PDF from the browser."""
    e = html.escape
    rows = "".join(
        f"<tr><td>{i}</td><td>{e(r.barangay)}</td><td>{r.flood_share_med_high:.0%}</td>"
        f"<td>{r.vulnerable_med_high:,.0f}</td><td>{r.to_cover:,.0f}</td><td>{r.doxy_caps:,.0f}</td></tr>"
        for i, r in enumerate(top.itertuples(), 1))
    date_rows = "".join(f"<li><b>{e(k)}:</b> {e(v)}</li>" for k, v in dates.items())
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>IRIS brief: {e(city)}</title>
<style>body{{font-family:Arial,sans-serif;max-width:780px;margin:24px auto;color:#222;line-height:1.4}}
h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:16px;margin:20px 0 6px}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:4px 6px;font-size:13px;text-align:left}}th{{background:#f2f2f2}}
.status{{padding:8px 10px;border-left:4px solid #c1121f;background:#fbeaea}}small{{color:#555}}</style></head><body>
<h1>IRIS leptospirosis brief: {e(city)}</h1>
<div class="status">{e(status_line)}</div>
<h2>Key dates</h2><ul>{date_rows}</ul>
<h2>Supplies (regimen: {e(regimen)})</h2>
<p>{totals['to_cover']:,.0f} people to cover, {totals['doxy_caps']:,.0f} doxycycline 100 mg capsules,
{totals['under5_zone']:,.0f} children under 5 and {totals['over65_zone']:,.0f} adults 65+ in flood zones.</p>
<h2>Barangays to prepare first</h2>
<table><tr><th>#</th><th>Barangay</th><th>Area in medium or high zones</th><th>Under 5 or 65+ in zones</th>
<th>People to cover</th><th>Capsules</th></tr>{rows}</table>
<p><small>{e(source_note)} Planning estimates only: check quantities and regimens with current DOH guidance.
Doxycycline is generally avoided in pregnancy and young children.</small></p></body></html>"""
