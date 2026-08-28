"""
Reconciliation of per-type (aggregate, country-level) generation reports
against per-unit (individual power plant) generation reports: computes the
residual ("leftover") generation not already captured by per-unit data, so
it isn't double-counted once per-unit data is regionalized separately.

Bundled during modularization (2026-07-16) out of per_type_scripts.py
(calc_leftover_gen_per_type) and per_unit_scripts.py (prepare_gen_per_unit,
its only caller) -- see modularization_docs/modularisierung_zielstruktur.md /
modularization_docs/modularisierung_status.md. Note: per_unit_scripts.py's other function,
preprocess_gen_per_unit, is used independently by the regionalization
orchestrator itself (not via this leftover calculation), so it moved to
generation/regional_split.py instead.
"""

import pandas as pd

from cosema.input_output.db_engine import INPUTS_SCHEMA, get_engine

gen_types_df = pd.read_sql(f"SELECT * FROM {INPUTS_SCHEMA}.gen_types_and_emission_factors", get_engine())
ALLOW_NEGATIVE_GENERATION = list(
    gen_types_df[gen_types_df["is_storage"]]["entsoe"].unique()
)


def prepare_gen_per_unit(per_unit_data):
    gen_per_unit = pd.DataFrame()

    temp_df = pd.DataFrame(columns=["technology", "EIC", "Generation [MW]"])

    for keys, values in per_unit_data.items():
        temp = temp_df.copy()
        keys = dict(keys[1])
        eic = keys["EIC"]
        technology = keys["technology"]

        temp["Generation [MW]"] = values["Generation [MW]"]
        temp.loc[:, "technology"] = technology
        temp.loc[:, "EIC"] = eic
        gen_per_unit = pd.concat([gen_per_unit, temp], axis=0)

    gen_per_unit = gen_per_unit.sort_index()
    gen_per_unit.index.name = "DateTime"
    gen_per_unit = gen_per_unit.fillna(0)

    return gen_per_unit


def calc_leftover_gen_per_type(raw_per_unit_data, gen_per_type):
    gen_per_unit = prepare_gen_per_unit(raw_per_unit_data)

    gen_per_unit_grouped = gen_per_unit.groupby(
        ["DateTime", "technology"], as_index=True
    ).sum(numeric_only=True)

    gen_per_unit_grouped = gen_per_unit_grouped.reset_index()
    gen_per_unit_grouped = gen_per_unit_grouped.set_index("DateTime", drop=True)
    gen_per_unit_grouped = gen_per_unit_grouped.fillna(0)

    gen_types_per_unit = gen_per_unit_grouped["technology"].unique()

    leftover_gen_per_type = gen_per_type.copy()

    for gen_type, generation in leftover_gen_per_type.items():
        if gen_type in gen_types_per_unit:
            per_unit = gen_per_unit_grouped.loc[
                gen_per_unit_grouped["technology"] == gen_type, "Generation [MW]"
            ]

            if len(per_unit) != len(generation):
                # add missing hours to per unit data and fill with 0.0
                missing_hours = generation.index.difference(per_unit.index)
                per_unit = per_unit.reindex(generation.index)
                per_unit[missing_hours] = 0.0

            dif = generation - per_unit

            if gen_type not in ALLOW_NEGATIVE_GENERATION:
                dif[dif < 0] = 0.0

            leftover_gen_per_type[gen_type] = dif

    return leftover_gen_per_type
