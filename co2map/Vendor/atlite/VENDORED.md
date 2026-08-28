# atlite: vendored copy — local patches

This `atlite/` directory is a **vendored copy** of [PyPSA/atlite](https://github.com/PyPSA/atlite),
based on **PyPI release 0.2.14** (see `atlite/version.py`). It is not installed as a pip
dependency because the project depends on local patches that don't exist upstream.

Kept vendored on purpose (decision from 2026-07-15): the local changes below are load-bearing
for this pipeline, not cosmetic. Switching to `pip install atlite` would break ERA5 downloads
(old CDS API) and remove three data-source modules this project relies on.

## How this was verified

Compared file-by-file against the `atlite==0.2.14` wheel from PyPI (CRLF/LF-neutral diff).
To reproduce:

```bash
pip download atlite==0.2.14 --no-deps -d /tmp/atlite_upstream
unzip /tmp/atlite_upstream/atlite-0.2.14-py2.py3-none-any.whl -d /tmp/atlite_upstream/extracted
diff -rq atlite /tmp/atlite_upstream/extracted/atlite   # then re-check flagged files ignoring \r
```

## Files identical to upstream 0.2.14

`aggregate.py`, `convert.py`, `csp.py`, `hydro.py`, `resource.py`, `utils.py`, `version.py`,
`wind.py`, `__init__.py`, `pv/__init__.py`, `pv/irradiation.py`, `pv/orientation.py`,
`pv/solar_panel_model.py`, `pv/solar_position.py`, `datasets/cordex.py`, `datasets/gebco.py`,
`datasets/ncep.py`, `datasets/sarah.py`.

`cutout.py` differs only in two lines of `black`-style line-wrapping — no behavioral change.

## Files with real local changes

### `datasets/__init__.py` and 3 new local-only modules
Adds three data-source modules that don't exist upstream: `datasets/dwd.py`,
`datasets/meteo.py`, `datasets/meteo_hist.py`. Registered in `modules = {...}` alongside
`era5`, `sarah`, `gebco`.
**Why:** custom weather data sources used by this project's pipeline.

### `datasets/era5.py`
Rewritten to use the **new Copernicus CDS API** (`cds.climate.copernicus.eu/api`) instead of
the old one the 0.2.14 release still targets. The old API was deprecated/shut down in 2024, so
upstream 0.2.14 as released can no longer download ERA5 data at all.
Key differences: downloads a `.zip` (`download_format: "zip"`) and unzips in memory instead of
downloading a `.nc` directly; request payload uses zero-padded lists for
year/month/day/variable instead of bare strings (required by the new API).
**Why:** necessary to keep ERA5 downloads working; not optional.

⚠️ **Known gap (fixed 2026-07-15):** upstream 0.2.14 clears stale `int16` netcdf encoding
inherited from the CDS download before writing the cutout back to disk, to avoid a known
xarray bug where float data gets silently corrupted to NaN on re-save
(https://github.com/pydata/xarray/issues/7691). This project's `era5.py`/`data.py` was missing
that cleanup. **Fixed** in `atlite/data.py` (`cutout_prepare`, before `ds.to_netcdf(tmp)`) by
clearing `.encoding` on any variable with `dtype == "int16"` right before the write.

### `gis.py`
`get_coords()`'s default ERA5 time range extends 4 weeks into the future
(`pd.Timestamp('now') + pd.Timedelta(weeks=4)`) instead of hard-stopping at `"now"`.
**Why:** appears intentional, to allow cutouts spanning near-future dates. Not yet confirmed
with Nick — flag if this causes unexpected empty/NaN data near the cutout's end.

### `data.py`
- Missing upstream's optional per-variable compression encoding for newly prepared features
  (upstream: `if compression: ds[v].encoding.update(...)`). Effect: cutouts written by this
  project are not compressed on disk even when a `compression` dict is passed — larger files,
  not a correctness issue.
- `ProgressBar()` always shown in `cutout_prepare`, regardless of `show_progress` argument
  (upstream only shows it when `show_progress=True`). Cosmetic only.

## Not yet compared

`resources/*.yaml` (turbine/solar-panel spec files) showed as differing in the raw file diff,
but this was not investigated further — worth checking before relying on default turbine/panel
curves if results look off.

## Newer upstream (GitHub `main`, not 0.2.14)

The current `PyPSA/atlite` `main` branch (https://github.com/PyPSA/atlite/blob/master/atlite)
is substantially newer than 0.2.14: full type hints, `atlite._types` module, removed backward-
compat shims (`xs`/`ys`, `years`/`months`, old `cutout_dir`/`name` cutout format), and adds a
`cooling_demand` conversion function that doesn't exist in this vendored copy at all. This
project has not been evaluated against `main` — only against the pinned 0.2.14 release.
