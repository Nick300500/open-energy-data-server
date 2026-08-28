import argparse
import logging
from datetime import datetime

import pandas as pd

from cosema.logging import get_handlers
from cosema.pipelines.runner import run_pipeline
from cosema.pipelines.scheduler_bootstrap import build_clients, start_scheduler

handlers = get_handlers(log_path="logs/initial_calculations.log")
logging.basicConfig(level=logging.INFO, handlers=handlers)

logger = logging.getLogger(__name__)

# how much time to go back in time to download data
INITIAL_DATE_OFFSET = pd.Timedelta("1h")
# time delta for the calculations
TIME_DELTA = pd.Timedelta("24h")
# when to start the scheduler for the first time
FIRST_RUN_OFFSET = pd.Timedelta(minutes=15)
# how often to run the scheduler [in hours]
TASK_INTERVAL = 1


def init_date(initial_date):
    global timestep
    timestep = initial_date.tz_convert("UTC")
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
        # Redundant since 2026-08-28: query_per_type_gen/query_demand_data/
        # query_cross_border_flows now read live from OEDS's entsoe_raw
        # schema instead of what these downloads used to write into our own
        # schema (see cosema/input_output/influxdb.py). Left disabled rather
        # than removed -- the flags/downloads themselves still work, just
        # unneeded given the current data source.
        download_per_type=False,
        download_demand=False,
        download_cross_border=False,
        parallel_downloads=True,
        run_regionalization=True,
        run_intensities=True,
        reg_mode="only_per_type",
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

    if first_run is None:
        first_run = (
            pd.Timestamp("now", tz="Europe/Berlin").round("h") + FIRST_RUN_OFFSET
        )

    else:
        first_run = pd.Timestamp(first_run, tz="Europe/Berlin")

    if initial_date is None:
        initial_date = first_run.round("h") - INITIAL_DATE_OFFSET
    else:
        initial_date = pd.Timestamp(initial_date, tz="UTC")

    tasks_interval = TASK_INTERVAL if tasks_interval is None else tasks_interval

    time_delta = (
        TIME_DELTA if time_delta is None else pd.Timedelta(f"{time_delta}h", tz="UTC")
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
        job_name="initial_calculations",
        first_run=first_run,
        tasks_interval=tasks_interval,
        misfire_grace_time=15 * 60,
        max_instances=4,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Script to initialize the scheduler for initial data downloads and intensity calculations."
    )

    parser.add_argument(
        "-st",
        "--start_date",
        type=str,
        required=False,
        help="A starting date for the scheduler in Y-m-d-H:M format.",
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
        help="An optional argument to set the interval between tasks [in hours]. 1h by default.",
    )

    parser.add_argument(
        "-d",
        "--time_delta",
        type=str,
        required=False,
        help="An optional argument to set the time delta for the calculation [in hours]. 1d by default.",
    )

    args = parser.parse_args()

    main(
        initial_date=args.start_date,
        first_run=args.first_run,
        tasks_interval=args.tasks_interval,
        time_delta=args.time_delta,
    )
