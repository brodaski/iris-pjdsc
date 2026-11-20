"""Download the raw HDX files the notebooks need into datasets/, and check them against SHA256SUMS.

    python tools/get_data.py            # download what is missing, then check
    python tools/get_data.py --record   # write SHA256SUMS from the files you have (after a fresh download)

Two sources cannot be downloaded by script and are listed at the end: the UP NOAH flood map and the University of
Mindanao case data on Mendeley Data. See the Data section of the README.
"""
import hashlib
import sys
from pathlib import Path

import requests

RAW = Path(__file__).resolve().parent.parent / "datasets"
SUMS = RAW.parent / "SHA256SUMS"
HDX = "https://data.humdata.org/api/3/action/package_show"
FILES = {  # file name in datasets/ -> (HDX dataset id, resource name)
    "phl-rainfall-subnat-full.csv": ("phl-rainfall-subnational", "phl-rainfall-subnat-full.csv"),
    "2020-census-total-popn_single-age_malefemale_admin4.xlsx": (
        "popn-single-year-age-sex-and-barangay-census-2020", "2020-census-total-popn_single-age_malefemale_admin4.xlsx"),
    "phl_admin_boundaries.gdb.zip": ("philippines-administrative-levels-0-to-3", "phl_admin_boundaries.gdb.zip"),
}
MANUAL = ["MetroManila_Flood_100year.shp (and .dbf, .prj, .shx): UP NOAH Center, https://noah.up.edu.ph",
          "Diseases Data (for NBL).xlsx: https://data.mendeley.com/datasets/v98325dpxv/1"]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(name, dataset, resource):
    pkg = requests.get(HDX, params={"id": dataset}, timeout=30).json()["result"]
    url = next((r["url"] for r in pkg["resources"] if r["name"] == resource), None)
    if url is None:
        print(f"{resource} is not listed any more; download it by hand from https://data.humdata.org/dataset/{dataset}")
        return
    print(f"Downloading {name} ...")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(RAW / name, "wb") as f:
            for block in r.iter_content(1 << 20):
                f.write(block)


RAW.mkdir(exist_ok=True)
if "--record" not in sys.argv:
    for name, (dataset, resource) in FILES.items():
        if not (RAW / name).exists():
            download(name, dataset, resource)
present = sorted(p for p in RAW.iterdir() if p.is_file())
if "--record" in sys.argv:
    SUMS.write_text("".join(f"{sha256(p)}  {p.name}\n" for p in present))
    print(f"Wrote {SUMS} for {len(present)} files")
elif SUMS.exists():
    expected = dict(line.split("  ", 1)[::-1] for line in SUMS.read_text().split("\n") if line)
    for p in present:
        want = expected.get(p.name)
        print(f"{'OK      ' if want == sha256(p) else 'NEW     ' if want is None else 'CHANGED '} {p.name}")
print("\nGet these by hand:\n- " + "\n- ".join(MANUAL))
