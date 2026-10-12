"""Weather-event discovery from satellite irradiance and estimated PV only (README §18–19).

Inputs are weather/PV quantities; GENCO output, AC solver results, network loading and any
later model performance are never read here. Thresholds come from a config written before
any satellite data were processed (configs/experiments/e3_event_discovery.yaml).

Per 15-minute slot (`slot_features`):
    fleet_cf, fleet_ramp (Δ over one slot), max_asset_ramp, frac_capacity_affected,
    mean_kc (clear-sky index at assets), field statistics of the analysis box
    (mean/std of kc, mean |∇kc| per km, fraction clear/cloudy).
Per window of W consecutive valid slots (`window_features`):
    mean/temporal-std of kc, max |ramp|, significant ramps, sign changes, ramp persistence,
    event duration, recovery time, field transition (start → end), trend monotonicity.
Classes A–E (`classify`), ranking and non-overlapping greedy selection (`select`) are
deterministic: ties break on window start time.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

CLASSES = {
    "A": "clear_sky_control",
    "B": "fast_ramp",
    "C": "broken_cloud",
    "D": "coherent_transition",
    "E": "overcast_control",
}


def slot_features(
    asset_ts: pd.DataFrame, field_ts: pd.DataFrame, step_min: int, thr: dict[str, float]
) -> pd.DataFrame:
    """`asset_ts`: slot, asset_id, cf, active_capacity_mw, kc, usable(bool).
    `field_ts`: slot, field_mean_kc, field_std_kc, field_grad_kc_per_km, field_frac_clear,
    field_frac_cloudy, field_frac_valid, elevation.
    """
    a = asset_ts[asset_ts["active_capacity_mw"] > 0].sort_values(["asset_id", "slot"]).copy()
    a["dcf"] = a.groupby("asset_id")["cf"].diff()
    gap = a.groupby("asset_id")["slot"].diff() != pd.Timedelta(minutes=step_min)
    a.loc[gap, "dcf"] = np.nan
    a["w_cf"] = a["cf"] * a["active_capacity_mw"]
    a["affected_cap"] = np.where(
        a["dcf"].abs() >= thr["asset_ramp_affected"], a["active_capacity_mw"], 0.0
    )
    g = a.groupby("slot")
    f = pd.DataFrame(
        {
            "fleet_capacity_mw": g["active_capacity_mw"].sum(),
            "fleet_cf": g["w_cf"].sum(min_count=1) / g["active_capacity_mw"].sum(),
            "max_asset_ramp": g["dcf"].apply(lambda s: s.abs().max()),
            "frac_capacity_affected": g["affected_cap"].sum() / g["active_capacity_mw"].sum(),
            "mean_kc": g["kc"].mean(),
            "assets_usable": g["usable"].all(),
        }
    )
    f = f.join(field_ts.set_index("slot"), how="left").sort_index()
    f["fleet_ramp"] = f["fleet_cf"].diff()
    f.loc[f.index.to_series().diff() != pd.Timedelta(minutes=step_min), "fleet_ramp"] = np.nan
    f["valid"] = f["assets_usable"].fillna(False) & (
        f["field_frac_valid"] >= thr["min_field_valid"]
    )
    return f


def _runs(signs: np.ndarray) -> int:
    best = cur = 0
    prev = 0
    for s in signs:
        if s != 0 and s == prev:
            cur += 1
        else:
            cur = 1 if s != 0 else 0
        prev = s
        best = max(best, cur)
    return best


def window_features(f: pd.DataFrame, w: int, step_min: int, thr: dict[str, float]) -> pd.DataFrame:
    """Features for every window of `w` consecutive, valid, daylight slots."""
    f = f.sort_index()
    idx = f.index
    rows = []
    for i in range(len(f) - w + 1):
        win = f.iloc[i : i + w]
        if win.index[-1] - win.index[0] != pd.Timedelta(minutes=step_min * (w - 1)):
            continue
        if not win["valid"].all() or (win["elevation"] < thr["min_elevation_deg"]).any():
            continue
        ramps = win["fleet_ramp"].iloc[1:].to_numpy()
        sig = np.where(np.abs(ramps) >= thr["significant_ramp"], np.sign(ramps), 0)
        nz = sig[sig != 0]
        cf = win["fleet_cf"].to_numpy()
        j = int(np.nanargmin(ramps)) if np.isfinite(ramps).any() else None
        recovery = np.nan
        if j is not None and ramps[j] <= -thr["significant_ramp"]:
            pre = cf[j]
            after = np.where(cf[j + 1 :] >= pre - thr["recovery_tolerance"])[0]
            recovery = float((after[0] + 1) * step_min) if len(after) else np.nan
        third = max(1, w // 3)
        fk = win["field_mean_kc"].to_numpy()
        t = np.arange(w)
        rho = pd.Series(fk).corr(pd.Series(t), method="spearman") if np.nanstd(fk) > 1e-9 else 0.0
        rows.append(
            {
                "start": idx[i],
                "end": win.index[-1],
                "fleet_capacity_mw": float(win["fleet_capacity_mw"].mean()),
                "mean_kc": float(win["mean_kc"].mean()),
                "std_kc_time": float(win["mean_kc"].std()),
                "mean_cf": float(np.nanmean(cf)),
                "max_abs_ramp": float(np.nanmax(np.abs(ramps))),
                "max_two_step_ramp": float(np.nanmax(np.abs(cf[2:] - cf[:-2])))
                if w > 2
                else np.nan,
                "max_asset_ramp": float(win["max_asset_ramp"].max()),
                "max_frac_capacity_affected": float(win["frac_capacity_affected"].max()),
                "n_significant_ramps": int((sig != 0).sum()),
                "n_sign_changes": int((np.diff(nz) != 0).sum()) if len(nz) > 1 else 0,
                "ramp_persistence": _runs(sig),
                "event_duration_min": float((sig != 0).sum() * step_min),
                "recovery_min": recovery,
                "field_mean_kc": float(np.nanmean(fk)),
                "field_mean_std_kc": float(win["field_std_kc"].mean()),
                "field_max_grad": float(win["field_grad_kc_per_km"].max()),
                "field_kc_start": float(np.nanmean(fk[:third])),
                "field_kc_end": float(np.nanmean(fk[-third:])),
                "field_frac_clear_start": float(win["field_frac_clear"].iloc[:third].mean()),
                "field_frac_cloudy_start": float(win["field_frac_cloudy"].iloc[:third].mean()),
                "field_frac_clear_end": float(win["field_frac_clear"].iloc[-third:].mean()),
                "field_frac_cloudy_end": float(win["field_frac_cloudy"].iloc[-third:].mean()),
                "field_trend_rho": float(rho) if np.isfinite(rho) else 0.0,
            }
        )
    return pd.DataFrame(rows)


def classify(wf: pd.DataFrame, c: dict[str, dict[str, float]]) -> pd.DataFrame:
    """Boolean membership per class (a window may qualify for several) and a class score."""
    if wf.empty:
        return wf.assign(**{k: pd.Series(dtype=bool) for k in CLASSES})
    A, B, C, D, E = (c[k] for k in "ABCDE")
    out = wf.copy()
    out["A"] = (
        (out.mean_kc >= A["min_mean_kc"])
        & (out.std_kc_time <= A["max_std_kc_time"])
        & (out.field_mean_std_kc <= A["max_field_std_kc"])
        & (out.max_abs_ramp <= A["max_abs_ramp"])
    )
    out["B"] = (out.max_abs_ramp >= B["min_one_step_ramp"]) | (
        out.max_two_step_ramp >= B["min_two_step_ramp"]
    )
    out["C"] = (
        (out.n_sign_changes >= C["min_sign_changes"])
        & out.mean_kc.between(C["kc_min"], C["kc_max"])
        & (out.n_significant_ramps >= C["min_significant_ramps"])
    )
    clear_to_cloud = (out.field_frac_clear_start >= D["min_frac_start"]) & (
        out.field_frac_cloudy_end >= D["min_frac_end"]
    )
    cloud_to_clear = (out.field_frac_cloudy_start >= D["min_frac_start"]) & (
        out.field_frac_clear_end >= D["min_frac_end"]
    )
    out["D"] = (
        (clear_to_cloud | cloud_to_clear)
        & (out.field_trend_rho.abs() >= D["min_abs_trend_rho"])
        & (out.field_max_grad >= D["min_field_grad"])
    )
    out["E"] = (
        (out.mean_kc <= E["max_mean_kc"])
        & (out.std_kc_time <= E["max_std_kc_time"])
        & (out.field_mean_std_kc <= E["max_field_std_kc"])
    )
    out["score_A"] = out.mean_kc - out.std_kc_time - out.field_mean_std_kc
    out["score_B"] = np.maximum(out.max_abs_ramp, out.max_two_step_ramp)
    out["score_C"] = out.n_sign_changes + out.std_kc_time
    out["score_D"] = out.field_trend_rho.abs() * (out.field_kc_start - out.field_kc_end).abs()
    out["score_E"] = -(out.mean_kc + out.std_kc_time + out.field_mean_std_kc)
    return out


def select(cl: pd.DataFrame, per_class: int, min_separation_h: float) -> pd.DataFrame:
    """Top windows per class, greedy by score (ties → earlier start), non-overlapping within a
    class and at least `min_separation_h` apart."""
    picks = []
    for k, name in CLASSES.items():
        cand = cl[cl[k]].sort_values([f"score_{k}", "start"], ascending=[False, True])
        chosen: list[pd.Series] = []
        for _, r in cand.iterrows():
            if all(
                abs((r["start"] - o["start"]).total_seconds()) >= min_separation_h * 3600
                for o in chosen
            ):
                chosen.append(r)
            if len(chosen) >= per_class:
                break
        for rank, r in enumerate(chosen, 1):
            d = r.to_dict()
            d.update(
                {
                    "event_class": k,
                    "class_name": name,
                    "rank_in_class": rank,
                    "score": float(r[f"score_{k}"]),
                }
            )
            picks.append(d)
    cols = ["event_class", "class_name", "rank_in_class", "start", "end", "score"]
    df = pd.DataFrame(picks)
    if df.empty:
        return pd.DataFrame(columns=cols)
    df["event_id"] = [
        f"{r.event_class}{r.rank_in_class:02d}_{r.start:%Y%m%dT%H%M}" for r in df.itertuples()
    ]
    return df[
        ["event_id", *cols]
        + [
            c
            for c in df.columns
            if c not in cols and c != "event_id" and not c.startswith("score_") and c not in CLASSES
        ]
    ]


def field_stats(
    kc: np.ndarray, valid: np.ndarray, dy_km: float, dx_km: float, thr: dict[str, Any]
) -> dict[str, float]:
    """Analysis-box statistics of one slot's clear-sky-index field (NaN where invalid)."""
    k = np.where(valid, kc, np.nan)
    gy, gx = np.gradient(k, dy_km, dx_km)
    grad = np.sqrt(gx**2 + gy**2)
    n = np.isfinite(k).sum()
    return {
        "field_mean_kc": float(np.nanmean(k)) if n else np.nan,
        "field_std_kc": float(np.nanstd(k)) if n else np.nan,
        "field_grad_kc_per_km": float(np.nanmean(grad)) if np.isfinite(grad).any() else np.nan,
        "field_frac_clear": float(np.nansum(k >= thr["kc_clear"]) / n) if n else np.nan,
        "field_frac_cloudy": float(np.nansum(k <= thr["kc_cloudy"]) / n) if n else np.nan,
        "field_frac_valid": float(n / k.size),
    }


def params_hash(cfg: dict[str, Any]) -> str:
    import hashlib
    import json

    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:16]
