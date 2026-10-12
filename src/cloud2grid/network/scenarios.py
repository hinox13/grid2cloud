"""Named network/measurement-interpretation variants of a validated baseline (E2 sensitivity).

A variant config `extends:` the baseline file and declares `scenario.changes`. The baseline file
is never modified. Supported change types (each needs documented evidence in the config):

    measurement_scale  multiply one metered input series by a factor resolved from data:
        capacity_ratio          published capacity / observed symmetric operating ceiling
                                (uses no validation target)
        kcl_regression_heldout  coefficient of the series in a busbar power balance fitted on
                                timestamps NOT used for validation (a CALIBRATION experiment)
    observed_outages   per timestamp, take a metered line out of service when it reads
                       |P| < max_abs_observed_mw while the all-closed model carries more than
                       min_abs_model_mw; that (line, timestamp) pair is then excluded from metrics
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from cloud2grid.network import measurements as ms


def load_config(path: Path) -> dict[str, Any]:
    """Load a scenario config, resolving `extends:` (deep merge; `scenario` is replaced)."""
    path = Path(path)
    cfg = yaml.safe_load(path.read_text())
    parent = cfg.pop("extends", None)
    if parent is None:
        return cfg
    base = load_config(path.parent / parent)
    return _merge(base, cfg)


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in over.items():
        if key != "scenario" and isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def changes(cfg: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [c for c in cfg.get("scenario", {}).get("changes", []) if c["type"] == kind]


# ------------------------------------------------------------------- measurement scale


def symmetric_ceiling(monthly: pd.DataFrame, line: str) -> dict[str, float]:
    """Median over published months of the monthly max |P| (the observed operating ceiling)."""
    m = monthly[(monthly["ltds_line_name"] == line) & (monthly["redacted"].astype(str) == "False")]
    peak = (
        pd.concat(
            [m["active_power_month_min_mw"].abs(), m["active_power_month_max_mw"].abs()], axis=1
        )
        .max(axis=1)
        .dropna()
    )
    return {
        "median_monthly_max_abs_mw": float(peak.median()),
        "n_months": int(len(peak)),
        "min": float(peak.min()),
        "max": float(peak.max()),
    }


def kcl_coefficient(
    s: ms.Series, cfg: dict[str, Any], change: dict[str, Any], exclude: pd.DatetimeIndex
) -> dict[str, Any]:
    """OLS of observed import on metered busbar outflows; returns the target series' coefficient.

    Fitted ONLY on timestamps not in `exclude` (the validation set).
    """
    imp = ms.observed_import(cfg, s)
    cols = {"imp": imp}
    for term in change["regressors"]:
        if "sum_lines" in term:  # one coefficient for a group (avoids per-circuit overfitting)
            cols[term["name"]] = sum(
                sign * s.circuit_p[ln] for ln, sign in term["sum_lines"].items()
            )
        elif "line" in term:
            cols[term["line"]] = term["sign"] * s.circuit_p[term["line"]]
        else:
            cols[term["transformer"]] = ms.transformer_demand(
                s, term["transformer"], term["positive"]
            )
    d = pd.DataFrame(cols).dropna()
    d = d[~d.index.isin(exclude)]
    names = [c for c in d.columns if c != "imp"]
    a = np.column_stack([d[c] for c in names] + [np.ones(len(d))])
    coef, *_ = np.linalg.lstsq(a, d["imp"].to_numpy(), rcond=None)
    return {
        "coefficients": dict(zip(names + ["intercept"], np.round(coef, 4).tolist(), strict=True)),
        "n_fit": int(len(d)),
        "fit_excludes_validation_timestamps": True,
        "factor": float(coef[names.index(change["series"])]),
    }


def resolve_scales(
    cfg: dict[str, Any], s: ms.Series, monthly: pd.DataFrame, validation_ts: pd.DatetimeIndex
) -> dict[str, dict[str, Any]]:
    """series → {factor, method, evidence} for every measurement_scale change."""
    out = {}
    for ch in changes(cfg, "measurement_scale"):
        if ch["method"] == "capacity_ratio":
            ceil = symmetric_ceiling(monthly, ch["series"])
            factor = ch["published_capacity_mw"] / ceil["median_monthly_max_abs_mw"]
            out[ch["series"]] = {
                "factor": factor,
                "method": ch["method"],
                "evidence": {"published_capacity_mw": ch["published_capacity_mw"], **ceil},
            }
        elif ch["method"] == "kcl_regression_heldout":
            fit = kcl_coefficient(s, cfg, ch, validation_ts)
            out[ch["series"]] = {"factor": fit["factor"], "method": ch["method"], "evidence": fit}
        else:
            raise ValueError(ch["method"])
    return out


def apply_scales(cfg: dict[str, Any], scales: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Copy of cfg with `scale` set on every load input circuit listed in `scales`."""
    out = copy.deepcopy(cfg)
    for spec in out["loads"]:
        for c in spec.get("circuits", []):
            if c["line"] in scales:
                c["scale"] = scales[c["line"]]["factor"]
    return out


# ------------------------------------------------------------------------- outages


def detect_outages(sim: dict[str, float], obs: dict[str, float], rule: dict[str, Any]) -> list[str]:
    """Lines metered at ~0 while the all-closed model carries flow."""
    return sorted(
        line
        for line, o in obs.items()
        if line in sim
        and not np.isnan(o)
        and abs(o) < rule["max_abs_observed_mw"]
        and abs(sim[line]) > rule["min_abs_model_mw"]
    )
