import argparse
import logging
from datetime import datetime

import pandas as pd

from cosema.logging import get_handlers
from cosema.pipelines.runner import run_pipeline
from cosema.pipelines.scheduler_bootstrap import build_clients, start_scheduler

handlers = get_handlers(log_path="logs/updated_calculations.log")
logging.basicConfig(level=logging.INFO, handlers=handlers)

logger = logging.getLogger(__name__)

# how much time to go back in time to download data
INITIAL_DATE_OFFSET = pd.Timedelta("7d")
# time delta for the calculations
TIME_DELTA = pd.Timedelta("7d")
# when to start the scheduler for the first time
FIRST_RUN_OFFSET = pd.Timedelta(days=1, hours=5, minutes=45)
# how often to run the scheduler [in hours]
TASK_INTERVAL = 24


def init_date(initial_date):
    global timestep
    timestep = initial_date
    logger.info(f"Scheduler initial date set to {timestep} ({timestep.tzinfo})")


def perform_initial_calculations(entsoe_client, db_client, time_delta, interval):
    global timestep

    end = timestep
    start = end - time_delta
    timestep += interval

    run_pipeline(
        start=start,
        end=end,
        db_client=db_client,
        entsoe_client=entsoe_client,
        # Redundant since 2026-08-28, same as initial_calculations.py: these
        # three now come live from OEDS's entsoe_raw instead. download_per_unit
        # stays on -- per-unit (per-power-plant) generation isn't in entsoe_raw
        # (zone-level only), so this is still the only source for it and still
        # needs a real ENTSO-E API key in keys.yaml.
        download_per_type=False,
        download_demand=False,
        download_per_unit=True,
        download_cross_border=False,
        run_vre_historical=True,
        run_regionalization=True,
        run_intensities=True,
        reg_mode="with_per_unit",
    )

    logger.info("Operation sucessfull")
    logger.info(f"Scheduler time advanced to {timestep} ({timestep.tzinfo})")


def main(
    initial_date: pd.Timestamp = None,
    first_run: datetime = None,
    tasks_interval: int = None,
    time_delta: pd.Timedelta = None,
):
    db_client, entsoe_client = build_clients()

    if initial_date is None:
        initial_date = pd.Timestamp("now", tz="UTC").normalize() - pd.Timedelta("7d")
    else:
        initial_date = pd.Timestamp(initial_date, tz="UTC")

    if first_run is None:
        current_date = pd.Timestamp("now", tz="Europe/Berlin").normalize()
        first_run = current_date + FIRST_RUN_OFFSET
    else:
        first_run = pd.Timestamp(first_run, tz="Europe/Berlin")

    tasks_interval = TASK_INTERVAL if tasks_interval is None else tasks_interval

    time_delta = (
        TIME_DELTA if time_delta is None else pd.Timedelta(f"{time_delta}d", tz="UTC")
    )

    logger.info(
        f"Scheduler starts at {first_run} ({first_run.tzinfo}). Scheduler will run every {tasks_interval} hours."
    )
    init_date(initial_date=initial_date)

    start_scheduler(
        perform_initial_calculations,
        job_kwargs={
            "entsoe_client": entsoe_client,
            "db_client": db_client,
            "time_delta": time_delta,
            "interval": pd.Timedelta(f"{tasks_interval}h"),
        },
        job_name="updated_calculations",
        first_run=first_run,
        tasks_interval=tasks_interval,
        misfire_grace_time=60 * 60,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Script to initialize the scheduler for initial data downloads."
    )

    parser.add_argument(
        "-st",
        "--start_date",
        type=str,
        required=False,
        help="n optional argument to the starting date for the calculations in Y-m-d-H:M format. now - 7d by default.",
    )

    parser.add_argument(
        "-r",
        "--first_run",
        type=str,
        required=False,
        help="An optional argument to when to start the scheduler in Y-m-d-H:M. datetine.now() by default.",
    )

    parser.add_argument(
        "-i",
        "--tasks_interval",
        type=int,
        required=False,
        help="An optional argument to set the interval between tasks [in hours]. 24 by default.",
    )

    parser.add_argument(
        "-t",
        "--time_delta",
        type=str,
        required=False,
        help="An optional argument to set the time delta for the calculation [in days]. 7d by default.",
    )

    args = parser.parse_args()

    main(
        initial_date=args.start_date,
        first_run=args.first_run,
        tasks_interval=args.tasks_interval,
        time_delta=args.time_delta,
    )
