# %%
import logging

import pandas as pd
import yaml
from entsoe import EntsoePandasClient

from cosema.capacities.mastr import calculate_total_capacities_for_cosema
from cosema.input_output.influxdb import DBClient
from cosema.logging import get_handlers
from cosema.pipelines.runner import run_pipeline

handlers = get_handlers(log_path="logs/manual_runs.log")
logging.basicConfig(level=logging.INFO, handlers=handlers)

logger = logging.getLogger(__name__)

# read config.yaml
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

# load keys.yaml where the database and entsoe keys are stored
with open("keys.yaml", "r") as f:
    keys = yaml.safe_load(f)

db_client = DBClient(
    database_name="cosema",
    username=keys["influxdb"]["username"],
    password=keys["influxdb"]["password"],
)

# timeout=: without it, a request whose server accepts the connection but never
# replies hangs forever (retry_function's ConnectionError catch never triggers,
# because no exception is ever raised) -- observed 2026-07-22/23, a cross-border
# flow request stalled for 3.5h+ with zero progress. The timeout turns that into
# a Timeout exception, which retry_function now retries like any other failure.
entsoe_client = EntsoePandasClient(api_key=keys["entsoe-key"], timeout=60)

# Start and end date
start = pd.Timestamp("2026-02-01 00:00", tz="UTC")
end = pd.Timestamp("2026-03-01 00:00", tz="UTC")

get_per_type_data = 0
get_demand_data = 0
get_demand_forecast_data = 0
get_cross_border_flows = 0
get_per_unit_data = 0
get_vre_historical_data = 1
get_vre_forecast_data = 0
run_regionalization = 1
calc_intensities = 1

calc_generation_capacities = 0

reg_mode = "with_per_unit"  # "only_per_type" / "with_per_unit"


# %%
if True:
# for month in pd.date_range(start=start, end=end, freq="MS"):
    if end - start > pd.Timedelta(days=30):
        temp_start = month
        temp_end = month + pd.DateOffset(months=1)
    else:
        temp_start = start
        temp_end = end

    logger.info(f"Running for {temp_start} to {temp_end}")

    run_pipeline(
        start=temp_start,
        end=temp_end,
        db_client=db_client,
        entsoe_client=entsoe_client,
        download_per_type=bool(get_per_type_data),
        download_demand=bool(get_demand_data),
        download_demand_forecast=bool(get_demand_forecast_data),
        download_cross_border=bool(get_cross_border_flows),
        download_per_unit=bool(get_per_unit_data),
        run_vre_historical=bool(get_vre_historical_data),
        run_vre_forecast=bool(get_vre_forecast_data),
        run_regionalization=bool(run_regionalization),
        run_intensities=bool(calc_intensities),
        reg_mode=reg_mode,
    )


# %%
if calc_generation_capacities:
    # conventional and VRE capacity calculation
    update_mastr_db = False

    calculate_total_capacities_for_cosema(
        start_date=start,
        end_date=end,
        update_mastr_db=update_mastr_db,
    )
