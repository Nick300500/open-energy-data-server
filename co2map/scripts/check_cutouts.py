"""
Completeness check of the weather cutouts (atlite .nc files) the CO2-Map
builds in cosema/generation/vre.py::run_vre_calculations.

Why a separate check: meteo_hist.py::fetch_data only logs a grid point whose
download failed after all retries and returns None -- the cutout is still
written, with that point missing (NaN). vre_gen/vre_forecast in the DB don't
show this (a state's generation just comes out a bit lower), so it has to be
checked on the files themselves.

Per file:
- grid       x/y count, regular spacing (dx/dy), same shape as the other files
- time       hourly without holes, covers the range in the file name
             (cutout_{YYYY_MM_DD}_{MM_DD}_{mode}.nc, end day inclusive)
- NaN        share per variable, plus grid points that are NaN for the whole
             period in a core variable (= a dropped download)

Usage (on the server, inside the container):
    docker exec oeds-co2map python scripts/check_cutouts.py
    docker exec oeds-co2map python scripts/check_cutouts.py --csv logs/cutout_check.csv
Locally:
    python scripts/check_cutouts.py --dir path/to/cutouts

Exit code 1 if any file has a problem, so the check can gate a backfill.
check_cutout(path) is importable for checking a single file right after it
was built.
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

DEFAULT_DIR = Path("inputs/cutouts")
GRID_STEP = 0.25

# Variables every downstream calculation needs (wind: wind speed/roughness, pv:
# influx_*/albedo/temperature). Open-Meteo and ERA5 parts are both covered, so
# a failed download on either side shows up here.
CORE_VARS = [
    "roughness",
    "influx_toa",
    "influx_direct",
    "influx_diffuse",
    "albedo",
    "temperature",
]
# Wind speed height differs by module: meteo_hist (historical) writes wnd100m,
# meteo (forecast) writes wnd80m.
WIND_VARS = ("wnd100m", "wnd80m")

NAME_PATTERN = re.compile(
    r"^cutout_(?P<year>\d{4})_(?P<sm>\d{2})_(?P<sd>\d{2})_(?P<em>\d{2})_(?P<ed>\d{2})_(?P<mode>\w+)\.nc$"
)


def expected_range(path: Path):
    """Start/end hour implied by the file name, or None if it doesn't match."""
    m = NAME_PATTERN.match(path.name)
    if not m:
        return None
    start = pd.Timestamp(int(m["year"]), int(m["sm"]), int(m["sd"]))
    end_year = start.year + (1 if int(m["em"]) < start.month else 0)
    end = pd.Timestamp(end_year, int(m["em"]), int(m["ed"]), 23)
    return start, end


def _regular(values: np.ndarray) -> bool:
    return len(values) > 1 and np.allclose(np.diff(values), GRID_STEP)


def check_cutout(path: Path) -> dict:
    path = Path(path)
    result = {"file": str(path), "problems": []}
    problems = result["problems"]

    try:
        ds = xr.open_dataset(path, chunks={})
    except Exception as e:  # unreadable / truncated file
        problems.append(f"nicht lesbar: {e.__class__.__name__}: {e}")
        return result

    with ds:
        result["n_x"], result["n_y"] = ds.sizes.get("x", 0), ds.sizes.get("y", 0)
        result["shape"] = (result["n_y"], result["n_x"])
        if not (_regular(ds.x.values) and _regular(ds.y.values)):
            problems.append(f"Raster nicht regelmäßig {GRID_STEP}°")

        time = ds.time.to_index()
        result["time_min"], result["time_max"], result["n_hours"] = time.min(), time.max(), len(time)
        full = pd.date_range(time.min(), time.max(), freq="h")
        result["missing_hours"] = len(full.difference(time))
        if result["missing_hours"]:
            problems.append(f"{result['missing_hours']} Stunden fehlen in der Zeitachse")
        if time.has_duplicates:
            problems.append("doppelte Zeitstempel")

        expected = expected_range(path)
        if expected is None:
            problems.append("Dateiname passt nicht zum Schema aus vre.py")
        elif time.min() > expected[0] or time.max() < expected[1]:
            problems.append(
                f"Zeitraum {time.min()} bis {time.max()} deckt {expected[0]} bis {expected[1]} nicht ab"
            )

        wind = next((v for v in WIND_VARS if v in ds), "/".join(WIND_VARS))
        core_vars = [wind, *CORE_VARS]
        missing_vars = [v for v in core_vars if v not in ds]
        if missing_vars:
            problems.append(f"Variablen fehlen: {missing_vars}")

        nan_share = {v: float(ds[v].isnull().mean()) for v in ds.data_vars}
        result["nan_share"] = {v: s for v, s in nan_share.items() if s > 0}
        result["dropped_points"] = 0
        for v in core_vars:
            if v not in ds or "time" not in ds[v].dims:
                continue
            dropped = int(ds[v].isnull().all("time").sum())
            result["dropped_points"] = max(result["dropped_points"], dropped)
            if nan_share[v] > 0:
                problems.append(
                    f"{v}: {nan_share[v]:.2%} NaN, {dropped} Punkte komplett leer"
                )

    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--csv", type=Path, help="Ergebnis zusätzlich als CSV schreiben")
    args = parser.parse_args()

    files = sorted(args.dir.glob("*/*.nc"))
    if not files:
        print(f"Keine Cutouts unter {args.dir}/*/*.nc gefunden.")
        return 1

    results = [check_cutout(f) for f in files]

    # A grid point dropped at the edge shrinks x/y instead of leaving a NaN,
    # so compare every file's shape with the most common one.
    shapes = Counter(r["shape"] for r in results if "shape" in r)
    if shapes:
        usual = shapes.most_common(1)[0][0]
        for r in results:
            if r.get("shape", usual) != usual:
                r["problems"].append(f"Raster {r['shape']} weicht vom üblichen {usual} ab (y, x)")

    n_bad = 0
    for r in results:
        status = "OK " if not r["problems"] else "FEHLER"
        n_bad += bool(r["problems"])
        span = f"{r.get('time_min')} bis {r.get('time_max')}" if "time_min" in r else ""
        print(f"{status} {r['file']}  {r.get('n_y')}x{r.get('n_x')}  {span}")
        for p in r["problems"]:
            print(f"       - {p}")
        if r.get("nan_share") and not r["problems"]:
            print(f"       (NaN nur in Nebenvariablen: {r['nan_share']})")

    print(f"\n{len(results)} Dateien, {n_bad} mit Problemen.")

    if args.csv:
        rows = [
            {
                **{k: v for k, v in r.items() if k not in ("problems", "nan_share", "shape")},
                "nan_share": "; ".join(f"{k}={v:.4f}" for k, v in r.get("nan_share", {}).items()),
                "problems": "; ".join(r["problems"]),
            }
            for r in results
        ]
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(args.csv, index=False)
        print(f"CSV: {args.csv}")

    return 1 if n_bad else 0


if __name__ == "__main__":
    sys.exit(main())
