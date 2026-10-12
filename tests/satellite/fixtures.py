"""Synthetic datasets shaped like the real LSA SAF MDSSFTD NetCDF4 product.

Structure taken from the official LSA SAF tutorial outputs and PUM (configs/data/lsasaf.yaml):
dims (time, lat, lon) with lat DESCENDING on a 0.05° grid aligned to 80.0 / -80.0; variables
DSSF_TOT (W/m2, int16 packed, CF scale_factor), FRACTION_DIFFUSE (packed), quality_flag (uint8).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

CLEAR_OK = 133  # land | clear | clear: processing ok
CLOUD_OK = 13  # land | cloud filled | cloudy: processing ok
NIGHT = 165  # land | clear | clear: night
FAIL = 0b01101101  # land | cloud filled | cloudy: algorithm failure (109)


def product(
    times: list[str],
    lat_range: tuple[float, float] = (52.20, 51.70),
    lon_range: tuple[float, float] = (-0.90, -0.30),
    dssf: np.ndarray | None = None,
    fraction: np.ndarray | None = None,
    flag: np.ndarray | None = None,
) -> xr.Dataset:
    lat = np.round(np.arange(lat_range[0], lat_range[1] - 1e-9, -0.05), 2)
    lon = np.round(np.arange(lon_range[0], lon_range[1] + 1e-9, 0.05), 2)
    shape = (len(times), len(lat), len(lon))
    dssf = np.full(shape, 800.0) if dssf is None else dssf
    fraction = np.full(shape, 0.2) if fraction is None else fraction
    flag = np.full(shape, CLEAR_OK, dtype=np.uint8) if flag is None else flag
    t = pd.DatetimeIndex(pd.to_datetime(times, utc=True)).tz_localize(None)
    ds = xr.Dataset(
        {
            "DSSF_TOT": (
                ("time", "lat", "lon"),
                dssf.astype(float),
                {"units": "W/m2", "long_name": "Total DSSF"},
            ),
            "FRACTION_DIFFUSE": (("time", "lat", "lon"), fraction.astype(float), {"units": "1"}),
            "quality_flag": (("time", "lat", "lon"), flag.astype(np.uint8)),
        },
        coords={
            "time": t,
            "lat": ("lat", lat.astype(np.float32), {"units": "degrees_north"}),
            "lon": ("lon", lon.astype(np.float32), {"units": "degrees_east"}),
        },
        attrs={"algorithm_version": "test", "Conventions": "CF-1.6", "region_name": "MSG-Disk"},
    )
    return ds


def write_packed(ds: xr.Dataset, path: Path) -> Path:
    """Write with the product's packing: int16 with scale factors and fill value -1."""
    enc = {
        "DSSF_TOT": {"dtype": "int16", "scale_factor": 0.1, "_FillValue": -1},
        "FRACTION_DIFFUSE": {"dtype": "int16", "scale_factor": 0.01, "_FillValue": -1},
        "quality_flag": {"dtype": "uint8"},
    }
    ds.to_netcdf(path, encoding=enc)
    return path
