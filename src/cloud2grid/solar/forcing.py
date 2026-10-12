"""MDSSFTD slot(s) → per-asset irradiance → capacity factor → estimated PV (E3 core).

Pure functions on xarray/pandas objects so the same code runs on synthetic, product-shaped
fixtures (tests) and on real cropped files (scripts/build_pv_timeseries.py).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pvlib
import xarray as xr

from cloud2grid.satellite import quality
from cloud2grid.satellite.geometry import RegularGrid
from cloud2grid.scenarios import events
from cloud2grid.solar import capacity as capm
from cloud2grid.solar import irradiance as irr
from cloud2grid.solar import pv


def sample_assets(ds: xr.Dataset, mapped: pd.DataFrame, names: dict[str, str]) -> pd.DataFrame:
    """Values at each asset's regular-grid cell for every time step of `ds` (decoded product).

    `mapped` comes from `satellite.geometry.map_assets` (pixel_row/col are FULL-grid indices);
    cells are selected by their centre coordinates, so cropped datasets work too.
    """
    lat = xr.DataArray(mapped["pixel_center_lat"].to_numpy(), dims="asset")
    lon = xr.DataArray(mapped["pixel_center_lon"].to_numpy(), dims="asset")
    sub = ds[[names["total"], names["diffuse_fraction"], names["quality"]]].sel(
        lat=lat, lon=lon, method="nearest", tolerance=0.01
    )
    df = sub.to_dataframe().reset_index()
    df["asset_id"] = mapped["asset_id"].to_numpy()[df["asset"].to_numpy()]
    df = df.rename(
        columns={
            names["total"]: "dssf_tot",
            names["diffuse_fraction"]: "fraction_diffuse",
            names["quality"]: "quality_flag",
            "time": "slot",
        }
    )
    df["status"] = quality.classify(df["quality_flag"], df["dssf_tot"], df["fraction_diffuse"])
    return df[["slot", "asset_id", "dssf_tot", "fraction_diffuse", "quality_flag", "status"]]


def asset_pv(
    samples: pd.DataFrame,
    mapped: pd.DataFrame,
    assets: pd.DataFrame,
    evidence: dict[str, dict],
    pv_cfg: dict[str, Any],
    allow_low_quality: bool,
    include_undated: bool = False,
) -> pd.DataFrame:
    """Per (slot, asset): GHI/DHI/DNI at acquisition time, capacity factor, active capacity and
    estimated PV (MW). Quality status is carried through unchanged."""
    out = []
    meta = mapped.set_index("asset_id")
    for aid, s in samples.groupby("asset_id", sort=True):
        s = s.sort_values("slot")
        m = meta.loc[aid]
        slot = pd.DatetimeIndex(pd.to_datetime(s["slot"], utc=True))
        acq = slot + pd.to_timedelta(float(m["acquisition_offset_min"]), unit="min")
        ghi, fd = quality.apply(
            s["dssf_tot"].to_numpy(),
            s["fraction_diffuse"].to_numpy(),
            s["status"].to_numpy(),
            allow_low_quality,
        )
        comp = irr.components(acq, ghi, fd, float(m["lat"]), float(m["lon"]), pv_cfg["irradiance"])
        cf = pv.capacity_factor(comp, pv_cfg["pv"])
        a = assets[assets["asset_id"] == aid]
        caps = [
            float(
                capm.active_capacity(a, t, evidence, include_undated)["active_capacity_mw"].iloc[0]
            )
            for t in slot
        ]
        df = comp.reset_index(drop=True)
        df.insert(0, "acquisition_time", acq)
        df.insert(0, "slot", slot)
        df.insert(0, "asset_id", aid)
        df["pixel_id"] = m["pixel_id"]
        df["native_pixel_id"] = m["native_pixel_id"]
        df["sampled_native_pixel_id"] = m.get("sampled_native_pixel_id")
        df["status"] = s["status"].to_numpy()
        df["quality_flag"] = s["quality_flag"].to_numpy()
        df["capacity_factor"] = cf.to_numpy()
        df["active_capacity_mw"] = caps
        df["estimated_pv_mw"] = df["capacity_factor"] * df["active_capacity_mw"]
        out.append(df)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def field_slot_stats(
    ds_slot: xr.Dataset,
    names: dict[str, str],
    acq_time: pd.Timestamp,
    thr: dict[str, Any],
    allow_low_quality: bool,
) -> dict[str, float]:
    """Clear-sky-index field statistics of the analysis box for one slot. Clear-sky GHI is
    evaluated at the box centre (≤ 60 km box; documented approximation)."""
    lat, lon = ds_slot["lat"].values, ds_slot["lon"].values
    tot = ds_slot[names["total"]].values.squeeze()
    fr = ds_slot[names["diffuse_fraction"]].values.squeeze()
    q = ds_slot[names["quality"]].values.squeeze()
    status = quality.classify(q, tot, fr)
    ok = quality.usable(status, allow_low_quality)
    ghi, _ = quality.apply(tot, fr, status, allow_low_quality)
    loc = pvlib.location.Location(float(np.mean(lat)), float(np.mean(lon)))
    t = pd.DatetimeIndex([acq_time])
    cs = loc.get_clearsky(t, model="ineichen")["ghi"].iloc[0]
    elev = float(loc.get_solarposition(t)["elevation"].iloc[0])
    kc = ghi / cs if cs > 10 else np.full_like(ghi, np.nan)
    grid = RegularGrid.from_coords(lat, lon)
    dx, dy = grid.cell_km(float(np.mean(lat)))
    stats = events.field_stats(kc, ok & np.isfinite(kc), dy, dx, thr)
    stats["elevation"] = elev
    stats["field_mean_ghi"] = float(np.nanmean(np.where(ok, ghi, np.nan))) if ok.any() else np.nan
    return stats
