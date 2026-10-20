# ruff: noqa: E501
"""Economic impact: per-asset clear-sky PV with the published E3 chain.

Ineichen clear sky (pvlib) → `cloud2grid.solar.pv.capacity_factor` with the frozen E3 PV config,
times each asset's active capacity, on the same 15-minute slots as the frozen E3 PV estimate.
Cached in data/interim/economic_impact/assets_with_clearsky.parquet.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from cloud2grid.solar import irradiance as irr
from cloud2grid.solar import pv as pvm

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data/interim/economic_impact/assets_with_clearsky.parquet"
PV_CFG = yaml.safe_load((ROOT / "configs/experiments/e3_pv_model.yaml").read_text())
ASSETS = pd.read_parquet(ROOT / "data/demo/events/jun15_cloud_clearing/assets.parquet").set_index("asset_id")


def _clearsky_cf(times: pd.DatetimeIndex, lat: float, lon: float) -> np.ndarray:
    sp = irr.solar_position(times, lat, lon)
    cs = irr.pvlib.location.Location(lat, lon).get_clearsky(times, model="ineichen", solar_position=sp)
    df = pd.DataFrame({"ghi": cs["ghi"].to_numpy(), "dhi": cs["dhi"].to_numpy(), "dni": cs["dni"].to_numpy(),
                       "apparent_zenith": sp["apparent_zenith"].to_numpy(), "azimuth": sp["azimuth"].to_numpy()}, index=times)  # fmt: skip
    return pvm.capacity_factor(df, PV_CFG["pv"]).to_numpy()


@lru_cache(maxsize=1)
def assets_table() -> pd.DataFrame:
    """Per (asset, slot): frozen PV estimate plus the clear-sky PV of the same chain."""
    cache = CACHE
    if cache.exists():
        return pd.read_parquet(cache)
    pa = pd.read_parquet(ROOT / "data/processed/satellite/sundon/pv_by_asset.parquet")
    pa = pa[pa.active_capacity_mw > 0].copy()
    parts = []
    for aid, g in pa.groupby("asset_id"):
        g = g.sort_values("slot").copy()
        r = ASSETS.loc[aid]
        g["pv_clear_mw"] = _clearsky_cf(pd.DatetimeIndex(g.acquisition_time), float(r.lat), float(r.lon)) * g.active_capacity_mw
        parts.append(g)
    out = pd.concat(parts, ignore_index=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(cache, index=False)
    return out
