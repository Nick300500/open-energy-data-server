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
import io
import zipfile
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
import time

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

# Global variables for rate limiting
API_LIMIT = 600
TIME_WINDOW = 60  # seconds
request_count = 0
start_time = time.time()

base_url = "https://archive-api.open-meteo.com/v1/archive"

# Model and CRS Settings
crs = 4326

features = {
    "all": [
        "height",
        "wnd100m",
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
    "wind": ["wnd100m", "wnd_azimuth", "roughness"],
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
    """
    Rename 'longitude' and 'latitude' columns to 'x' and 'y' and fix roundings.

    Optionally (add_lon_lat, default:True) preserves latitude and
    longitude columns as 'lat' and 'lon'.
    """
    ds = ds.rename({"longitude": "x", "latitude": "y"})
    if "valid_time" in ds.sizes:
        ds = ds.rename({"valid_time": "time"}).unify_chunks()
    # round coords since cds coords are float32 which would lead to mismatches
    ds = ds.assign_coords(
        x=np.round(ds.x.astype(float), 5), y=np.round(ds.y.astype(float), 5)
    )
    ds = maybe_swap_spatial_dims(ds)
    if add_lon_lat:
        ds = ds.assign_coords(lon=ds.coords["x"], lat=ds.coords["y"])

    # Combine ERA5 and ERA5T data into a single dimension.
    # See https://github.com/PyPSA/atlite/issues/190
    if "expver" in ds.coords:
        unique_expver = np.unique(ds["expver"].values)
        if len(unique_expver) > 1:
            expver_dim = xr.DataArray(
                unique_expver, dims=["expver"], coords={"expver": unique_expver}
            )
            ds = (
                ds.assign_coords({"expver_dim": expver_dim})
                .drop_vars("expver")
                .rename({"expver_dim": "expver"})
                .set_index(expver="expver")
            )
            for var in ds.data_vars:
                ds[var] = ds[var].expand_dims("expver")
            # expver=1 is ERA5 data, expver=5 is ERA5T data This combines both
            # by filling in NaNs from ERA5 data with values from ERA5T.
            ds = ds.sel(expver="0001").combine_first(ds.sel(expver="0005"))
    ds = ds.drop_vars(["expver", "number"], errors="ignore")

    return ds

def get_data_all(retrieval_params):
    """Get all data from meteo API for given retrieval parameters at once to save requests and runtime."""
    times = retrieval_times(retrieval_params["coords"], static=True)
    del retrieval_params["coords"]

    ds = retrieve_meteo_data(
        variable=[
            "windspeed_100m",
            "winddirection_100m",
            "shortwave_radiation",
            "direct_radiation",
            "diffuse_radiation",
            "direct_normal_irradiance",
            "temperature_2m",
            "soil_temperature_28_to_100cm",
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

    ds_era5_fal = (
        ds_era5["fal"]
        .interp(
            time=ds.time.values,
            method="nearest",
            kwargs={"fill_value": "extrapolate"},
        )
        .chunk(chunks=retrieval_params["chunks"])
    )

    ds_era5_fsr = (
        ds_era5["fsr"]
        .interp(
            time=ds.time.values,
            method="nearest",
            kwargs={"fill_value": "extrapolate"},
        )
        .chunk(chunks=retrieval_params["chunks"])
    )

    ds_era5_tisr = (
        ds_era5["tisr"]
        .interp(
            time=ds.time.values,
            method="nearest",
            kwargs={"fill_value": "extrapolate"},
        )
        .chunk(chunks=retrieval_params["chunks"])
    )

    attrs = ds_era5.attrs
    ds_era5 = xr.merge([ds_era5_fal, ds_era5_fsr, ds_era5_tisr])
    ds_era5.attrs = attrs

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
            "soil_temperature_28_to_100cm": "soil temperature",
            "direct_radiation": "influx_direct",
            "diffuse_radiation": "influx_diffuse",
            "windspeed_100m": "wnd100m",
            "winddirection_100m": "wnd_azimuth",
            "fal": "albedo",
            "fsr": "roughness",
            "tisr": "influx_toa",
        }
    )

    ds = ds.drop_vars(
        [
            "shortwave_radiation",
            "direct_normal_irradiance",
        ]
    )

    # Convert from Celsius to Kelvin C -> K, by adding 273.15
    ds[["temperature", "soil temperature"]] = (
        ds[["temperature", "soil temperature"]] + 273.15
    )

    # Convert from energy to power J m**-2 -> W m**-2 and clip negative fluxes
    ds["influx_toa"] = ds["influx_toa"] / (60.0 * 60.0)

    ds["temperature"].attrs.update(units="K", long_name="2 metre temperature")
    ds["soil temperature"].attrs.update(units="K", long_name="Soil temperature 54cm")

    ds["wnd100m"].attrs.update(
        units="m s**-1", long_name="Wind speed at 100m above ground"
    )
    ds["wnd_azimuth"].attrs.update(
        units="degree", long_name="Wind direction at 100m above ground"
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
    
    # unify_chunks() is necessary to avoid a bug in xarray
    ds = ds.unify_chunks()

    # ERA5 variables are mean values for previous hour, i.e. 13:01 to 14:00 are labelled as "14:00"
    # account by calculating the SolarPosition for the center of the interval for aggregation happens
    # see https://github.com/PyPSA/atlite/issues/158
    # Do not show DeprecationWarning from new SolarPosition calculation (#199)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        time_shift = pd.to_timedelta("-30 minutes")
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
            "windspeed_100m",
            "winddirection_100m",
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
            "windspeed_100m": "wnd100m",
            "winddirection_100m": "wnd_azimuth",
            "fsr": "roughness",
        }
    )

    ds.wnd100m.attrs.update(
        units="m s**-1", long_name="Wind speed at 100m above ground"
    )
    ds.wnd_azimuth.attrs.update(
        units="degree", long_name="Wind direction at 100m above ground"
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

    ds = ds.drop_vars(["shortwave_radiation", "direct_normal_irradiance"])
        
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

    # unify_chunks() is necessary to avoid a bug in xarray
    ds = ds.unify_chunks()

    # ERA5 variables are mean values for previous hour, i.e. 13:01 to 14:00 are labelled as "14:00"
    # account by calculating the SolarPosition for the center of the interval for aggregation happens
    # see https://github.com/PyPSA/atlite/issues/158
    # Do not show DeprecationWarning from new SolarPosition calculation (#199)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        time_shift = pd.to_timedelta("-30 minutes")
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
        variable=["temperature_2m", "soil_temperature_28_to_100cm"], **retrieval_params
    )

    ds = _rename_and_clean_coords(ds)
    ds = ds.rename(
        {
            "temperature_2m": "temperature",
            "soil_temperature_28_to_100cm": "soil temperature",
        }
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

    # Generate latitude and longitude grid
    g_lat = np.arange(
        request["area"][2], request["area"][0] + request["grid"][0], request["grid"][0]
    )
    g_lon = np.arange(
        request["area"][1], request["area"][3] + request["grid"][1], request["grid"][1]
    )

    era5_coords = [(lon, lat) for lon in g_lon for lat in g_lat]

    # Precompute values that don't change in the loop
    start_date = request['start'].strftime('%Y-%m-%d')
    end_date = request['end'].strftime('%Y-%m-%d')
    hourly_variables = ','.join(request['variable'])

    # Fetch data sequentially with rate limiting
    data = []
    for longitude, latitude in era5_coords:
        # Apply rate limiting
        apply_rate_limiting()

        # Fetch data for the current coordinate
        result = fetch_data(longitude, latitude, hourly_variables, start_date, end_date)
        if result is not None:
            data.append(result)

    # Concatenate data and convert to xarray
    ds = pd.concat(data).to_xarray().chunk(chunks=chunks)

    return ds


def apply_rate_limiting():
    """Check and apply rate limiting based on the API limit."""
    global request_count, start_time

    # If we've reached the API limit, sleep for the remainder of the time window
    if request_count >= API_LIMIT:
        elapsed_time = time.time() - start_time
        if elapsed_time < TIME_WINDOW:
            time.sleep(TIME_WINDOW - elapsed_time)
        # Reset count and timer after sleeping
        request_count = 0
        start_time = time.time()

    # Increment the request count
    request_count += 1


def fetch_data(longitude, latitude, hourly_variables, start_date, end_date):
    """Fetch data for a specific coordinate."""
    data_url = f"{base_url}?latitude={latitude}&longitude={longitude}&hourly={hourly_variables}&windspeed_unit=ms&start_date={start_date}&end_date={end_date}"

    try:
        response = urlopen_with_retry(data_url)
        database = pd.DataFrame(response["hourly"])[hourly_variables.split(",") + ["time"]]

        # Prepare the data for concatenation
        database["time"] = pd.to_datetime(database["time"])
        database["latitude"] = latitude
        database["longitude"] = longitude
        database.set_index(["time", "latitude", "longitude"], inplace=True)

        return database

    except Exception as e:
        # Log the error if needed, or simply return None
        logger.error(f"Failed to fetch data for ({latitude}, {longitude}): {e}")
        return None


@retry(tries=5, delay=5, backoff=2)
def urlopen_with_retry(data_url):
    """Fetch data from the URL with retry mechanism."""
    resp = requests.get(data_url, timeout=5)
    response = resp.json()

    if response.get("error", False):
        raise ValueError(f"Error in response: {response['error']}, response: {response}")

    return response


def retrieve_era5_data(product, chunks=None, tmpdir=None, lock=None, **updates):
    """
    Download data like ERA5 from the Climate Data Store (CDS).

    If you want to track the state of your request go to
    https://cds-beta.climate.copernicus.eu/requests?tab=all
    """
    
    # Set url for data download, this allows to switch to different data 
    # sources more easily.
    url = 'https://cds.climate.copernicus.eu/api'
    product = 'reanalysis-era5-single-levels'
    
    request = {"product_type": ["reanalysis"],
               "data_format": "netcdf", 
               "download_format": "zip"}
    
    request.update(updates)

    assert {"year", "month", "variable"}.issubset(
        request
    ), "Need to specify at least 'variable', 'year' and 'month'"

    del request["start"], request["end"]

    client = cdsapi.Client(
        url = url,
        info_callback=logger.debug, 
        debug=logging.DEBUG >= logging.root.level
    )
    result = client.retrieve(product, request)

    if lock is None:
        lock = nullcontext()

    with lock:
        fd, target_zip = mkstemp(suffix=".zip", dir=tmpdir)
        os.close(fd)

        # Inform user about data being downloaded as "* variable (year-month)"
        timestr = f"{request['year']}-{request['month']}"
        variables = atleast_1d(request["variable"])
        varstr = "\n\t".join([f"{v} ({timestr})" for v in variables])
        logger.info(f"CDS: Downloading variables\n\t{varstr}\n")
        result.download(target_zip)
        
        # Open the .zip file in memory
        with zipfile.ZipFile(target_zip, "r") as zf:
            # Identify .nc files inside the .zip
            nc_files = [name for name in zf.namelist() if name.endswith(".nc")]
     
            if not nc_files:
                raise FileNotFoundError("No .nc files found in the downloaded .zip archive.")
     
            if len(nc_files) == 1:
                # If there's only one .nc file, read it into memory
                with zf.open(nc_files[0]) as nc_file:
                    # Pass the in-memory file-like object to Xarray
                    ds = xr.open_dataset(io.BytesIO(nc_file.read()), chunks=chunks or {})
                    
            else:
                # If multiple .nc files, combine them using Xarray
                datasets = []
                for nc_file in nc_files:
                    with zf.open(nc_file) as file:
                        datasets.append(xr.open_dataset(io.BytesIO(file.read()), chunks=chunks or {}))
                # Combine datasets along temporal dimension
                ds = xr.merge(datasets) 
        
    if tmpdir is None:
        logging.debug(f"Adding finalizer for {target_zip}")
        weakref.finalize(ds._file_obj._manager, noisy_unlink, target_zip)

    if "valid_time" in ds.sizes:
        ds = ds.rename({"valid_time": "time"}).unify_chunks()
    
    return ds


def retrieval_times(coords, static=False, monthly_requests=False):
    """
    Get list of retrieval cdsapi arguments for time dimension in coordinates.

    If static is False, this function creates a query for each month and year
    in the time axis in coords. This ensures not running into size query limits
    of the cdsapi even with very (spatially) large cutouts.
    If static is True, the function return only one set of parameters
    for the very first time point.

    Parameters
    ----------
    coords : atlite.Cutout.coords
    static : bool, optional
    monthly_requests : bool, optional
        If True, the data is requested on a monthly basis. This is useful for
        large cutouts, where the data is requested in smaller chunks. The
        default is False

    Returns
    -------
    list of dicts witht retrieval arguments

    """
    time = coords["time"].to_index()
    if static:
        return {
            "year": [str(time[0].year)],
            "month": [str(time[0].month).zfill(2)],
            "day": [str(time[0].day).zfill(2)],
            "time": time[0].strftime("%H:00"),
        }

    # Prepare request for all months and years
    times = []
    for year in time.year.unique():
        t = time[time.year == year]
        if monthly_requests:
            for month in t.month.unique():
                query = {
                    "year": str(year),
                    "month": [str(month).zfill(2)],
                    "day": list(t[t.month == month].day.unique().astype(str).str.zfill(2)),
                    "time": ["%02d:00" % h for h in t[t.month == month].hour.unique()],
                }
                times.append(query)
        else:
            query = {
                "year": [str(year)],
                "month": list(t.month.unique().astype(str).str.zfill(2)),
                "day": list(t.day.unique().astype(str).str.zfill(2)),
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
