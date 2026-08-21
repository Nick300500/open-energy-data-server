# -*- coding: utf-8 -*-
"""
Variable renewable energy (VRE: solar, wind onshore, wind offshore) generation
calculation via atlite (weather-based simulation).

Bundled during modularization (2026-07-16) out of vre_scripts.py (atlite
plumbing: cutouts, shapes, per-technology generation) and calc_vre.py (the
orchestrator, run_vre_calculations) -- see modularization_docs/modularisierung_zielstruktur.md
/ modularization_docs/modularisierung_status.md.

Original calc_vre.py header:
Created on Thu Oct 25 14:45:26 2022
@author: Tim Fürmann
Version: 1.0
Description: This is the main file for calculating the generation of the renewable
powerplants (Solar,Onshore,Offshore) in Germany for the year 2021 in the spatial
resolution of the federal states.
"""
import logging
import os

import geopandas as gp
import numpy as np
import pandas as pd
import shapely
import yaml

from cosema.input_output.db_engine import INPUTS_SCHEMA, get_engine
from cosema.regions import OFFSHORE_STATES

import Vendor.atlite as at

logging.getLogger("atlite").setLevel(logging.ERROR)
logging.getLogger("open_mastr").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

nuts2_to_state = config["nuts2_to_state"]
nuts2_to_state = {k[3:]: v[3:] for k, v in nuts2_to_state.items()}

# cosema_inputs.shapefile_states, migrated there via the standalone "Transfer
# data to database" scripts (originally inputs/shapefiles/states.geojson).
regions = gp.read_postgis(
    f'SELECT * FROM "{INPUTS_SCHEMA}".shapefile_states', get_engine(), geom_col="geometry"
)

x1, y1 = regions.bounds[["minx", "miny"]].min(axis=0).tolist()
x2, y2 = regions.bounds[["maxx", "maxy"]].max(axis=0).tolist()

grid = {
    "dx": 0.25,
    "dy": 0.25,
    "x": [x1, x2],
    "y": [y1, y2],
}


def get_borders_federal():
    """German federal-state borders, from cosema_inputs.shapefile_states
    (migrated there via the standalone "Transfer data to database" scripts)."""

    df = gp.read_postgis(
        f'SELECT * FROM "{INPUTS_SCHEMA}".shapefile_states', get_engine(), geom_col="geometry"
    )
    polygons = df[["NUTS_ID", "geometry"]].set_index("NUTS_ID")

    # match NUTS_ID to state abbreviation
    polygons.index = polygons.index.map(nuts2_to_state)

    polygons["geometry"] = shapely.make_valid(polygons["geometry"])

    return polygons


def _vre_capacities_exist(period: str, technology: str, state: str) -> bool:
    """Whether cosema_inputs.capacities_vre has rows for the given period/
    technology/state -- replaces the old os.path.isfile(check_path) probe
    now that capacities come from the DB (see the standalone "Transfer data
    to database" scripts) instead of local parquet files."""
    query = (
        f'SELECT 1 FROM "{INPUTS_SCHEMA}".capacities_vre '
        "WHERE period = %(period)s AND technology = %(technology)s AND state = %(state)s "
        "LIMIT 1"
    )
    with get_engine().connect() as conn:
        result = pd.read_sql(
            query, conn, params={"period": period, "technology": technology, "state": state}
        )
    return not result.empty


def _load_vre_capacity(technology: str, state: str, period: str) -> gp.GeoDataFrame:
    """Per-plant VRE capacities (x, y, Capacity, geometry) for one technology/
    state/period, from cosema_inputs.capacities_vre -- replaces the old
    gp.read_parquet(local_capacity_path) call."""
    query = (
        f'SELECT x, y, "Capacity", geometry FROM "{INPUTS_SCHEMA}".capacities_vre '
        "WHERE period = %(period)s AND technology = %(technology)s AND state = %(state)s"
    )
    return gp.read_postgis(
        query,
        get_engine(),
        geom_col="geometry",
        params={"period": period, "technology": technology, "state": state},
    )


# cutouts
def create_cutout(path, grid, time, module="meteo", features="all"):
    cutout = at.Cutout(
        path=path,
        module=module,
        x=slice(grid["x"][0] - grid["dx"], grid["x"][1] + grid["dx"]),
        y=slice(grid["y"][0] - grid["dy"], grid["y"][1] + grid["dy"]),
        time=slice(time["start"], time["end"]),
    )

    cutout.prepare(features=features)

    if "expver" in cutout.data.coords:
        cutout.data = cutout.data.reduce(np.nansum, dim="expver", keep_attrs=True)

    return cutout


def select_cutout(cutout, path, grid, time):
    if abs(grid["x"][0] - grid["dx"] - (grid["x"][1] + grid["dx"])) < 0.5:
        a = (cutout.data.x.values < grid["x"][0]) * cutout.data.x.values
        grid["x"][0] = np.max(a[np.nonzero(a)])
        a = (cutout.data.x.values > grid["x"][1]) * cutout.data.x.values
        grid["x"][1] = np.min(a[np.nonzero(a)])

    if abs(grid["y"][0] - grid["dy"] - (grid["y"][1] + grid["dy"])) < 0.5:
        a = (cutout.data.y.values < grid["y"][0]) * cutout.data.y.values
        grid["y"][0] = np.max(a[np.nonzero(a)])
        a = (cutout.data.y.values > grid["y"][1]) * cutout.data.y.values
        grid["y"][1] = np.min(a[np.nonzero(a)])

        cutout = cutout.sel(
            path=path,
            x=slice(grid["x"][0] - grid["dx"], grid["x"][1] + grid["dx"]),
            y=slice(grid["y"][0] - grid["dy"], grid["y"][1] + grid["dy"]),
            time=slice(time["start"], time["end"]),
        )
    return cutout


