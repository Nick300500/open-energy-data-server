# %%
import logging

import pandas as pd

from cosema.capacities.mastr import calculate_total_capacities_for_cosema
from cosema.logging import get_handlers
from cosema.pipelines.runner import run_pipeline
from cosema.pipelines.scheduler_bootstrap import build_clients

handlers = get_handlers(log_path="logs/manual_runs.log")
logging.basicConfig(level=logging.INFO, handlers=handlers)

logger = logging.getLogger(__name__)

# Same clients as the schedulers: DB_HOST/PORT/NAME/USER/PASSWORD and
# ENTSOE_API_KEY from env vars or .env (locally e.g. via SSH tunnel). Replaces
# keys.yaml (2026-11-15), which doesn't exist in this repo and whose DBClient
# call pointed at localhost:5432/cosema instead of the OEDS database.
db_client, entsoe_client = build_clients()

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
# One pipeline run per calendar month (cut at start/end if they fall
# mid-month), so a long range doesn't load everything into memory at once.
boundaries = sorted({start, end, *pd.date_range(start=start, end=end, freq="MS")})
for temp_start, temp_end in zip(boundaries[:-1], boundaries[1:]):
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
