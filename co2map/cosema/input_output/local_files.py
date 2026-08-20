"""
Reading of reference/input data files from local disk (CSV/Parquet/NetCDF),
as opposed to influxdb.py which handles the InfluxDB-backed data.

Started during modularization (2026-07-16) with the demand-regionalization
factors extracted out of demand_scripts.py:reg_demand_data_dynamic. Intended
to also absorb the other scattered file-reads (capacities parquet, cutouts,
...) in later steps -- see modularization_docs/modularisierung_zielstruktur.md.
"""

import pandas as pd


def load_demand_reg_factors(index: pd.DatetimeIndex) -> pd.DataFrame:
    """
    Load and concatenate the yearly demand regionalization factor CSVs
    (inputs/demand_reg_data/demand_reg_factors_{year}.csv) covering the
    given index, and return the factors aligned to that index.
    """
    years = sorted(set(index.year))

    demand_reg_factors_all = pd.DataFrame()

    for year in years:
        yearly_factors = pd.read_csv(
            f"inputs/demand_reg_data/demand_reg_factors_{year}.csv", index_col=0
        )
        yearly_factors.index = pd.to_datetime(yearly_factors.index, utc=True)
        demand_reg_factors_all = pd.concat([demand_reg_factors_all, yearly_factors])

    demand_reg_factors_all = demand_reg_factors_all[
        ~demand_reg_factors_all.index.duplicated(keep="first")
    ]

    return demand_reg_factors_all.loc[index]
