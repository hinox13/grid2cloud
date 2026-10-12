"""Spatial-diversity metrics for PV fleets and an APPROXIMATE satellite-pixel model (E3 prep).

Everything here uses asset coordinates and capacities only. The pixel model is a geometric
approximation of a geostationary (MSG/SEVIRI-like) grid; it is not derived from product files.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

EARTH_R_KM = 6371.0
GEO_R_KM = 42164.0
GEO_ALT_KM = GEO_R_KM - EARTH_R_KM  # 35,793 km (≈ 35,786 km nominal)


def pairwise_km(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    p = np.radians(lat)[:, None], np.radians(lat)[None, :]
    dphi = p[1] - p[0]
    dlmb = np.radians(lon)[None, :] - np.radians(lon)[:, None]
    a = np.sin(dphi / 2) ** 2 + np.cos(p[0]) * np.cos(p[1]) * np.sin(dlmb / 2) ** 2
    return 2 * EARTH_R_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def hhi(capacity: np.ndarray) -> dict[str, float]:
    """Herfindahl index of capacity shares, normalised to [0, 1], and effective asset count."""
    s = np.asarray(capacity, dtype=float)
    s = s / s.sum()
    n = len(s)
    h = float((s**2).sum())
    norm = (h - 1 / n) / (1 - 1 / n) if n > 1 else 1.0
    return {"hhi": h, "normalised_hhi": float(norm), "effective_n_assets": 1 / h}


def assets_for_share(capacity: np.ndarray, share: float) -> int:
    """Smallest number of assets (largest first) holding >= share of total capacity."""
    c = np.sort(np.asarray(capacity, dtype=float))[::-1]
    cum = np.cumsum(c) / c.sum()
    return int(np.searchsorted(cum, share - 1e-12) + 1)


def weighted_mean_pairwise_km(capacity: np.ndarray, d: np.ndarray) -> float:
    w = np.asarray(capacity, dtype=float)
    iu = np.triu_indices(len(w), 1)
    ww = (w[:, None] * w[None, :])[iu]
    return float((ww * d[iu]).sum() / ww.sum()) if len(ww) else 0.0


def effective_extent_km(lat: np.ndarray, lon: np.ndarray, capacity: np.ndarray) -> float:
    """2 × capacity-weighted radius of gyration about the capacity-weighted centroid."""
    w = np.asarray(capacity, dtype=float) / np.sum(capacity)
    lat0 = float((w * lat).sum())
    x = np.radians(lon - (w * lon).sum()) * EARTH_R_KM * math.cos(math.radians(lat0))
    y = np.radians(lat - lat0) * EARTH_R_KM
    return float(2 * math.sqrt((w * (x**2 + y**2)).sum()))


def ew_span_km(lat: np.ndarray, lon: np.ndarray) -> float:
    return float(
        np.radians(lon.max() - lon.min()) * EARTH_R_KM * math.cos(math.radians(lat.mean()))
    )


def pixel_footprint(
    lat: float, lon: float, nominal_km: float = 3.0, sub_lon: float = 0.0
) -> dict[str, float]:
    """APPROXIMATE geostationary pixel footprint at (lat, lon).

    dx (E–W) = nominal × slant_range / altitude; dy (N–S) = dx / cos(viewing zenith).
    """
    gamma = math.acos(math.cos(math.radians(lat)) * math.cos(math.radians(lon - sub_lon)))
    slant = math.sqrt(EARTH_R_KM**2 + GEO_R_KM**2 - 2 * EARTH_R_KM * GEO_R_KM * math.cos(gamma))
    vza = math.asin(GEO_R_KM * math.sin(gamma) / slant)
    dx = nominal_km * slant / GEO_ALT_KM
    return {"dx_km": dx, "dy_km": dx / math.cos(vza), "viewing_zenith_deg": math.degrees(vza)}


def pixel_occupancy(
    lat: np.ndarray,
    lon: np.ndarray,
    capacity: np.ndarray,
    dx_km: float,
    dy_km: float,
    draws: int,
    seed: int,
) -> dict[str, float]:
    """Monte Carlo over unknown grid phase: distinct pixels occupied and the capacity-weighted
    effective number of independent pixels (1 / Σ pixel-share²)."""
    rng = np.random.default_rng(seed)
    lat0 = float(np.mean(lat))
    x = np.radians(lon - lon.mean()) * EARTH_R_KM * math.cos(math.radians(lat0))
    y = np.radians(lat - lat0) * EARTH_R_KM
    w = np.asarray(capacity, dtype=float) / np.sum(capacity)
    distinct, eff = [], []
    for _ in range(draws):
        ox, oy = rng.uniform(0, dx_km), rng.uniform(0, dy_km)
        cells = list(
            zip(
                np.floor((x + ox) / dx_km).astype(int),
                np.floor((y + oy) / dy_km).astype(int),
                strict=True,
            )
        )
        share = pd.Series(w).groupby(pd.Series(cells, dtype=object)).sum()
        distinct.append(len(share))
        eff.append(1 / float((share**2).sum()))
    return {
        "distinct_pixels_mean": float(np.mean(distinct)),
        "distinct_pixels_min": int(np.min(distinct)),
        "distinct_pixels_max": int(np.max(distinct)),
        "effective_independent_pixels": float(np.mean(eff)),
    }


def classify_h2(m: dict[str, float], criteria: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Apply the pre-defined H2 criteria (STRONG → PLAUSIBLE → WEAK)."""
    detail = {}
    for level in ("STRONG", "PLAUSIBLE"):
        c = criteria[level]
        checks = {
            "effective_independent_pixels": m["effective_independent_pixels"]
            >= c["effective_independent_pixels_min"],
            "weighted_mean_pairwise_km": m["weighted_mean_pairwise_km"]
            >= c["weighted_mean_pairwise_km_min"],
            "major_ew_span_km": m["major_ew_span_km"] >= c["major_ew_span_km_min"],
            "normalised_hhi": m["normalised_hhi"] <= c["normalised_hhi_max"],
            "p_capable_circuits": m["p_capable_circuits"] >= c["p_capable_circuits_min"],
        }
        detail[level] = checks
        if all(checks.values()):
            return level, detail
    return "WEAK", detail
