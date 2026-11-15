"""
Emission factor of Hydro Pumped Storage: mean CO2 intensity of the
electricity used for pumping (weighted by the pumped energy, per state and
for Germany), divided by the round-trip efficiency (0.8, see the estimate
below). Run about once a year (January/February) for the finished year.

Reads reg_generation (balanced "Storage", negative = charging) and
co2_intensity (consumption) from the DB, and the current emission factors
from cosema_inputs.gen_types_and_emission_factors. Writes a full copy of that
table as CSV with the new values; the DB itself is not changed. Upload the
CSV via "Transfer data to database/transfer_generation_data.py"
(GENERATION_DATA_DIR = folder of the CSV, file name as written here).

Units: co2_intensity is in g/kWh, the emission factors are in t/MWh
(= kg/kWh; calc_intensities.py multiplies by 1000), so the result is
divided by 1000 before it's written.

Columns: year_{year} for every --years entry, plus year_{last year + 1}
with the same value (the map falls back to the previous year only one year
back). A year column that doesn't exist yet is first filled with the latest
existing year for all other technologies -- otherwise they'd get NaN there.

Fixed 2026-11-15: keys.yaml -> build_db_client(), column "mean" ->
"Intensity [g/kWh]", g/kWh -> t/MWh, years as argument, CSV written again,
per-state result columns. Only the German mean is written; the former
per-state rows ("Hydro Pumped Storage BW", ...) were dropped, nothing reads
them and they'd show up as extra technologies.

Usage (from co2map/):
    python -m scripts.calc_hps_intensities --years 2025
    python -m scripts.calc_hps_intensities --years 2024 2025 --out outputs/ef/gen_types_and_emission_factors.csv
"""
import argparse
import os

import numpy as np
import pandas as pd

from cosema.input_output.db_engine import INPUTS_SCHEMA, get_engine
from cosema.regions import BUSES

EFFICIENCY = 0.8
TECHNOLOGY = "Storage"  # balanced reg_generation: one column for all storage
HPS_ROW = "Hydro Pumped Storage"

# -------------------------------------------------
# Estimate efficiency of Hydro Pumped Storage in DE
# -------------------------------------------------

# years = [f"{year}" for year in range(2015, 2026)]

# df = pd.DataFrame(
#     columns=["HPS/Generation", "HPS/Consumption", "HPS/Factor"], index=years
# )

# for year in years:
#     DE_production = pd.read_csv(f"inputs/hps/DE_Production_{year}.csv")

#     con = df.loc[year, "HPS/Consumption"] = DE_production[
#         "Hydro Pumped Storage  - Actual Consumption [MW]"
#     ].sum()
#     gen = df.loc[year, "HPS/Generation"] = DE_production[
#         "Hydro Pumped Storage  - Actual Aggregated [MW]"
#     ].sum()

#     fac = df.loc[year, "HPS/Factor"] = (
#         df.loc[year, "HPS/Generation"] / df.loc[year, "HPS/Consumption"]
#     )

#     print(
#         f" {year} ->     Yearly factor: {fac:.3f}     " + f"( {gen} MWh / {con} MWh )"
#     )

# con = df["HPS/Consumption"].sum()
# gen = df["HPS/Generation"].sum()
# fac = gen / con

# df.loc["Total"] = (gen, con, fac)

# print(f"Total ->      Total factor: {fac:.3f}     " + f"( {gen} MWh / {con} MWh )")

# print()
# print("Result: about 0.8 -> use 0.8 as the efficiency")
# print()



# -----------------------------------------------
# Calculate mean intensity of charged electricity
# -----------------------------------------------


