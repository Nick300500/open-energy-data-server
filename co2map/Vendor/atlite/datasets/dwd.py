# -*- coding: utf-8 -*-

# SPDX-FileCopyrightText: 2016-2021 The Atlite Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Module for downloading and curating data from ECMWFs ERA5 dataset (via CDS).

For further reference see
https://confluence.ecmwf.int/display/CKB/ERA5%3A+data+documentation
"""

import logging
import os
import warnings
import weakref
from tempfile import mkstemp

import cdsapi
import numpy as np
import pandas as pd
import requests
import xarray as xr
from numpy import atleast_1d
from retry import retry

from ..gis import maybe_swap_spatial_dims
from ..pv.solar_position import SolarPosition

# Null context for running a with statements wihout any context
try:
    from contextlib import nullcontext
except ImportError:
    # for Python verions < 3.7:
    import contextlib

    @contextlib.contextmanager
    def nullcontext():
        yield


logger = logging.getLogger(__name__)

# Model and CRS Settings
crs = 4326

features = {
    "all": [
        "height",
        "wnd80m",
        "wnd_azimuth",
        "roughness",
        "influx_toa",
        "influx_direct",
        "influx_diffuse",
        "albedo",
        "solar_altitude",
        "solar_azimuth",
        "temperature",
        "soil temperature",
    ],
    "height": ["height"],
    "wind": ["wnd80m", "wnd_azimuth", "roughness"],
    "influx": [
        "influx_toa",
        "influx_direct",
        "influx_diffuse",
        "albedo",
        "solar_altitude",
        "solar_azimuth",
    ],
    "temperature": ["temperature", "soil temperature"],
}

static_features = {"height"}


def _add_height(ds):
    """Convert geopotential 'z' to geopotential height following [1].

    References
    ----------
    [1] ERA5: surface elevation and orography, retrieved: 10.02.2019
    https://confluence.ecmwf.int/display/CKB/ERA5%3A+surface+elevation+and+orography

    """
    g0 = 9.80665
    z = ds["z"]
    if "time" in z.coords:
        z = z.isel(time=0, drop=True)
    ds["height"] = z / g0
    ds = ds.drop_vars("z")
    return ds


def _rename_and_clean_coords(ds, add_lon_lat=True):
    """Rename 'longitude' and 'latitude' columns to 'x' and 'y' and fix roundings.

    Optionally (add_lon_lat, default:True) preserves latitude and longitude
    columns as 'lat' and 'lon'.
    """
    ds = ds.rename({"longitude": "x", "latitude": "y"})
    # round coords since cds coords are float32 which would lead to mismatches
    ds = ds.assign_coords(
        x=np.round(ds.x.astype(float), 5), y=np.round(ds.y.astype(float), 5)
    )
    ds = maybe_swap_spatial_dims(ds)
    if add_lon_lat:
        ds = ds.assign_coords(lon=ds.coords["x"], lat=ds.coords["y"])
    return ds


def get_data_all(retrieval_params):
    """Get all data from meteo API for given retrieval parameters at once to save requests and runtime."""
    times = retrieval_times(retrieval_params["coords"], static=True)
    del retrieval_params["coords"]

    ds = retrieve_meteo_data(
        variable=[
            "windspeed_80m",
            "winddirection_80m",
            "shortwave_radiation",
            "direct_radiation",
            "diffuse_radiation",
            "direct_normal_irradiance",
            "terrestrial_radiation",
            "temperature_2m",
            "soil_temperature_54cm",
        ],
        **retrieval_params,
    )

    ds_era5 = retrieve_era5_data(
        variable=[
            "forecast_surface_roughness",
            "toa_incident_solar_radiation",
            "forecast_albedo",
        ],
        **retrieval_params,
    )

    ds_era5["fal"] = (
        ds_era5["fal"]
        .interp(
            time=ds.time.values,
            method="nearest",
            kwargs={"fill_value": "extrapolate"},
        )
        .chunk(chunks=retrieval_params["chunks"])
    )

    ds_era5["fsr"] = (
        ds_era5["fsr"]
        .interp(
            time=ds.time.values,
            method="nearest",
            kwargs={"fill_value": "extrapolate"},
        )
        .chunk(chunks=retrieval_params["chunks"])
    )

    ds_era5["tisr"] = (
        ds_era5["tisr"]
        .interp(
            time=ds.time.values,
            method="nearest",
            kwargs={"fill_value": "extrapolate"},
        )
        .chunk(chunks=retrieval_params["chunks"])
    )

    (
        retrieval_params["year"],
        retrieval_params["month"],
        retrieval_params["day"],
        retrieval_params["time"],
    ) = (times["year"], times["month"], times["day"], times["time"])

    z_era5 = retrieve_era5_data(variable="geopotential", **retrieval_params).chunk(
        chunks=retrieval_params["chunks"]
    )
    z_era5 = _add_height(z_era5)

    ds = xr.merge([ds, ds_era5, z_era5])

    ds = _rename_and_clean_coords(ds)

    ds = ds.rename(
        {
            "temperature_2m": "temperature",
            "soil_temperature_54cm": "soil temperature",
            "direct_radiation": "influx_direct",
            "diffuse_radiation": "influx_diffuse",
            "windspeed_80m": "wnd80m",
            "winddirection_80m": "wnd_azimuth",
            "fal": "albedo",
            "fsr": "roughness",
            "tisr": "influx_toa",
        }
    )

    ds = ds.drop_vars(
        ["shortwave_radiation", "direct_normal_irradiance", "terrestrial_radiation"]
    )

    # Convert from Celsius to Kelvin C -> K, by adding 273.15
    ds[["temperature", "soil temperature"]] = (
        ds[["temperature", "soil temperature"]] + 273.15
    )

    # Convert from energy to power J m**-2 -> W m**-2 and clip negative fluxes
    ds["influx_toa"] = ds["influx_toa"] / (60.0 * 60.0)

    ds["temperature"].attrs.update(units="K", long_name="2 metre temperature")
    ds["soil temperature"].attrs.update(units="K", long_name="Soil temperature 54cm")

    ds["wnd80m"].attrs.update(
        units="m s**-1", long_name="Wind speed at 80m above ground"
    )
    ds["wnd_azimuth"].attrs.update(
        units="degree", long_name="Wind direction at 80m above ground"
    )

    ds["influx_direct"].attrs.update(
        units="W m**-2", long_name="Surface direct solar radiation downwards"
    )
    ds["influx_diffuse"].attrs.update(
        units="W m**-2", long_name="Surface diffuse solar radiation downwards"
    )
    ds["influx_toa"].attrs.update(
        units="W m**-2", long_name="TOA incident solar radiation"
    )

    # ERA5 variables are mean values for previous hour, i.e. 13:01 to 14:00 are labelled as "14:00"
    # account by calculating the SolarPosition for the center of the interval for aggregation happens
    # see https://github.com/PyPSA/atlite/issues/158
    # Do not show DeprecationWarning from new SolarPosition calculation (#199)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        # Convert dt / time frequency to timedelta and shift solar position by half
        # (freqs like ["H","30T"] do not work with pd.to_timedelta(...)
        time_shift = (
            -1
            / 2
            * pd.to_timedelta(
                pd.date_range(
                    "1970-01-01", periods=1, freq=pd.infer_freq(ds["time"])
                ).freq
            )
        )
        sp = SolarPosition(ds, time_shift=time_shift)
    sp = sp.rename({v: f"solar_{v}" for v in sp.data_vars})

    ds = xr.merge([ds, sp])

    return ds


def sanitize_all(ds):
    """Sanitize all retrieved data."""
    ds["roughness"] = ds["roughness"].where(ds["roughness"] >= 0.0, 2e-4)

    for a in ("influx_direct", "influx_diffuse", "influx_toa"):
        ds[a] = ds[a].clip(min=0.0)

    return ds


def get_data_wind(retrieval_params):
    """Get wind data for given retrieval parameters."""
    ds = retrieve_meteo_data(
        variable=[
            "windspeed_80m",
            "winddirection_80m",
        ],
        **retrieval_params,
    )

    fsr = retrieve_era5_data(
        variable=["forecast_surface_roughness"],
        **retrieval_params,
    )

    fsr = fsr.interp(
        time=ds.time.values,
        method="nearest",
        kwargs={"fill_value": "extrapolate"},
    )

    ds = xr.merge([ds, fsr])

    ds = _rename_and_clean_coords(ds)

    ds = ds.rename(
        {
            "windspeed_80m": "wnd80m",
            "winddirection_80m": "wnd_azimuth",
            "fsr": "roughness",
        }
    )

    ds.wnd80m.attrs.update(units="m s**-1", long_name="Wind speed at 80m above ground")
    ds.wnd_azimuth.attrs.update(
        units="degree", long_name="Wind direction at 80m above ground"
    )

    return ds


def sanitize_wind(ds):
    """Sanitize retrieved wind data."""
    ds["roughness"] = ds["roughness"].where(ds["roughness"] >= 0.0, 2e-4)
    return ds


def get_data_influx(retrieval_params):
    """Get influx data for given retrieval parameters."""
    ds = retrieve_meteo_data(
        variable=[
            "shortwave_radiation",
            "direct_radiation",
            "diffuse_radiation",
            "direct_normal_irradiance",
            "terrestrial_radiation",
        ],
        **retrieval_params,
    )

    fal = retrieve_era5_data(
        variable=["forecast_albedo"],
        **retrieval_params,
    )

    tisr = retrieve_era5_data(
        variable=["toa_incident_solar_radiation"],
        **retrieval_params,
    )

    fal = fal.interp(
        time=ds.time.values,
        method="nearest",
        kwargs={"fill_value": "extrapolate"},
    )

    tisr = tisr.interp(
        time=ds.time.values,
        method="nearest",
        kwargs={"fill_value": "extrapolate"},
    )

    ds = xr.merge([ds, fal, tisr])

    ds = _rename_and_clean_coords(ds)

    ds = ds.rename(
        {
            "direct_radiation": "influx_direct",
            "diffuse_radiation": "influx_diffuse",
            "tisr": "influx_toa",
            "fal": "albedo",
        }
    )

    ds = ds.drop_vars(
        ["shortwave_radiation", "terrestrial_radiation", "direct_normal_irradiance"]
    )

    # Convert from energy to power J m**-2 -> W m**-2 and clip negative fluxes
    ds["influx_toa"] = ds["influx_toa"] / (60.0 * 60.0)

    ds.influx_direct.attrs.update(
        units="W m**-2", long_name="Surface direct solar radiation downwards"
    )
    ds.influx_diffuse.attrs.update(
        units="W m**-2", long_name="Surface diffuse solar radiation downwards"
    )
    ds.influx_toa.attrs.update(
        units="W m**-2", long_name="TOA incident solar radiation"
    )

    # ERA5 variables are mean values for previous hour, i.e. 13:01 to 14:00 are labelled as "14:00"
    # account by calculating the SolarPosition for the center of the interval for aggregation happens
    # see https://github.com/PyPSA/atlite/issues/158
    # Do not show DeprecationWarning from new SolarPosition calculation (#199)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        # Convert dt / time frequency to timedelta and shift solar position by half
        # (freqs like ["H","30T"] do not work with pd.to_timedelta(...)
        time_shift = (
            -1
            / 2
            * pd.to_timedelta(
                pd.date_range(
                    "1970-01-01", periods=1, freq=pd.infer_freq(ds["time"])
                ).freq
            )
        )
        sp = SolarPosition(ds, time_shift=time_shift)
    sp = sp.rename({v: f"solar_{v}" for v in sp.data_vars})

    ds = xr.merge([ds, sp])

    return ds


def sanitize_influx(ds):
    """Sanitize retrieved influx data."""
    for a in ("influx_direct", "influx_diffuse", "influx_toa"):
        ds[a] = ds[a].clip(min=0.0)
    return ds


def get_data_temperature(retrieval_params):
    """Get wind temperature for given retrieval parameters."""
    ds = retrieve_meteo_data(
        variable=["temperature_2m", "soil_temperature_54cm"], **retrieval_params
    )

    ds = _rename_and_clean_coords(ds)
    ds = ds.rename(
        {"temperature_2m": "temperature", "soil_temperature_54cm": "soil temperature"}
    )

    # Convert from Celsius to Kelvin C -> K, by adding 273.15
    ds = ds + 273.15

    ds["temperature"].attrs.update(units="K", long_name="2 metre temperature")
    ds["soil temperature"].attrs.update(units="K", long_name="Soil temperature 54cm")

    return ds


def get_data_height(retrieval_params):
    """Get height data for given retrieval parameters."""
    ds = retrieve_era5_data(variable="geopotential", **retrieval_params)

    ds = _rename_and_clean_coords(ds)
    ds = _add_height(ds)

    return ds


def _area(coords):
    # North, West, South, East. Default: global
    x0, x1 = coords["x"].min().item(), coords["x"].max().item()
    y0, y1 = coords["y"].min().item(), coords["y"].max().item()
    return [y1, x0, y0, x1]


def noisy_unlink(path):
    """Delete file at given path."""
    logger.debug(f"Deleting file {path}")
    try:
        os.unlink(path)
    except PermissionError:
        logger.error(f"Unable to delete file {path}, as it is still in use.")


def retrieve_meteo_data(product, chunks=None, tmpdir=None, lock=None, **updates):
    """
    Download data like ERA5 from the Climate Data Store (CDS).

    If you want to track the state of your request go to
    https://cds.climate.copernicus.eu/cdsapp#!/yourrequests
    """
    request = {"product_type": "meteo_api", "format": "direct_download"}
    request.update(updates)

    g_lat = np.arange(
        request["area"][2], request["area"][0] + request["grid"][0], request["grid"][0]
    )
    g_lon = np.arange(
        request["area"][1], request["area"][3] + request["grid"][1], request["grid"][1]
    )

    era5_grid = np.meshgrid(g_lon, g_lat, indexing="ij")
    era5_coords = list(zip(era5_grid[0].flatten(), era5_grid[1].flatten()))

    data = list()

    for longitude, latitude in era5_coords:
        data_url = f"https://api.open-meteo.com/v1/dwd-icon?latitude={latitude}&longitude={longitude}&hourly={','.join(request['variable'])}&windspeed_unit=ms&start_date={request['start'].strftime('%Y-%m-%d')}&end_date={request['end'].strftime('%Y-%m-%d')}"

        database = urlopen_with_retry(data_url)

        database = pd.DataFrame(database["hourly"])[request["variable"] + ["time"]]

        database["time"] = pd.to_datetime(database["time"])
        database["latitude"] = latitude
        database["longitude"] = longitude
        database.set_index(["time", "latitude", "longitude"], inplace=True)

        data.append(database)

    ds = pd.concat(data).to_xarray().chunk(chunks=chunks)

    return ds


@retry(tries=5, delay=5)
def urlopen_with_retry(data_url):
    resp = requests.get(data_url, timeout=5)
    database = resp.json()
    return database


def retrieve_era5_data(product, chunks=None, tmpdir=None, lock=None, **updates):
    """
    Download data like ERA5 from the Climate Data Store (CDS).

    If you want to track the state of your request go to
    https://cds.climate.copernicus.eu/cdsapp#!/yourrequests
    """
    request = {"product_type": "reanalysis", "format": "netcdf"}
    request.update(updates)

    assert {"year", "month", "variable"}.issubset(
        request
    ), "Need to specify at least 'variable', 'year' and 'month'"

    client = cdsapi.Client(
        info_callback=logger.debug, debug=logging.DEBUG >= logging.root.level
    )
    del request["start"], request["end"]
    result = client.retrieve("reanalysis-era5-single-levels", request)

    if lock is None:
        lock = nullcontext()

    with lock:
        fd, target = mkstemp(suffix=".nc", dir=tmpdir)
        os.close(fd)

        yearstr = ", ".join(atleast_1d(request["year"]))
        variables = atleast_1d(request["variable"])
        varstr = "".join(["\t * " + v + f" ({yearstr})\n" for v in variables])
        logger.info(f"CDS: Downloading variables\n{varstr}")
        result.download(target)

    ds = xr.open_dataset(target, chunks=chunks or {})
    if tmpdir is None:
        logger.debug(f"Adding finalizer for {target}")
        weakref.finalize(ds._file_obj._manager, noisy_unlink, target)

    return ds


def retrieval_times(coords, static=False):
    """
    Get list of retrieval cdsapi arguments for time dimension in coordinates.

    If static is False, this function creates a query for each year in the
    time axis in coords. This ensures not running into query limits of the
    cdsapi. If static is True, the function return only one set of parameters
    for the very first time point.

    Parameters
    ----------
    coords : atlite.Cutout.coords

    Returns
    -------
    list of dicts witht retrieval arguments

    """
    time = coords["time"].to_index()
    if static:
        return {
            "year": str(time[0].year),
            "month": str(time[0].month),
            "day": str(time[0].day),
            "time": time[0].strftime("%H:00"),
        }

    times = []
    for year in time.year.unique():
        t = time[time.year == year]
        query = {
            "year": str(year),
            "month": list(t.month.unique()),
            "day": list(t.day.unique()),
            "time": ["%02d:00" % h for h in t.hour.unique()],
        }
        times.append(query)
    return times


def get_data(cutout, feature, tmpdir, lock=None, **creation_parameters):
    """
    Retrieve data from ECMWFs ERA5 dataset (via CDS).

    This front-end function downloads data for a specific feature and formats
    it to match the given Cutout.

    Parameters
    ----------
    cutout : atlite.Cutout
    feature : str
        Name of the feature data to retrieve. Must be in
        `atlite.datasets.era5.features`
    tmpdir : str/Path
        Directory where the temporary netcdf files are stored.
    **creation_parameters :
        Additional keyword arguments. The only effective argument is 'sanitize'
        (default True) which sets sanitization of the data on or off.

    Returns
    -------
    xarray.Dataset
        Dataset of dask arrays of the retrieved variables.

    """
    coords = cutout.coords

    sanitize = creation_parameters.get("sanitize", True)

    retrieval_params = {
        "product": "meteo_api_data",
        "area": _area(coords),
        "chunks": cutout.chunks,
        "grid": [cutout.dx, cutout.dy],
        "tmpdir": tmpdir,
        "lock": lock,
    }

    func = globals().get(f"get_data_{feature}")
    sanitize_func = globals().get(f"sanitize_{feature}")

    logger.info(f"Requesting data for feature {feature}...")

    def retrieve_once(time):
        ds = func({**retrieval_params, **time})
        if sanitize and sanitize_func is not None:
            ds = sanitize_func(ds)
        return ds

    time = coords["time"].to_index()

    start_date = time.min()
    end_date = time.max()

    if feature in static_features:
        datasets = retrieve_once(
            {
                **{"start": start_date, "end": end_date},
                **retrieval_times(coords, static=True),
            }
        )
    elif feature == "all":
        datasets = retrieve_once(
            {
                **{"start": start_date, "end": end_date, "coords": coords},
                **retrieval_times(coords)[0],
            }
        )
    else:
        datasets = retrieve_once(
            {**{"start": start_date, "end": end_date}, **retrieval_times(coords)[0]}
        )

    return datasets
