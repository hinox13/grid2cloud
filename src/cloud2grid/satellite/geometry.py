"""Product geometry for LSA SAF MSG products and asset-to-pixel mapping.

Two grids are involved:

* the **regular 0.05° latitude/longitude grid** of the MDSSFTD NetCDF4 files ("MSG-Disk";
  lat 80 → -80 descending, lon -80 → 80; coordinates are cell centres). Asset sampling uses it;
* the **native MSG/SEVIRI geostationary grid** (3712 × 3712, 3 km at the sub-satellite point)
  in which the product is *retrieved* (PUM §6.2; HDF5 files). The NetCDF grid is a resampling
  of it, so the native pixel — not the 0.05° cell — bounds how many independent irradiance
  samples a set of assets can receive. It also sets the line acquisition time (PUM §6.3).

Native projection: CGMS normalized geostationary projection (CGMS LRIT/HRIT Global
Specification §4.4.3.2), with the LSA SAF constants of PUM §6.2 (COFF = LOFF = 1857,
CFAC = LFAC = 13642337, scan angles in degrees, ncol = 1 westernmost, nlin = 1 northernmost).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from cloud2grid.evaluation.spatial import EARTH_R_KM

# CGMS ellipsoid and orbit (LRIT/HRIT Global Spec §4.4.3.2)
R_EQ_KM = 6378.169
R_POL_KM = 6356.5838
SAT_DIST_KM = 42164.0


@dataclass(frozen=True)
class NativeGrid:
    coff: float = 1857.0
    loff: float = 1857.0
    cfac: float = 13642337.0
    lfac: float = 13642337.0
    n: int = 3712
    sub_lon: float = 0.0


MSG_DISK = NativeGrid()  # full MSG disk (PUM §6.2)


@dataclass(frozen=True)
class RegularGrid:
    """Regular grid described by its first cell centres and step (descending lat allowed)."""

    lat0: float = 80.0
    lon0: float = -80.0
    dlat: float = -0.05
    dlon: float = 0.05
    nlat: int = 3201
    nlon: int = 3201

    @classmethod
    def from_coords(cls, lat: np.ndarray, lon: np.ndarray) -> RegularGrid:
        lat, lon = np.asarray(lat, float), np.asarray(lon, float)
        dlat, dlon = np.diff(lat), np.diff(lon)
        if not (np.allclose(dlat, dlat[0], atol=1e-4) and np.allclose(dlon, dlon[0], atol=1e-4)):
            raise ValueError("coordinates are not a regular grid")
        return cls(float(lat[0]), float(lon[0]), float(dlat[0]), float(dlon[0]), len(lat), len(lon))

    def index(self, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Nearest cell (row, col), 0-based — the cell whose centre is closest."""
        row = np.rint((np.asarray(lat, float) - self.lat0) / self.dlat).astype(int)
        col = np.rint((np.asarray(lon, float) - self.lon0) / self.dlon).astype(int)
        if (
            (row < 0).any()
            or (row >= self.nlat).any()
            or (col < 0).any()
            or (col >= self.nlon).any()
        ):
            raise ValueError("point outside the grid")
        return row, col

    def centre(self, row: np.ndarray, col: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return self.lat0 + np.asarray(row) * self.dlat, self.lon0 + np.asarray(col) * self.dlon

    def cell_km(self, lat: float) -> tuple[float, float]:
        """(E–W, N–S) cell size in km at latitude `lat` (spherical Earth)."""
        dx = math.radians(abs(self.dlon)) * EARTH_R_KM * math.cos(math.radians(lat))
        return dx, math.radians(abs(self.dlat)) * EARTH_R_KM


# ----------------------------------------------------------------------- native projection


def native_scan_angles(
    lat: np.ndarray, lon: np.ndarray, sub_lon: float = 0.0
) -> tuple[np.ndarray, np.ndarray]:
    """Geographic → CGMS intermediate coordinates (x, y) in degrees."""
    lat_r = np.radians(np.asarray(lat, float))
    dlon = np.radians(np.asarray(lon, float) - sub_lon)
    c_lat = np.arctan((R_POL_KM**2 / R_EQ_KM**2) * np.tan(lat_r))
    e2 = (R_EQ_KM**2 - R_POL_KM**2) / R_EQ_KM**2
    r_l = R_POL_KM / np.sqrt(1 - e2 * np.cos(c_lat) ** 2)
    r1 = SAT_DIST_KM - r_l * np.cos(c_lat) * np.cos(dlon)
    r2 = -r_l * np.cos(c_lat) * np.sin(dlon)
    r3 = r_l * np.sin(c_lat)
    rn = np.sqrt(r1**2 + r2**2 + r3**2)
    if np.any(r1 * SAT_DIST_KM - r1**2 - r2**2 - r3**2 * R_EQ_KM**2 / R_POL_KM**2 < 0):
        raise ValueError("point not visible from the satellite")
    return np.degrees(np.arctan(-r2 / r1)), np.degrees(np.arcsin(-r3 / rn))


def native_index(
    lat: np.ndarray, lon: np.ndarray, g: NativeGrid = MSG_DISK
) -> tuple[np.ndarray, np.ndarray]:
    """Geographic → 1-based native (ncol from west, nlin from north), continuous."""
    x, y = native_scan_angles(lat, lon, g.sub_lon)
    return g.coff + x * 2**-16 * g.cfac, g.loff + y * 2**-16 * g.lfac


def native_pixel(
    lat: np.ndarray, lon: np.ndarray, g: NativeGrid = MSG_DISK
) -> tuple[np.ndarray, np.ndarray]:
    """Native pixel containing the point: 1-based (ncol, nlin) integers."""
    c, l_ = native_index(lat, lon, g)
    return np.rint(c).astype(int), np.rint(l_).astype(int)


def native_to_geo(
    ncol: np.ndarray, nlin: np.ndarray, g: NativeGrid = MSG_DISK
) -> tuple[np.ndarray, np.ndarray]:
    """1-based native (ncol, nlin) → geographic (lat, lon) of the point (CGMS inverse)."""
    x = np.radians((np.asarray(ncol, float) - g.coff) / (2**-16 * g.cfac))
    y = np.radians((np.asarray(nlin, float) - g.loff) / (2**-16 * g.lfac))
    k = R_EQ_KM**2 / R_POL_KM**2
    a = np.cos(y) ** 2 + k * np.sin(y) ** 2
    sd2 = (SAT_DIST_KM * np.cos(x) * np.cos(y)) ** 2 - a * (SAT_DIST_KM**2 - R_EQ_KM**2)
    if np.any(sd2 < 0):
        raise ValueError("pixel off the Earth disk")
    sd = np.sqrt(sd2)
    sn = (SAT_DIST_KM * np.cos(x) * np.cos(y) - sd) / a
    s1 = SAT_DIST_KM - sn * np.cos(x) * np.cos(y)
    s2 = sn * np.sin(x) * np.cos(y)
    s3 = -sn * np.sin(y)
    sxy = np.sqrt(s1**2 + s2**2)
    lon = np.degrees(np.arctan(s2 / s1)) + g.sub_lon
    lat = np.degrees(np.arctan(k * s3 / sxy))
    return lat, lon


def native_footprint_km(lat: float, lon: float, g: NativeGrid = MSG_DISK) -> dict:
    """Size of the native pixel containing (lat, lon): E–W and N–S extent in km."""
    c, l_ = native_pixel(np.array([lat]), np.array([lon]), g)
    c, l_ = float(c[0]), float(l_[0])
    lat_w, lon_w = map(float, native_to_geo(c - 0.5, l_, g))
    lat_e, lon_e = map(float, native_to_geo(c + 0.5, l_, g))
    lat_n, lon_n = map(float, native_to_geo(c, l_ - 0.5, g))
    lat_s, lon_s = map(float, native_to_geo(c, l_ + 0.5, g))
    ew = haversine_km(lat_w, lon_w, lat_e, lon_e)
    ns = haversine_km(lat_n, lon_n, lat_s, lon_s)
    return {"ncol": int(c), "nlin": int(l_), "dx_km": ew, "dy_km": ns, "area_km2": ew * ns}


def acquisition_offset_min(nlin: np.ndarray) -> np.ndarray:
    """Line acquisition time after the nominal slot, minutes (PUM §6.3, eq. 5:
    Δt = 760 − Y/5 seconds with Y the native line counted from the north; as used in the LSA SAF
    tutorial `12_Acquisition_time_analysis`). SEVIRI scans south → north."""
    return (760.0 - np.asarray(nlin, float) / 5.0) / 60.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_R_KM * math.asin(math.sqrt(min(1.0, a)))


# ------------------------------------------------------------------- asset → pixel mapping


def map_assets(
    assets: pd.DataFrame, grid: RegularGrid, native: NativeGrid = MSG_DISK
) -> pd.DataFrame:
    """Per asset: regular-grid cell, its centre and distance, and the native pixel.

    `assets` needs columns asset_id, capacity_mw, lat, lon.
    """
    lat, lon = assets["lat"].to_numpy(float), assets["lon"].to_numpy(float)
    row, col = grid.index(lat, lon)
    clat, clon = grid.centre(row, col)
    ncol, nlin = native_pixel(lat, lon, native)
    nlat, nlon = native_to_geo(ncol, nlin, native)
    out = assets.copy()
    out["pixel_row"], out["pixel_col"] = row, col
    out["pixel_id"] = [f"r{r}c{c}" for r, c in zip(row, col, strict=True)]
    out["pixel_center_lat"], out["pixel_center_lon"] = clat, clon
    out["dist_to_pixel_center_km"] = [
        haversine_km(a, b, c, d) for a, b, c, d in zip(lat, lon, clat, clon, strict=True)
    ]
    out["native_ncol"], out["native_nlin"] = ncol, nlin
    out["native_pixel_id"] = [f"n{c}_{li}" for c, li in zip(ncol, nlin, strict=True)]
    out["native_center_lat"], out["native_center_lon"] = nlat, nlon
    out["dist_to_native_center_km"] = [
        haversine_km(a, b, c, d) for a, b, c, d in zip(lat, lon, nlat, nlon, strict=True)
    ]
    out["acquisition_offset_min"] = acquisition_offset_min(nlin)
    # The NetCDF value of a 0.05° cell is the native pixel containing the CELL CENTRE
    # (nearest-neighbour reprojection, verified on a real file): that is the sample an asset
    # actually receives when the product is read at its cell.
    sc, sl = native_pixel(clat, clon, native)
    out["sampled_native_pixel_id"] = [f"n{c}_{li}" for c, li in zip(sc, sl, strict=True)]
    return out


def pixel_summary(mapped: pd.DataFrame, pixel_col: str) -> dict:
    """Distinct pixels, shared pixels and capacity-weighted effective pixel count."""
    share = mapped.groupby(pixel_col)["capacity_mw"].sum() / mapped["capacity_mw"].sum()
    shared = {
        str(k): sorted(map(str, v))
        for k, v in mapped.groupby(pixel_col)["asset_id"].apply(list).items()
        if len(v) > 1
    }
    return {
        "distinct_pixels": int(mapped[pixel_col].nunique()),
        "effective_independent_pixels": float(1 / (share**2).sum()),
        "shared_pixels": shared,
    }


def pixel_separations(mapped: pd.DataFrame, row: str, col: str) -> pd.DataFrame:
    """Pairwise separation between assets in pixel steps (Chebyshev and Δrow/Δcol) and km."""
    rows = []
    recs = mapped.to_dict("records")
    for i in range(len(recs)):
        for j in range(i + 1, len(recs)):
            a, b = recs[i], recs[j]
            dr, dc = int(b[row] - a[row]), int(b[col] - a[col])
            rows.append(
                {
                    "asset_a": a["asset_id"],
                    "asset_b": b["asset_id"],
                    "d_row": dr,
                    "d_col": dc,
                    "chebyshev": max(abs(dr), abs(dc)),
                    "distance_km": haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]),
                }
            )
    return pd.DataFrame(rows)