def renewable_generation(
    technology, local_capacity, shape_file, time, cutout_path, cutout
):
    x1, y1, x2, y2 = shape_file.bounds
    grid = {
        "dx": 0.25,
        "dy": 0.25,
        "x": [x1, x2],
        "y": [y1, y2],
    }

    cutout = select_cutout(cutout=cutout, path=cutout_path, grid=grid, time=time)

    # add identifier bus and state to the data based on the nearest bus of each powerplant
    layout = cutout.layout_from_capacity_list(local_capacity, col="Capacity")

    # calculate generation and capacity factors for 'Solar', 'Onshore' and 'Offshore'
    if technology == "solar":
        generation = cutout.pv(
            panel="CSi",
            orientation={"slope": 30.0, "azimuth": 180.0},
            shapes=[shape_file],
            layout=layout,
            show_progress=False,
        )
    if technology == "wind_onshore":
        generation = cutout.wind(
            turbine="Vestas_V112_3MW",
            shapes=[shape_file],
            layout=layout,
            show_progress=False,
        )
    if technology == "wind_offshore":
        generation = cutout.wind(
            turbine="NREL_ReferenceTurbine_5MW_offshore",
            layout=layout,
            show_progress=False,
        )

    generation = generation.to_dataframe()
    generation = generation.reset_index(level=[1])
    generation = generation.drop("dim_0", axis=1)

    return generation


def run_vre_calculations(
    start: pd.Timestamp,
    end: pd.Timestamp,
    db_client,
    mode: str = "forecast" or "historical",
    level: str = "federal" or "nuts3",
    overwrite: bool = False,
):
    if pd.Timestamp("now", tz="UTC") - start < pd.Timedelta("7d"):
        era_start_date = (start - pd.Timedelta("7d")).strftime("%Y-%m-%d %H:%M")
    else:
        era_start_date = start.strftime("%Y-%m-%d %H:%M")

    era_end_date = end.strftime("%Y-%m-%d %H:%M")

    time = {"start": era_start_date, "end": era_end_date}

    module = "meteo_hist" if mode == "historical" else "meteo"
    features = "all"
    month = start.strftime("%Y_%m")
    files_daterange = f"{start.strftime('%Y_%m_%d')}_{end.strftime('%m_%d')}"

    cutout_path = f"./inputs/cutouts/{month}"
    cutout_file_path = f"{cutout_path}/cutout_{files_daterange}_{mode}.nc"
    if not os.path.exists(cutout_path):
        os.makedirs(cutout_path)

    shapes = get_borders_federal()

    # check if cutout already exists and delete if overwrite is set to True
    if os.path.isfile(cutout_file_path) and overwrite:
        os.remove(cutout_file_path)

    logger.info(f"Creating cutout for {start}-{end} using {module} module")
    cutout_GER = create_cutout(
        path=cutout_file_path,
        grid=grid,
        time=time,
        module=module,
        features=features,
    )
    logger.info(f"Sucessfully created cutout for {start}-{end}")

    month = start.strftime("%Y_%m")

    attempt = 0
    max_attempts = 6

    while attempt < max_attempts:
        if _vre_capacities_exist(month, "solar", "BW"):
            logger.info(f"Found VRE capacities for {month}. Using them for calculations.")
            break  # Found the period; exit loop.
        else:
            logger.warning(
                f"VRE capacities for {month} not found. Using values from last months."
            )
            # Subtract ~1 month (30 days) from `start`, then recalc `month`
            start = start - pd.Timedelta("30d")
            month = start.strftime("%Y_%m")
            attempt += 1

    for technology in ["solar", "wind_onshore", "wind_offshore"]:
        generation_df = pd.DataFrame()
        for idx, _ in shapes.iterrows():
            identifier = (
                shapes.loc[idx].name if level == "federal" else shapes.loc[idx].NUTS_ID
            )
            if technology == "wind_offshore" and identifier not in OFFSHORE_STATES:
                continue

            local_capacity = _load_vre_capacity(technology, identifier, month)
            local_capacity["geometry"] = shapely.make_valid(local_capacity["geometry"])

            local_shape = shapes.loc[idx]["geometry"]

            generation = renewable_generation(
                technology=technology,
                local_capacity=local_capacity,
                shape_file=local_shape,
                time=time,
                cutout_path=cutout_file_path,
                cutout=cutout_GER,
            )

            generation.index = generation.index - pd.Timedelta("1h")
            # rename column specific generation to identifier
            generation.rename(columns={generation.columns[0]: identifier}, inplace=True)
            generation_df = pd.concat([generation_df, generation], axis=1)

            # skip writing to the satabase if the data is faulty, for example contains only zeros
            if generation.sum().sum() == 0:
                logger.warning(
                    f"Generation data for {identifier} and {technology} is empty. Skipping writing to database."
                )
                continue

            if db_client is not None:
                db_client.write_vre_data(
                    df=generation,
                    technology=technology,
                    state=identifier,
                    mode=mode,
                    column_name="Generation [MW]",
                )

        total_generation = generation_df.sum(axis=1)
        for idx, _ in shapes.iterrows():
            identifier = (
                shapes.loc[idx].name if level == "federal" else shapes.loc[idx].NUTS_ID
            )
            if technology == "wind_offshore" and identifier not in OFFSHORE_STATES:
                continue

            capacity_factors = generation_df[identifier] / total_generation
            capacity_factors = capacity_factors.fillna(0)

            if db_client is not None:
                db_client.write_vre_data(
                    df=capacity_factors,
                    technology=technology,
                    state=identifier,
                    mode=mode,
                    column_name="reg_factor",
                )

    logger.info(f"Sucessfully calculated VRE generation and CF for {generation_df.index[0]}-{generation_df.index[-1]}")
