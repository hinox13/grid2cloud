"""Generic, capacity-normalised PV model built from pvlib components (README §12–13).

This is a FORCING model, not a fitted generation estimator: parameters are documented UK
utility-scale conventions (configs/experiments/e3_pv_model.yaml), never calibrated to UKPN data.

Per asset, with unit AC capacity (pac0 = 1):

    POA          pvlib.irradiance.get_total_irradiance (Hay–Davies sky diffuse, albedo)
    IAM          pvlib.iam.ashrae on the beam component
    T_cell       pvlib.temperature.faiman (fixed ambient / wind: no met data used)
    P_dc         pvlib.pvsystem.pvwatts_dc, pdc0 = dc_ac_ratio, γ_pdc
    losses       pvlib.pvsystem.pvwatts_losses (soiling, wiring, …) — applied to P_dc
    P_ac         pvlib.inverter.pvwatts, pac0 = 1 → clipped at 1 (export limit)

    capacity_factor(t) = P_ac(t) ∈ [0, 1]
    P(asset, t) [MW]   = capacity_factor(t) × active_capacity(asset, t)

ECR registered capacity is the AC (export) rating, so clipping at 1 is the AC/DC convention.
Output is labelled "satellite-driven estimated PV generation" — never "measured".
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pvlib


def capacity_factor(irr: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    """Capacity factor from `solar.irradiance.components` output and model parameters `p`."""
    dni_extra = pvlib.irradiance.get_extra_radiation(irr.index)
    airmass = pvlib.atmosphere.get_relative_airmass(irr["apparent_zenith"])
    poa = pvlib.irradiance.get_total_irradiance(
        surface_tilt=p["tilt_deg"],
        surface_azimuth=p["azimuth_deg"],
        solar_zenith=irr["apparent_zenith"],
        solar_azimuth=irr["azimuth"],
        dni=irr["dni"],
        ghi=irr["ghi"],
        dhi=irr["dhi"],
        dni_extra=dni_extra,
        airmass=airmass,
        albedo=p["albedo"],
        model=p["sky_diffuse_model"],
    )
    aoi = pvlib.irradiance.aoi(
        p["tilt_deg"], p["azimuth_deg"], irr["apparent_zenith"], irr["azimuth"]
    )
    iam = pvlib.iam.ashrae(aoi, b=p["iam_ashrae_b"])
    effective = (poa["poa_direct"] * iam + poa["poa_diffuse"]).clip(lower=0)
    t_cell = pvlib.temperature.faiman(
        poa["poa_global"].clip(lower=0), p["temp_air_c"], p["wind_speed_ms"]
    )
    pdc0 = p["dc_ac_ratio"]  # per unit of AC capacity
    pdc = pvlib.pvsystem.pvwatts_dc(effective, t_cell, pdc0, p["gamma_pdc"])
    loss = pvlib.pvsystem.pvwatts_losses(**p["losses_pct"]) / 100.0
    pdc = pdc * (1 - loss)
    pac = pvlib.inverter.pvwatts(
        pdc, pdc0=1.0 / p["inverter_eta_nom"], eta_inv_nom=p["inverter_eta_nom"]
    )
    cf = pd.Series(np.clip(np.asarray(pac, dtype=float), 0.0, 1.0), index=irr.index)
    cf[irr["ghi"].to_numpy() == 0.0] = 0.0
    return cf.where(np.isfinite(irr["ghi"].to_numpy()) & np.isfinite(irr["dhi"].to_numpy()))
