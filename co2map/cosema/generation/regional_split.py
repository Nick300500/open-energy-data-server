"""
Distribution of country-level (Germany-wide) generation and demand onto
individual Bundesländer (states), using capacity factors (conventional and
VRE) and demand regionalization factors.

Bundled during modularization (2026-07-16) out of regionalization.py
(entirely), per_type_scripts.py (calc_reg_gen_by_type), demand_scripts.py
(reg_demand_data_dynamic), and per_unit_scripts.py (preprocess_gen_per_unit
-- used directly by the orchestrator below, not via the leftover
calculation, see generation/leftover.py for that) -- see
modularization_docs/modularisierung_zielstruktur.md / modularization_docs/modularisierung_status.md.
"""

import logging
import os
import traceback
import warnings

import pandas as pd
import yaml

from cosema.generation.leftover import calc_leftover_gen_per_type
from cosema.input_output.db_engine import INPUTS_SCHEMA, get_engine
from cosema.input_output.influxdb import collect_vre, query_per_type_data
from cosema.input_output.local_files import load_demand_reg_factors
from cosema.regions import BUSES

logger = logging.getLogger(__name__)

warnings.simplefilter(action="ignore", category=FutureWarning)

with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

_gen_types_df = pd.read_sql(f"SELECT * FROM {INPUTS_SCHEMA}.gen_types_and_emission_factors", get_engine())
gen_types = _gen_types_df["entsoe"].unique()

matching_id_EIC = pd.read_sql(f"SELECT * FROM {INPUTS_SCHEMA}.matching_id_bna_eic", get_engine())

entsoe_gen_types = gen_types


def _latest_conv_capacities_period(at_or_before: str):
    """Most recent period in cosema_inputs.capacities_conventional at or
    before the given YYYY_MM period, or None if there's none at all.
    Replaces the old fixed 6-month lookback loop (subtract 30d, retry, up to
    6 times) -- that silently ran out once real data got more than 6 months
    stale, crashing with UnboundLocalError one statement later (found
    2026-08-28: the only period uploaded so far, 2026_02, was one month
    older than 6 months back from the then-current month)."""
    query = (
        f'SELECT period FROM "{INPUTS_SCHEMA}".capacities_conventional '
        "WHERE period <= %(at_or_before)s ORDER BY period DESC LIMIT 1"
    )
    with get_engine().connect() as conn:
        result = pd.read_sql(query, conn, params={"at_or_before": at_or_before})
    return result["period"].iloc[0] if not result.empty else None


def _load_conv_capacities(period: str) -> pd.DataFrame:
    """Conventional per-state capacities (one column per technology) for one
    period, from cosema_inputs.capacities_conventional -- replaces the old
    pd.read_parquet(check_path) call. Same shape as the old parquet file:
    indexed by state, one column per technology."""
    query = f'SELECT * FROM "{INPUTS_SCHEMA}".capacities_conventional WHERE period = %(period)s'
    df = pd.read_sql(query, get_engine(), params={"period": period})
    return df.drop(columns=["period"]).set_index("state")


