# %%
"""
Standalone audit report for Mirko: for each raw generation type, how much
installed capacity and generated energy is directly measured (per-unit,
EIC-matched ENTSO-E data) vs. only estimated/distributed (leftover, spread
via capacity-weighted regional factors).

Pure read-only analysis -- does not write anything back to the DB and is
not part of run_pipeline(). Only needs, for the chosen period, that
ingestion (download_per_type_data, download_per_unit_data) and the
conventional capacity calculation (calculate_total_capacities_for_cosema,
uploaded to cosema_inputs.capacities_conventional) have already run.

DB connection via build_db_client() (DB_* env vars or .env) since
2026-11-15, replacing keys.yaml; capacities read from the DB instead of the
local inputs/capacities/ files, like regional_split.py does.
"""
import os

import pandas as pd

from cosema.generation.leftover import calc_leftover_gen_per_type, prepare_gen_per_unit
from cosema.generation.regional_split import (
    _load_conv_capacities,
    get_per_type_data,
    preprocess_gen_per_unit,
)
from cosema.pipelines.scheduler_bootstrap import build_db_client

db_client = build_db_client()

# Period must already be ingested (per_type_gen / per_unit_gen) and have
# conventional capacities in cosema_inputs.capacities_conventional.
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

regional_capacities = _load_conv_capacities(month)
if regional_capacities.empty:
    raise ValueError(f"No conventional capacities for {month} in capacities_conventional")

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
