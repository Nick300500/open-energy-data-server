"""
Reading of reference/input data, as opposed to influxdb.py which handles the
Postgres/entsoe_raw-backed timeseries data.

Started during modularization (2026-07-16) with the demand-regionalization
factors extracted out of demand_scripts.py:reg_demand_data_dynamic. Intended
to also absorb the other scattered file-reads (capacities parquet, cutouts,
...) in later steps -- see modularization_docs/modularisierung_zielstruktur.md.

Redirected to the DB (2026-08-21): demand_reg_factors used to be yearly local
CSVs (inputs/demand_reg_data/demand_reg_factors_{year}.csv), now migrated
into cosema_inputs.demand_reg_factors (see the standalone "Transfer data to
database" scripts, kept outside this repo) and read from there instead.
"""

import pandas as pd

from cosema.input_output.db_engine import INPUTS_SCHEMA, get_engine
from cosema.regions import BUSES


def load_demand_reg_factors(index: pd.DatetimeIndex) -> pd.DataFrame:
    """
    Load the demand regionalization factors from cosema_inputs.demand_reg_factors
    covering the given index, and return the factors aligned to that index.
    """
    engine = get_engine()
    demand_reg_factors_all = pd.read_sql(
        f"SELECT * FROM {INPUTS_SCHEMA}.demand_reg_factors "
        f"WHERE time >= %(start)s AND time <= %(end)s",
        engine,
        params={"start": index.min().to_pydatetime(), "end": index.max().to_pydatetime()},
        index_col="time",
    )
    demand_reg_factors_all.index = pd.to_datetime(demand_reg_factors_all.index, utc=True)
    demand_reg_factors_all = demand_reg_factors_all[
        ~demand_reg_factors_all.index.duplicated(keep="first")
    ]

    # Pre-existing inconsistency in the original source CSVs, found 2026-08-29
    # debugging a real deploy: demand_reg_factors_2019.csv (and the unsuffixed
    # base file it was itself derived from) has 3 extra columns (BE, HB, HH --
    # the city-states) that every later year's file (2020-2026) dropped.
    # cosema/regions.py::BUSES never included those 3 to begin with, so
    # nothing else in this codebase can use them anyway. The old, pre-DB
    # per-year CSV loader never surfaced this (it only ever read the file(s)
    # for the specific requested year, so a 2026 run never touched 2019's
    # file) -- concatenating every year into one DB table exposed it: the
    # combined table has all 16 columns (NaN for BE/HB/HH outside 2019), and
    # reg_demand_data_dynamic's demand_DE.values * reg_factors.values crashed
    # with a (13,) vs (16,) shape mismatch during the fallback path (see
    # get_demand_data(), which hardcodes columns=BUSES) whenever it hit real
    # data gaps. Reindexing to BUSES here -- not just trimming the DB table
    # once -- keeps this correct even if a future upload reintroduces the
    # extra columns.
    demand_reg_factors_all = demand_reg_factors_all.reindex(columns=BUSES)

    return demand_reg_factors_all.loc[index]