def preprocess_gen_per_unit(per_unit_data, start, end):
    global matching_id_EIC

    gen_per_unit_df = pd.DataFrame()
    gen_per_unit_info = {}
    # bna_used = []

    # a dataframe where columns are technology and index is states filled with 0
    capacities_used_in_per_unit = pd.DataFrame(
        index=BUSES,
        columns=entsoe_gen_types,
        data=0.0,
    )

    # inclusive="left": per-unit data covers the half-open interval [start, end)
    # (e.g. 672 hourly points for a 28-day month) -- date_range's default
    # (inclusive on both ends) would be off by one, so len(temp) == len(index)
    # below would never match and no per-unit capacity would ever get credited.
    index = pd.date_range(start=start, end=end, freq="H", inclusive="left")

    for keys, values in per_unit_data.items():
        keys = dict(keys[1])
        eic = keys["EIC"]
        technology = keys["technology"]
        state = matching_id_EIC.loc[matching_id_EIC["eic_code_block"] == eic, "state"]

        if len(state) == 0:
            logger.warning(f"Missing EIC: {eic}! Please update the matching_id_EIC.csv")

            # Moved from inputs/generation_data/ to logs/ (2026-08-29):
            # inputs/ is now a read-only bind mount (weather cutouts + PyPSA
            # reference network, see compose.yml), so writing here isn't just
            # a matter of the old directory no longer existing -- it would
            # fail outright even if created.
            missing_eic_path = "logs/missing_eic.txt"
            os.makedirs(os.path.dirname(missing_eic_path), exist_ok=True)
            if not os.path.exists(missing_eic_path):
                with open(missing_eic_path, "w") as f:
                    pass  # Create the file if it doesn't exist

            # Open missing_eic.txt and append EIC if not already in there
            with open(missing_eic_path, "r+") as f:
                if eic not in f.read():
                    f.write(f"{eic}\n")

            continue

        state = state.iloc[0]

        if state == "missing":
            continue

        temp = pd.DataFrame(columns=[eic])
        temp[eic] = values["Generation [MW]"]
        if len(temp) == 1:
            continue

        if len(temp) == len(index):
            capacity = matching_id_EIC.loc[
                matching_id_EIC["eic_code_block"] == eic, "capacity"
            ].values[0]
            capacities_used_in_per_unit.loc[state, technology] += capacity

        gen_per_unit_df = pd.concat([gen_per_unit_df, temp], axis=1)
        gen_per_unit_info[eic] = {"bus": state, "carrier": technology}

    # sum columns with same name in gen_per_unit_df
    gen_per_unit_df = gen_per_unit_df.groupby(gen_per_unit_df.columns, axis=1).sum()
    gen_per_unit_df = gen_per_unit_df.fillna(0)

    gen_per_unit_info = pd.DataFrame(gen_per_unit_info).T
    gen_per_unit_dict = {"gen": gen_per_unit_df, "info": gen_per_unit_info}

    # remove all columns with only 0 from capacities_used_in_per_unit
    capacities_used_in_per_unit = capacities_used_in_per_unit.loc[
        :, (capacities_used_in_per_unit != 0).any(axis=0)
    ]

    return gen_per_unit_dict, capacities_used_in_per_unit


def calc_reg_gen_by_type(
    gen_per_type, reg_cap_factors, solar_cf, onshore_cf, offshore_cf
):
    index = gen_per_type.index
    reg_gen_by_type = pd.DataFrame()

    # create  list with all original energy types from gen_per_type.columns
    # and conv_cap_factors.index
    energy_types = gen_per_type.columns.tolist()
    energy_types.extend(reg_cap_factors.columns.tolist())
    energy_types = list(set(energy_types))

    for energy_type in energy_types:
        if energy_type in gen_per_type.columns:
            temp = gen_per_type[energy_type]

            if energy_type in reg_cap_factors.columns and energy_type not in [
                "Solar",
                "Wind Onshore",
                "Wind Offshore",
            ]:
                cap_factor = pd.DataFrame(
                    index=index, columns=reg_cap_factors.index, data=0.0
                )
                cap_factor += reg_cap_factors[energy_type]
                temp = cap_factor.mul(temp, axis=0)

            elif energy_type == "Solar":
                temp = solar_cf.mul(temp, axis=0)

            elif energy_type == "Wind Onshore":
                temp = onshore_cf.mul(temp, axis=0)

            elif energy_type == "Wind Offshore":
                temp = offshore_cf.mul(temp, axis=0)

            else:
                temp = pd.DataFrame(index=index, columns=BUSES, data=0.0)

        else:
            temp = pd.DataFrame(index=index, columns=BUSES, data=0.0)

        temp = temp.add_suffix(f"_{energy_type}")

        reg_gen_by_type = pd.concat([reg_gen_by_type, temp], axis=1)

    return reg_gen_by_type


