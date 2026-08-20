"""
Shared pipeline logic, used by scripts/manual_runs.py,
schedulers/initial_calculations.py, and schedulers/updated_calculations.py.

Before this module existed, all three scripts duplicated almost the same
sequence (downloads -> VRE -> regionalization -> intensities), just with
different time windows / toggles / modes. Each script is now a thin wrapper
that calls `run_pipeline()` with the flags matching its previous behavior --
see modularization_docs/modularisierung_zielstruktur.md (Schritt 6).

Note: downloads are independent of each other (each writes to its own
InfluxDB measurement, none reads another's output), so the order they run in
here does not affect the result -- only whether a step runs before
regionalization/intensities (which DO read what the downloads wrote) matters,
and that ordering is preserved.

schedulers/forecast_calculations.py is NOT covered here -- different
downstream logic (forecast pipeline), out of scope for this modularization
pass, see modularization_docs/modularisierung_zielstruktur.md.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from cosema.calc_intensities import calculate_intensities
from cosema.generation.regional_split import calculate_regionalized_gen_and_demand
from cosema.generation.vre import run_vre_calculations
from cosema.ingestion.entsoe import (
    download_cross_border_flows,
    download_demand_data,
    download_demand_forecast_data,
    download_per_type_data,
    download_per_unit_data,
)

logger = logging.getLogger(__name__)


def run_pipeline(
    start,
    end,
    db_client,
    entsoe_client=None,
    download_per_type=False,
    download_demand=False,
    download_demand_forecast=False,
    download_per_unit=False,
    download_cross_border=False,
    parallel_downloads=False,
    run_vre_historical=False,
    run_vre_forecast=False,
    run_regionalization=False,
    run_intensities=False,
    reg_mode="only_per_type",
):
    """
    Run any combination of download / VRE / regionalization / intensity
    steps for the window [start, end). Every step is opt-in via its flag, so
    callers can reproduce exactly the behavior of the three previously
    separate scripts by only turning on what they used to run.
    """
    downloads = []
    if download_per_type:
        downloads.append(
            (
                download_per_type_data,
                dict(
                    start=start, end=end, entsoe_client=entsoe_client, db_client=db_client
                ),
            )
        )
    if download_demand:
        downloads.append(
            (
                download_demand_data,
                dict(
                    start=start, end=end, entsoe_client=entsoe_client, db_client=db_client
                ),
            )
        )
    if download_cross_border:
        downloads.append(
            (
                download_cross_border_flows,
                dict(
                    start=start, end=end, entsoe_client=entsoe_client, db_client=db_client
                ),
            )
        )

    if parallel_downloads and downloads:
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(fn, **kwargs) for fn, kwargs in downloads]
            for future in futures:
                future.result()
    else:
        for fn, kwargs in downloads:
            fn(**kwargs)

    if download_per_unit:
        download_per_unit_data(
            start=start, end=end, entsoe_client=entsoe_client, db_client=db_client
        )

    if download_demand_forecast:
        download_demand_forecast_data(
            start=start, end=end, entsoe_client=entsoe_client, db_client=db_client
        )

    if run_vre_historical:
        run_vre_calculations(
            start=start, end=end, db_client=db_client, mode="historical", level="federal"
        )

    if run_vre_forecast:
        run_vre_calculations(
            start=start,
            end=end,
            db_client=db_client,
            mode="forecast",
            level="federal",
            overwrite=True,
        )

    if run_regionalization:
        calculate_regionalized_gen_and_demand(
            start=start, end=end, db_client=db_client, mode=reg_mode
        )

    if run_intensities:
        calculate_intensities(start=start, end=end, db_client=db_client, mode=reg_mode)
