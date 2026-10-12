"""Simulated-vs-observed comparison metrics (E2)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def flow_metrics(sim: pd.Series, obs: pd.Series, direction_threshold: float | None = None) -> dict:
    """MAE, RMSE, bias (sim − obs), Pearson r and, if a threshold is given, direction agreement.

    Direction agreement counts only observations with |obs| ≥ threshold, so that sign noise
    around zero flow is not scored.
    """
    j = pd.concat([sim.rename("sim"), obs.rename("obs")], axis=1).dropna()
    n = len(j)
    if n == 0:
        return {"n": 0}
    err = j["sim"] - j["obs"]
    out = {
        "n": n,
        "mae": float(err.abs().mean()),
        "rmse": float(np.sqrt((err**2).mean())),
        "bias": float(err.mean()),
        "obs_mean_abs": float(j["obs"].abs().mean()),
        "r": float(np.corrcoef(j["sim"], j["obs"])[0, 1]) if n > 2 and j["obs"].std() > 0 else None,
    }
    out["nmae"] = out["mae"] / out["obs_mean_abs"] if out["obs_mean_abs"] > 0 else None
    if direction_threshold is not None:
        sig = j[j["obs"].abs() >= direction_threshold]
        out["direction_n"] = len(sig)
        out["direction_agreement"] = (
            float((np.sign(sig["sim"]) == np.sign(sig["obs"])).mean()) if len(sig) else None
        )
    return out
