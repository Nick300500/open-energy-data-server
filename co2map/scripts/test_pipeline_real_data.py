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

# Confirmed real (if gappy) entsoe_raw data in this window, verified
# 2026-08-21/2026-08-28 sessions -- see co2map/oeds_integration_plan.md and
# this script's own docstring.
START = pd.Timestamp("2026-07-21 00:00", tz="UTC")
END = pd.Timestamp("2026-07-22 00:00", tz="UTC")

db_client = DBClient(
    database_name=os.environ.get("DB_NAME", "opendata"),
    host=os.environ.get("DB_HOST", "localhost"),
    port=int(os.environ.get("DB_PORT", "5432")),
    username=os.environ["DB_USER"],
    password=os.environ["DB_PASSWORD"],
)

logger.info(f"Running pipeline for {START} - {END} (real-data window, no downloads, no VRE)")

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
    reg_mode="only_per_type",
)

logger.info("Done -- check the cosema schema's co2_intensity table for output.")
