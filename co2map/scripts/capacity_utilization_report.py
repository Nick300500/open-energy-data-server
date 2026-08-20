# %%
"""
Standalone audit report for Mirko: for each raw generation type, how much
installed capacity and generated energy is directly measured (per-unit,
EIC-matched ENTSO-E data) vs. only estimated/distributed (leftover, spread
via capacity-weighted regional factors).

Pure read-only analysis -- does not write anything back to the DB and is
not part of run_pipeline(). Only needs, for the chosen period, that
ingestion (download_per_type_data, download_per_unit_data) and the
conventional capacity calculation (calculate_total_capacities_for_cosema)
have already run.
"""
import os

import pandas as pd
import yaml

from cosema.generation.leftover import calc_leftover_gen_per_type, prepare_gen_per_unit
from cosema.generation.regional_split import get_per_type_data, preprocess_gen_per_unit
from cosema.input_output.influxdb import DBClient

with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

with open("keys.yaml", "r") as f:
    keys = yaml.safe_load(f)

db_client = DBClient(
    database_name="cosema",
    username=keys["influxdb"]["username"],
    password=keys["influxdb"]["password"],
)

# Period must already be ingested (per_type_gen / per_unit_gen in InfluxDB) and
# have conventional capacities computed (inputs/capacities/{month}/...).
start = pd.Timestamp("2026-02-01 00:00", tz="UTC")
end = pd.Timestamp("2026-03-01 00:00", tz="UTC")
month = start.strftime("%Y_%m")

# %% 1. Raw inputs
raw_per_unit_data = db_client.query_per_unit_gen(start=start, end=end)
gen_per_type = get_per_type_data(db_client=db_client, start=start, end=end)  # DE, raw ENTSO-E types

# %% 2. Capacities: total vs. measured (per Bundesland x Type)
gen_per_unit_dict, capacities_used_in_per_unit = preprocess_gen_per_unit(
    raw_per_unit_data, start, end
)

capacity_path = f"inputs/capacities/{month}"
regional_capacities = pd.read_parquet(f"{capacity_path}/conv_capacities_{month}.parquet")

# align the two capacity tables (same Bundesland index, same Type columns)
# before comparing -- capacities_used_in_per_unit only has columns/rows for
# types & states it actually encountered EIC matches for.
capacities_used_in_per_unit = capacities_used_in_per_unit.reindex(
    index=regional_capacities.index, columns=regional_capacities.columns, fill_value=0.0
)
capacity_estimated = (regional_capacities - capacities_used_in_per_unit).clip(lower=0)

# %% 3. Generation: measured vs. estimated ("leftover"), DE-wide per raw type
gen_measured = (
    prepare_gen_per_unit(raw_per_unit_data)
    .groupby(["DateTime", "technology"])
    .sum(numeric_only=True)
    .reset_index()
    .pivot(index="DateTime", columns="technology", values="Generation [MW]")
    .fillna(0.0)
)
gen_estimated = calc_leftover_gen_per_type(raw_per_unit_data, gen_per_type)

# %% 4. Assemble the per-type report (summed over the whole period, DE-wide)
report = pd.DataFrame(
    {
        "capacity_total_MW": regional_capacities.sum(axis=0),
        "capacity_measured_MW": capacities_used_in_per_unit.sum(axis=0),
        "capacity_estimated_MW": capacity_estimated.sum(axis=0),
    }
)

report["generation_measured_MWh"] = gen_measured.reindex(
    columns=report.index, fill_value=0.0
).sum(axis=0)
report["generation_estimated_MWh"] = gen_estimated.reindex(
    columns=report.index, fill_value=0.0
).sum(axis=0)
report["generation_total_MWh"] = (
    report["generation_measured_MWh"] + report["generation_estimated_MWh"]
)

report["share_capacity_measured"] = (
    report["capacity_measured_MW"] / report["capacity_total_MW"]
).fillna(0.0)

hours = (end - start).total_seconds() / 3600
report["capacity_factor_measured"] = report["generation_measured_MWh"] / (
    report["capacity_measured_MW"] * hours
)

report = report.sort_values("capacity_total_MW", ascending=False)

# %% 5. Output
os.makedirs("outputs", exist_ok=True)
report.round(3).to_csv(f"outputs/capacity_utilization_report_{month}.csv")
print(report.round(1))
