"""
One-off manual test (2026-08-29): does the core calculation logic
(regionalization + intensities) produce sane output against a window with
confirmed real entsoe_raw data, as opposed to the "everything is zero"
degenerate case the live scheduler has been hitting since OEDS's crawler
stalled (2026-07-27) -- see cosema/calc_intensities.py's collect_and_prepare_data
IndexError, found the same day. This script exists to answer that question
directly rather than continuing to patch defensive edge cases uncovered only
by the all-zero scenario.

No downloads (download_per_type/demand/cross_border/per_unit all off):
query_per_type_gen/query_demand_data/query_cross_border_flows already read
live from entsoe_raw (see cosema/input_output/influxdb.py), no separate
ingestion step needed. entsoe_client is therefore never touched -- None is
fine, no real ENTSO-E API key needed for this test.

VRE (run_vre_historical) also off for this first pass, to isolate whether
regionalization/intensities work on their own before pulling in atlite's
weather-cutout generation (needs a real CDSAPI_KEY + network access) as a
second variable.

Set TEST_MODE=with_per_unit to instead mirror updated_calculations.py's daily
job (reg_mode="with_per_unit"). Still no new downloads even in this mode --
download_per_unit/run_vre_historical stay off, reusing whatever is already in
cosema.per_unit_gen/cosema.vre_gen from a real prior run instead of triggering
a fresh ENTSO-E/CDS pull. Pick TEST_START/TEST_END inside a window both
tables already fully cover, or check_per_unit_data()'s "using data until ..."
fallback will silently shorten the window.

Run inside the container:
  docker run --rm -e DB_HOST=... -e DB_PORT=... -e DB_NAME=... -e DB_USER=... -e DB_PASSWORD=... \
    co2map:test python scripts/test_pipeline_real_data.py
"""
import logging
import os

import pandas as pd

from cosema.input_output.influxdb import DBClient
from cosema.logging import get_handlers
from cosema.pipelines.runner import run_pipeline

handlers = get_handlers(log_path="logs/test_pipeline_real_data.log")
logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)
logger = logging.getLogger(__name__)

# Default window has complete generation and demand data (96 rows/day each
# for DE_LU) in production's entsoe_raw, checked 2026-09-21. Production has
# multi-day gaps elsewhere (e.g. 2026-09-15..18), so check per-day row counts
# before picking another window. Override with TEST_START / TEST_END.
START = pd.Timestamp(os.environ.get("TEST_START", "2026-09-10 00:00"), tz="UTC")
END = pd.Timestamp(os.environ.get("TEST_END", "2026-09-11 00:00"), tz="UTC")

db_client = DBClient(
    database_name=os.environ.get("DB_NAME", "opendata"),
    host=os.environ.get("DB_HOST", "localhost"),
    port=int(os.environ.get("DB_PORT", "5432")),
    username=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
)

MODE = os.environ.get("TEST_MODE", "only_per_type")
assert MODE in ("only_per_type", "with_per_unit"), f"unknown TEST_MODE {MODE!r}"

logger.info(f"Running pipeline for {START} - {END} (real-data window, no downloads, mode={MODE})")

run_pipeline(
    start=START,
    end=END,
    db_client=db_client,
    entsoe_client=None,
    download_per_type=False,
    download_demand=False,
    download_demand_forecast=False,
    download_cross_border=False,
    download_per_unit=False,
    run_vre_historical=False,
    run_vre_forecast=False,
    run_regionalization=True,
    run_intensities=True,
    reg_mode=MODE,
)

logger.info("Done -- check the cosema schema's co2_intensity table for output.")