def reg_demand_data_dynamic(demand_DE):
    reg_factors = load_demand_reg_factors(demand_DE.index)

    # Calculate the regionalized demand
    reg_demand_DE = demand_DE.values * reg_factors.values
    reg_demand_DE = pd.DataFrame(
        columns=reg_factors.columns, index=demand_DE.index, data=reg_demand_DE
    )

    return reg_demand_DE


def get_per_type_data(
    db_client,
    start: pd.Timestamp,
    end: pd.Timestamp,
):
    logger.debug("Quering per type generation data for DE...")
    try:
        gen_per_type = query_per_type_data(
            start=start,
            end=end,
            db_client=db_client,
            countries=["DE"],
        )

        # remove upper level column
        gen_per_type.columns = gen_per_type.columns.droplevel(0)

    except Exception as e:
        error = traceback.format_exc().splitlines()[-1]
        logger.error(
            f"Critical error {error}! No per type data for DE for period {start} - {end}. Using blank data..."
        )
        index = pd.date_range(start=start, end=end, freq="1h", tz=start.tz)
        gen_per_type = pd.DataFrame(index=index, columns=gen_types, data=0.0)

    return gen_per_type


def get_vre_data(
    db_client,
    start: pd.Timestamp,
    end: pd.Timestamp,
    mode: str = "historical" or "forecast",
):
    logger.debug("Quering VRE capacity factors...")
    try:
        solar_cf, onshore_cf, offshore_cf = collect_vre(
            start=start,
            end=end,
            db_client=db_client,
            mode=mode,
            value="reg_factor",
        )

    except Exception as e:
        error = traceback.format_exc().splitlines()[-1]
        logger.error(
            f"Critical error {error}! No VRE data for period {start} - {end}. Using blank data..."
        )
        index = pd.date_range(start=start, end=end, freq="1h", tz=start.tz)
        solar_cf = pd.DataFrame(index=index, columns=BUSES, data=0.0)
        onshore_cf = pd.DataFrame(index=index, columns=BUSES, data=0.0)
        offshore_cf = pd.DataFrame(index=index, columns=BUSES, data=0.0)

    return solar_cf, onshore_cf, offshore_cf


def get_demand_data(
    db_client,
    start: pd.Timestamp,
    end: pd.Timestamp,
):
    # Prepare demand data
    logger.debug("Preparing demand data...")

    try:
        demand_DE = db_client.query_demand_data(
            start=start,
            end=end,
            country="DE",
        )

    except Exception as e:
        error = traceback.format_exc().splitlines()[-1]
        logger.error(
            f"Critical error {error}! No demand data for period {start} - {end}. Using blank data..."
        )
        index = pd.date_range(start=start, end=end, freq="1h", tz=start.tz)
        demand_DE = pd.DataFrame(index=index, columns=BUSES, data=0.0)

    return demand_DE


