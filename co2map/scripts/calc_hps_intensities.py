import numpy as np
import pandas as pd
import yaml

from cosema.input_output.influxdb import DBClient
from cosema.regions import BUSES

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
# load keys.yaml where the database and entsoe keys are stored
with open("keys.yaml", "r") as f:
    keys = yaml.safe_load(f)

db_client = DBClient(
    database_name="cosema",
    username=keys["influxdb"]["username"],
    password=keys["influxdb"]["password"],
)

with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

states = BUSES

years = ["2024", "2025"]
use_balanced = True
technology = "Storage" if use_balanced else ["Hydro Pumped Storage"]

intensities = pd.DataFrame(index=years, data=0.0, columns=([s + "Total" for s in states]), dtype=float)

for year in years:
    start = pd.Timestamp(f"{year}-01-01 00:00", tz="UTC")
    end = pd.Timestamp(f"{year}-12-31 23:59", tz="UTC")

    emissions = 0
    charge = 0

    for state in states:
        print(f"Calculating {year} - {state}...")
        df_gen = db_client.query_reg_gen_data(
            start,
            end,
            state=state,
            technologies=[technology],
            balanced=use_balanced,
        )

        # if there is no storage data for that state/year, skip
        if df_gen.empty or df_gen[technology].sum() == 0:
            print(f"No storage data for {state} in {year}, skipping...")
            intensities.loc[year, state] = 0.0
            continue
    
        df_gen["Charge"] = np.where(df_gen[technology] < 0, df_gen[technology], 0)
        df_gen["Discharge"] = np.where(df_gen[technology] > 0, df_gen[technology], 0)

        # print(f"{state}({year})", df_gen["Discharge"].sum())

        df_int = db_client.query_intensities(
            start, end, state=state, emission_type="consumption", mode="with_per_unit"
        )

        local_emissions = (df_int["mean"] * df_gen["Charge"]).sum()
        local_charge = df_gen["Charge"].sum()

        intensities.loc[year, state] = (
            (local_emissions / local_charge) if local_charge != 0 else np.nan
        )

        emissions += local_emissions
        charge += local_charge

    intensities.loc[year, "Total"] = emissions / charge

intensities = intensities.round(3)

print()
print("Mean intensity of charged electricity:")
print(intensities)
print()


# -------------------------------------------------
# Estimate mean intensity of discharged electricity
# -------------------------------------------------

efficiency = 0.8
intensities = intensities / efficiency
intensities = intensities.round(3)

print()
print("Estimated mean intensity of discharged electricity:")
print(intensities)


# ----------------------------------
# Write to emission factors csv file
# ----------------------------------

write_to_csv = True
write_only_mean = True

emission_factors = pd.read_csv(
    "inputs/generation_data/gen_types_and_emission_factors.csv", index_col="entsoe"
)

if write_only_mean:
    row = {"converted": "Storage"}

    # set historical years
    for year in years:
        row[f"year_{year}"] = intensities.loc[year, "Total"]

    # set next year with last known
    row[f"year_{str(int(years[-1])+1)}"] = intensities.loc[years[-1], "Total"]

    # apply
    emission_factors.loc["Hydro Pumped Storage"] = row

else:
    for state in states:
        row = {"converted": f"Storage {state}"}

        # set historical years
        for year in years:
            row[f"year_{year}"] = (
                intensities.loc[year, "Total"]
                if np.isnan(intensities.loc[year, state])
                else intensities.loc[year, state]
            )

        # set next year with last known
        row[f"year_{str(int(years[-1])+1)}"] = (
            intensities.loc[years[-1], "Total"]
            if np.isnan(intensities.loc[years[-1], state])
            else intensities.loc[years[-1], state]
        )

        # apply
        emission_factors.loc[f"Hydro Pumped Storage {state}"] = row

# save
# emission_factors.to_csv("inputs/generation_data/gen_types_and_emission_factors.csv")
print("Updated emission factors dataframe:")
print(emission_factors)