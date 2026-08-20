"""
Shared bootstrap for the production schedulers (schedulers/initial_calculations.py,
schedulers/updated_calculations.py) -- building the DB/ENTSO-E clients and
starting/running/stopping a BackgroundScheduler job. This is deliberately
named differently from the top-level `schedulers/` folder (the actual
long-running production entry points, see schedulers/restart.sh,
stop_all.sh, and the `systemctl co2mapapi` service) to avoid confusing the
two -- this module is just shared plumbing, not an entry point itself.

Deliberately NOT included here: each scheduler's operational parameters
(TASK_INTERVAL, TIME_DELTA, FIRST_RUN_OFFSET, misfire_grace_time,
max_instances), its date-default logic, its CLI argument parsing, and its
`perform_calculations` function. Those differ in meaningful, not just
cosmetic, ways between schedulers and stay individually visible in each
schedulers/*.py file -- this is production-critical scheduling logic, not
boilerplate to hide away.

schedulers/forecast_calculations.py does not use this (different structure).
"""

import time

import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from entsoe import EntsoePandasClient

from cosema.input_output.influxdb import DBClient


def build_clients():
    """
    Load keys.yaml and build the DBClient + EntsoePandasClient shared by all
    schedulers.
    """
    with open("keys.yaml", "r") as f:
        keys = yaml.safe_load(f)

    db_client = DBClient(
        database_name="cosema",
        username=keys["influxdb"]["username"],
        password=keys["influxdb"]["password"],
    )
    # timeout=: without it, a request whose server accepts the connection but
    # never replies hangs forever, bypassing retry_function's retry entirely
    # (see cosema/ingestion/entsoe.py::retry_function) -- observed 2026-07-22/23
    # via manual_runs.py, a cross-border flow request stalled for 3.5h+.
    entsoe_client = EntsoePandasClient(api_key=keys["entsoe-key"], timeout=60)

    return db_client, entsoe_client


def start_scheduler(
    perform_calculations,
    job_kwargs,
    job_name,
    first_run,
    tasks_interval,
    misfire_grace_time,
    max_instances=1,
):
    """
    Register `perform_calculations` as a recurring APScheduler job (every
    `tasks_interval` hours, starting at `first_run`) and block the calling
    thread until interrupted, then shut the scheduler down cleanly.
    """
    scheduler = BackgroundScheduler()

    scheduler.add_job(
        perform_calculations,
        trigger="interval",
        hours=tasks_interval,
        kwargs=job_kwargs,
        name=job_name,
        next_run_time=first_run.to_pydatetime(),
        misfire_grace_time=misfire_grace_time,
        max_instances=max_instances,
    )

    scheduler.start()

    try:
        # This is here to simulate application activity (which keeps the main thread alive).
        while True:
            time.sleep(2)
    except (KeyboardInterrupt, SystemExit):
        # Not strictly necessary if daemonic mode is enabled but should be done if possible
        scheduler.shutdown()