def calculate_regionalized_gen_and_demand(
    start: pd.Timestamp,
    end: pd.Timestamp,
    db_client,
    mode: str = "only_per_type" or "with_per_unit",
    extra_tags: dict = None,
):
    if mode == "with_per_unit":
        available_gen_per_unit = db_client.check_per_unit_data(start=start, end=end)
        new_end = available_gen_per_unit[-1]
        if end != new_end:
            logger.warning(
                f"Per unit data is not available until {end}, using data until {new_end}"
            )
        end = new_end

    gen_per_unit_dict = None

    # Prepare power plants list and generation per unit
    logger.debug("Reading power plants list...")

    gen_per_type = get_per_type_data(db_client=db_client, start=start, end=end)

    # Prepare generation per unit data
    if mode == "with_per_unit":
        logger.debug("Preparing generation per unit data...")
        raw_per_unit_data = db_client.query_per_unit_gen(start=start, end=end)

        gen_per_unit_dict, capacities_used_in_per_unit = preprocess_gen_per_unit(
            raw_per_unit_data, start, end
        )

        gen_per_type = calc_leftover_gen_per_type(
            raw_per_unit_data=raw_per_unit_data, gen_per_type=gen_per_type
        )

    vre_mode = "historical" if mode == "with_per_unit" else "forecast"
    solar_cf, onshore_cf, offshore_cf = get_vre_data(
        db_client=db_client,
        start=start,
        end=end,
        mode=vre_mode,
    )

    logger.debug("Calculating regional capacity factors...")

    month = start.strftime("%Y_%m")

    latest_period = _latest_conv_capacities_period(month)
    if latest_period is None:
        raise RuntimeError(
            f"No conventional capacities found in {INPUTS_SCHEMA}.capacities_conventional "
            f"at or before {month}"
        )
    if latest_period != month:
        logger.warning(
            f"Conventional capacities for {month} not found. Using latest available: {latest_period}."
        )
    else:
        logger.info(f"Found conventional capacities for {month}. Using them for calculations.")
    regional_capacities = _load_conv_capacities(latest_period)

    # remove columns from regional_capacities which are not in gen_types
    columns_to_remove = list(set(regional_capacities.columns) - set(gen_types))
    regional_capacities = regional_capacities.drop(columns=columns_to_remove)

    if mode == "with_per_unit":
        # substract capacities used in per unit from regional capacities
        regional_capacities = regional_capacities.sub(
            capacities_used_in_per_unit
        ).fillna(regional_capacities)
        # remove negative values
        regional_capacities[regional_capacities < 0] = 0

    # calculate regional capacity factors by normalizing per row
    reg_cap_factors = regional_capacities.div(regional_capacities.sum(axis=0), axis=1)
    # remove nan values
    reg_cap_factors = reg_cap_factors.fillna(0)

    logger.debug("Calculating regional per type generation...")
    reg_gen_by_type = calc_reg_gen_by_type(
        gen_per_type=gen_per_type,
        reg_cap_factors=reg_cap_factors,
        solar_cf=solar_cf,
        onshore_cf=onshore_cf,
        offshore_cf=offshore_cf,
    )

    demand_DE = get_demand_data(
        db_client=db_client,
        start=start,
        end=end,
    )
    reg_demand_DE = reg_demand_data_dynamic(demand_DE)

    # iterate over gen_per_unit data and assign to reg_gen_by_type by state and technology
    if mode == "with_per_unit":
        for _, row in gen_per_unit_dict["info"].iterrows():
            state = row["bus"]
            carrier = row["carrier"]
            reg_gen_by_type[f"{state}_{carrier}"] += gen_per_unit_dict["gen"][row.name]

    # check if total regionalized generation per technology is equal the initial total generation per technology
    # if not, raise a warning
    # NOTES:
    # 1: Hydro Water reservoir has a mismatch due to multiple nehative values in the initial data which are
    # set to 0 during processing
    # 2: Nuclear doesn't typically match because per unit data if not equal to the per type data
    # and all nuclear is in per_unit, which we trust more
    # 3. Hard coal has a mitmatch because per unit data is usually larger than per type data and we trust
    # per unit data more
    # 4. Fossil gas has a mismatch because coal-derived gas is not included in per type data
    for gen_type in gen_types:
        if gen_type in gen_per_type.columns:
            total_reg_gen = reg_gen_by_type.filter(regex=f"{gen_type}$").sum(axis=1)
            difference = abs(total_reg_gen - gen_per_type[gen_type])
            if (difference > 100).any():
                logger.warning(
                    f"Total regionalized generation for {gen_type} is not equal to initial total generation!"
                )

    # fill nan values with 0
    reg_gen_by_type = reg_gen_by_type.fillna(0)
    reg_demand_DE = reg_demand_DE.fillna(0)

    db_client.write_reg_demand_data(
        df=reg_demand_DE, balanced=False, extra_tags=extra_tags
    )
    db_client.write_reg_generation_data(
        df=reg_gen_by_type, mode=mode, balanced=False, extra_tags=extra_tags
    )

    logger.info(
        f"Regionalized generation and demand written to the database, period {start}-{end}."
    )
