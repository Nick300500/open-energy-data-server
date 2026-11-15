"""
Calculates the monthly capacity files (conventional per state, VRE per state
and 0.25 degree grid cell) for a range of months, e.g. all months of the
historical runs since 2020. Thin CLI around
cosema/capacities/mastr.py::calculate_total_capacities_for_cosema, which
loads the MaStR once and then loops over the months.

Reads the MaStR and the state shapes from cosema_inputs, so DB_HOST/PORT/
NAME/USER/PASSWORD must point at the OEDS database (env vars or .env, e.g.
through an SSH tunnel when run locally).

A month counts as done once its conv_capacities_{YYYY_MM}.parquet exists
(written last per month), so an aborted run can simply be started again and
continues with the first unfinished month. --overwrite recalculates all.

Usage (from co2map/; -m so that cosema is importable without PYTHONPATH):
    python -m scripts.calc_capacities --start 2020-01 --end 2026-11
    python -m scripts.calc_capacities --start 2020-01 --end 2026-11 --out-dir "C:/path/cap_upload"

Upload afterwards with "Transfer data to database/transfer_capacities.py"
(CAPACITIES_DIR = --out-dir); it replaces only the months it finds there.
"""
import argparse
import logging
import time

import pandas as pd

from cosema.capacities.mastr import calculate_total_capacities_for_cosema
from cosema.logging import get_handlers


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--start", required=True, help="first month, YYYY-MM")
    parser.add_argument("--end", required=True, help="last month (inclusive), YYYY-MM")
    parser.add_argument(
        "--out-dir",
        default="inputs/capacities",
        help="folder for the {YYYY_MM} subfolders (default: inputs/capacities)",
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="recalculate months that already exist"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, handlers=get_handlers(log_path="logs/calc_capacities.log")
    )
    logger = logging.getLogger(__name__)

    start = pd.Period(args.start, freq="M").start_time
    end = pd.Period(args.end, freq="M").end_time.normalize()
    if end < start:
        parser.error("--end is before --start")

    logger.info(f"Calculating capacities {args.start} to {args.end} into {args.out_dir}")
    t0 = time.time()
    calculate_total_capacities_for_cosema(
        start_date=start,
        end_date=end,
        overwrite=args.overwrite,
        out_dir=args.out_dir,
    )
    logger.info(f"Done in {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
