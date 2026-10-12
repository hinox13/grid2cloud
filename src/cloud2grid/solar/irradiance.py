"""MDSSFTD → GHI / DHI / DNI at an asset (inputs to pvlib).

MDSSFTD provides the total downwelling surface shortwave flux (DSSF_TOT, W/m², 0.3–4 µm) and
the diffuse fraction fD = diffuse / total (PUM §5.1: "the diffuse fraction defined as the ratio
of the diffuse component of the solar irradiance to the total"). Hence directly:

    GHI = DSSF_TOT
    DHI = fD × GHI
    DNI = (GHI − DHI) / cos(θz)                 (closure; θz = solar zenith)

No decomposition model is needed — the product's own diffuse fraction is the better-supported
route. DNI is computed with `pvlib.irradiance.dni`, which applies the physical limits: DNI = 0
for θz ≥ `zenith_zero_dni_deg`, and DNI ≤ `clearsky_tolerance` × clear-sky DNI for
θz ≥ `zenith_clearsky_limit_deg` (where cos θz makes the closure ill-conditioned).

Solar position is evaluated at the pixel's ACQUISITION time (slot + line offset, PUM §6.3),
not at the nominal slot. Night (product status NIGHT) is exactly zero.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pvlib


def solar_position(
    times: pd.DatetimeIndex, lat: float, lon: float, altitude_m: float = 0.0
) -> pd.DataFrame:
    return pvlib.solarposition.get_solarposition(times, lat, lon, altitude=altitude_m)


def components(
    times: pd.DatetimeIndex,
    ghi: np.ndarray,
    diffuse_fraction: np.ndarray,
    lat: float,
    lon: float,
    cfg: dict[str, Any],
) -> pd.DataFrame:
    """GHI, DHI, DNI (W/m²) and solar geometry for one location over `times` (UTC)."""
    times = pd.DatetimeIndex(times)
    sp = solar_position(times, lat, lon)
    ghi = np.clip(np.asarray(ghi, dtype=float), 0.0, None)
    fd = np.asarray(diffuse_fraction, dtype=float)
    fd = np.where(np.isfinite(fd), np.clip(fd, 0.0, 1.0), np.nan)
    dhi = np.where(ghi == 0.0, 0.0, fd * ghi)
    cs = pvlib.location.Location(lat, lon).get_clearsky(times, model="ineichen", solar_position=sp)
    dni = pvlib.irradiance.dni(
        pd.Series(ghi, index=times),
        pd.Series(dhi, index=times),
        sp["zenith"],
        dni_clear=cs["dni"],
        clearsky_tolerance=cfg["clearsky_tolerance"],
        zenith_threshold_for_zero_dni=cfg["zenith_zero_dni_deg"],
        zenith_threshold_for_clearsky_limit=cfg["zenith_clearsky_limit_deg"],
    )
    dni = dni.fillna(0.0).clip(lower=0.0).where(np.isfinite(dhi), np.nan)
    # Where DNI was limited, restore closure by assigning the remainder to diffuse.
    cosz = np.cos(np.radians(sp["zenith"].to_numpy()))
    beam_h = np.clip(dni.to_numpy() * np.clip(cosz, 0, None), 0.0, None)
    dhi_closed = np.where(np.isfinite(dhi), np.clip(ghi - beam_h, 0.0, None), np.nan)
    return pd.DataFrame(
        {
            "ghi": ghi,
            "dhi": dhi_closed,
            "dni": dni.to_numpy(),
            "diffuse_fraction": fd,
            "ghi_clearsky": cs["ghi"].to_numpy(),
            "clearsky_index": _ratio(ghi, cs["ghi"].to_numpy(), min_denominator=10.0),
            "zenith": sp["zenith"].to_numpy(),
            "apparent_zenith": sp["apparent_zenith"].to_numpy(),
            "azimuth": sp["azimuth"].to_numpy(),
            "elevation": sp["elevation"].to_numpy(),
        },
        index=times,
    )


def _ratio(num: np.ndarray, den: np.ndarray, min_denominator: float) -> np.ndarray:
    """num / den where den > min_denominator (clear-sky index undefined near sunrise/sunset)."""
    out = np.full(np.shape(num), np.nan)
    ok = den > min_denominator
    np.divide(num, den, out=out, where=ok)
    return out
