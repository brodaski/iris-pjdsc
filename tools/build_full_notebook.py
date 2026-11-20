"""Join notebooks 00 to 05 into one notebook that runs top to bottom: notebooks/IRIS_full_pipeline.ipynb.

The separate notebooks stay the source. Run this again after editing any of them, then run the joined notebook:

    python tools/build_full_notebook.py
    jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=-1 notebooks/IRIS_full_pipeline.ipynb
"""
from pathlib import Path

import nbformat

NB = Path(__file__).resolve().parent.parent / 'notebooks'

# Order: build the processed data first (01, 03), look at it (00), then the analysis (02, 04, 05).
PARTS = [
    ('01_prepare_data.ipynb', 'Prepare the rain and case data'),
    ('03_metro_manila_flood.ipynb', 'Metro Manila flood drill-down'),
    ('00_eda.ipynb', 'Exploratory data analysis'),
    ('02_lag_analysis.ipynb', 'Lag analysis'),
    ('04_metro_manila_outlook.ipynb', 'Metro Manila outlook'),
    ('05_forecast_backtest.ipynb', 'Forecast backtest'),
]

INTRO = """# IRIS: the full pipeline in one notebook

This notebook joins the six project notebooks so the whole analysis runs top to bottom with **Run All**. Each part
keeps its original notebook's text and code, and its first cell sets up its own paths and data, so a part can
also be rerun on its own after the parts before it have run once.

| Part | Original notebook | What it does |
| --- | --- | --- |
{rows}

**Before you run it.** Put the raw files in `datasets/` (see the README): `phl-rainfall-subnat-full.csv`,
`Diseases Data (for NBL).xlsx`, `phl_admin_boundaries.gdb/`, `MetroManila_Flood_100year.shp` (with its .dbf, .shx
and .prj) and `2020-census-total-popn_single-age_malefemale_admin4.xlsx`. The next cell checks they are there.

**Run time.** About 10 to 15 minutes in all; the flood overlay in Part 2 takes most of it.

**What it writes.** The files in `data/processed/` that the dashboard reads. Running it again overwrites them with
the same results. `provinces.geojson` is only rebuilt if it is missing.

The separate notebooks are still the source: after editing one, rebuild this file with
`python tools/build_full_notebook.py`."""

CHECK = """# Check that the raw files are in place before the long run starts
from pathlib import Path

ROOT = Path('..') if Path.cwd().name == 'notebooks' else Path('.')
RAW = ROOT / 'datasets'
NEEDED = ['phl-rainfall-subnat-full.csv', 'Diseases Data (for NBL).xlsx', 'phl_admin_boundaries.gdb',
          'MetroManila_Flood_100year.shp', 'MetroManila_Flood_100year.dbf', 'MetroManila_Flood_100year.shx',
          'MetroManila_Flood_100year.prj', '2020-census-total-popn_single-age_malefemale_admin4.xlsx']
missing = [f for f in NEEDED if not (RAW / f).exists()]
if missing:
    raise FileNotFoundError(f'Missing from {RAW.resolve()}: ' + ', '.join(missing))
print('All raw files found in', RAW.resolve())"""

# The EDA part changes matplotlib's chart style; put it back afterwards so later charts (and the saved
# lag_curve.png) look the same as when their notebooks run on their own.
SAVE_STYLE = """import matplotlib
_style_before = matplotlib.rcParams.copy()   # restored at the end of this part"""
RESTORE_STYLE = """matplotlib.rcParams.update(_style_before)   # back to the default chart style for the parts below"""


def main():
    first = nbformat.read(NB / PARTS[0][0], as_version=4)
    rows = '\n'.join(f'| {i} | `{f}` | {title} |' for i, (f, title) in enumerate(PARTS, 1))
    cells = [nbformat.v4.new_markdown_cell(INTRO.format(rows=rows)), nbformat.v4.new_code_cell(CHECK)]
    for i, (fname, title) in enumerate(PARTS, 1):
        src = nbformat.read(NB / fname, as_version=4)
        head = src.cells[0]
        assert head.cell_type == 'markdown' and head.source.startswith('#'), fname
        body = head.source.split('\n', 1)[1] if '\n' in head.source else ''
        if fname == '00_eda.ipynb':
            body = body.replace('(made by notebooks 01, 03 and 04), so it needs no raw downloads',
                                '(made in Parts 1 and 2 above)')
        cells.append(nbformat.v4.new_markdown_cell(f'---\n# Part {i}: {title}\n\n*From `notebooks/{fname}`.*\n{body}'))
        if fname == '00_eda.ipynb':
            cells.append(nbformat.v4.new_code_cell(SAVE_STYLE))
        for c in src.cells[1:]:
            new = (nbformat.v4.new_code_cell(c.source) if c.cell_type == 'code'
                   else nbformat.v4.new_markdown_cell(c.source))
            cells.append(new)
        if fname == '00_eda.ipynb':
            cells.append(nbformat.v4.new_code_cell(RESTORE_STYLE))
    out = nbformat.v4.new_notebook(cells=cells, metadata=first.metadata)
    nbformat.write(out, NB / 'IRIS_full_pipeline.ipynb')
    print(f'Wrote {NB / "IRIS_full_pipeline.ipynb"} ({len(cells)} cells)')


if __name__ == '__main__':
    main()