def charge_intensities(db_client, years, mode="with_per_unit"):
    """Mean intensity (g/kWh) of the pumped (charging) electricity per year,
    per state and "Total" (Germany, weighted by charged energy)."""
    intensities = pd.DataFrame(index=years, columns=BUSES + ["Total"], dtype=float)

    for year in years:
        start = pd.Timestamp(f"{year}-01-01 00:00", tz="UTC")
        end = pd.Timestamp(f"{year}-12-31 23:59", tz="UTC")
        emissions = 0.0
        charge = 0.0

        for state in BUSES:
            print(f"Calculating {year} - {state}...")
            df_gen = db_client.query_reg_gen_data(
                start, end, state=state, mode=mode, technologies=[TECHNOLOGY], balanced=True
            )
            if df_gen.empty or df_gen[TECHNOLOGY].sum() == 0:
                print(f"No storage data for {state} in {year}, skipping...")
                continue

            charging = df_gen[TECHNOLOGY].clip(upper=0)  # MW, negative
            df_int = db_client.query_intensities(
                start, end, state=state, emission_type="consumption", mode=mode
            )
            intensity = df_int["Intensity [g/kWh]"].reindex(charging.index)
            missing = int((intensity.isna() & (charging < 0)).sum())
            if missing:
                print(f"  {missing} charging hours without intensity in {state}, left out")
            used = intensity.notna()

            local_emissions = (intensity[used] * charging[used]).sum()
            local_charge = charging[used].sum()
            if local_charge != 0:
                intensities.loc[year, state] = local_emissions / local_charge
            emissions += local_emissions
            charge += local_charge

        intensities.loc[year, "Total"] = emissions / charge if charge != 0 else np.nan

    return intensities


# ----------------------------------
# Write to emission factors csv file
# ----------------------------------


def updated_emission_factors(emission_factors, factors_t_per_mwh, years):
    """Copy of the emission factor table with the HPS row set for every year
    in years and for the year after the last one."""
    ef = emission_factors.copy()
    year_cols = sorted(c for c in ef.columns if c.startswith("year_"))
    targets = {f"year_{y}": factors_t_per_mwh[y] for y in years}
    targets[f"year_{int(years[-1]) + 1}"] = factors_t_per_mwh[years[-1]]

    for col in sorted(targets):
        if col not in ef.columns:
            earlier = [c for c in year_cols if c < col]
            if not earlier:
                raise ValueError(f"No earlier year column to fill {col} from")
            ef[col] = ef[earlier[-1]]
            year_cols = sorted(year_cols + [col])
        if np.isnan(targets[col]):
            print(f"No result for {col}, keeping {ef.loc[HPS_ROW, col]}")
            continue
        ef.loc[HPS_ROW, col] = targets[col]

    # keep the year columns in order after the other columns
    return ef[[c for c in ef.columns if not c.startswith("year_")] + year_cols]


def main():
    parser = argparse.ArgumentParser(description="Emission factor of Hydro Pumped Storage")
    parser.add_argument("--years", nargs="+", required=True, help="finished years, e.g. 2025")
    parser.add_argument("--mode", default="with_per_unit", help="co2_intensity/reg_generation mode")
    parser.add_argument(
        "--out",
        default="outputs/emission_factors/gen_types_and_emission_factors.csv",
        help="CSV to write (default: %(default)s)",
    )
    args = parser.parse_args()
    years = sorted(args.years)

    from cosema.pipelines.scheduler_bootstrap import build_db_client

    db_client = build_db_client()
    intensities = charge_intensities(db_client, years, mode=args.mode)

    print("\nMean intensity of charged electricity [g/kWh]:")
    print(intensities.round(1))
    discharged = intensities / EFFICIENCY
    print(f"\nEstimated mean intensity of discharged electricity [g/kWh] (efficiency {EFFICIENCY}):")
    print(discharged.round(1))

    factors = (discharged["Total"] / 1000).round(3).to_dict()  # g/kWh -> t/MWh
    emission_factors = pd.read_sql(
        f'SELECT * FROM "{INPUTS_SCHEMA}".gen_types_and_emission_factors', get_engine()
    ).set_index("entsoe")
    ef = updated_emission_factors(emission_factors, factors, years)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    ef.to_csv(args.out)
    print(f"\n{HPS_ROW} before -> after [t/MWh]:")
    print(pd.DataFrame({"before": emission_factors.loc[HPS_ROW], "after": ef.loc[HPS_ROW]}))
    print(f"\nWritten {args.out} -- upload with transfer_generation_data.py")


if __name__ == "__main__":
    main()
