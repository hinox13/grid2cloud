"""Block-bootstrap statistics for E4 (states are autocorrelated: never treated as independent).

All resampling is over BLOCKS (days for satellite-driven families, datakit load scenarios for
S0), with replacement, a fixed seed, and percentile 95 % intervals. Effects are reported as
absolute values, differences, relative differences and intervals — not significance tests.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _block_index(blocks: pd.Series) -> tuple[np.ndarray, list[np.ndarray]]:
    codes, uniq = pd.factorize(blocks, sort=True)
    return uniq, [np.flatnonzero(codes == k) for k in range(len(uniq))]


def _resample_means(
    values: np.ndarray, groups: list[np.ndarray], b: int, rng: np.random.Generator
) -> np.ndarray:
    """Bootstrap distribution of the overall mean, resampling whole blocks."""
    sums = np.array([values[g].sum() for g in groups])
    counts = np.array([len(g) for g in groups])
    pick = rng.integers(0, len(groups), size=(b, len(groups)))
    return sums[pick].sum(axis=1) / counts[pick].sum(axis=1)


def block_mean_ci(
    values: pd.Series, blocks: pd.Series, b: int, seed: int, ci: float = 0.95
) -> dict[str, Any]:
    v = values.to_numpy(float)
    ok = np.isfinite(v)
    _, groups = _block_index(blocks[ok].reset_index(drop=True))
    rng = np.random.default_rng(seed)
    boot = _resample_means(v[ok], groups, b, rng)
    a = (1 - ci) / 2
    return {
        "mean": float(v[ok].mean()),
        "ci_low": float(np.quantile(boot, a)),
        "ci_high": float(np.quantile(boot, 1 - a)),
        "n": int(ok.sum()),
        "blocks": len(groups),
    }


def gap_unpaired(
    a: pd.Series,
    a_blocks: pd.Series,
    c: pd.Series,
    c_blocks: pd.Series,
    b: int,
    seed: int,
    ci: float = 0.95,
) -> dict[str, Any]:
    """Metric(a) − Metric(c) for independent families, each resampled by its own blocks."""
    rng = np.random.default_rng(seed)
    av, cv = a.to_numpy(float), c.to_numpy(float)
    ma, mc = np.isfinite(av), np.isfinite(cv)
    _, ga = _block_index(a_blocks[ma].reset_index(drop=True))
    _, gc = _block_index(c_blocks[mc].reset_index(drop=True))
    ba = _resample_means(av[ma], ga, b, rng)
    bc = _resample_means(cv[mc], gc, b, rng)
    diff, rel = ba - bc, ba / bc - 1
    q = (1 - ci) / 2
    point = av[ma].mean() - cv[mc].mean()
    return {
        "metric_a": float(av[ma].mean()),
        "metric_control": float(cv[mc].mean()),
        "difference": float(point),
        "relative": float(point / cv[mc].mean()),
        "diff_ci": [float(np.quantile(diff, q)), float(np.quantile(diff, 1 - q))],
        "rel_ci": [float(np.quantile(rel, q)), float(np.quantile(rel, 1 - q))],
    }


def gap_paired(
    df: pd.DataFrame, a: str, c: str, block: str, b: int, seed: int, ci: float = 0.95
) -> dict[str, Any]:
    """Paired gap: rows are base timestamps with columns a (S1) and c (control, already
    averaged over control seeds). Days are resampled; the relative gap is a ratio of means."""
    d = df[[a, c, block]].dropna()
    _, groups = _block_index(d[block].reset_index(drop=True))
    rng = np.random.default_rng(seed)
    av, cv = d[a].to_numpy(float), d[c].to_numpy(float)
    pick = rng.integers(0, len(groups), size=(b, len(groups)))
    sa = np.array([av[g].sum() for g in groups])
    sc = np.array([cv[g].sum() for g in groups])
    n = np.array([len(g) for g in groups])
    ma, mc = sa[pick].sum(1) / n[pick].sum(1), sc[pick].sum(1) / n[pick].sum(1)
    q = (1 - ci) / 2
    point = av.mean() - cv.mean()
    return {
        "metric_a": float(av.mean()),
        "metric_control": float(cv.mean()),
        "difference": float(point),
        "relative": float(point / cv.mean()),
        "diff_ci": [float(np.quantile(ma - mc, q)), float(np.quantile(ma - mc, 1 - q))],
        "rel_ci": [float(np.quantile(ma / mc - 1, q)), float(np.quantile(ma / mc - 1, 1 - q))],
        "n_pairs": int(len(d)),
        "blocks": len(groups),
    }


def material(gap: dict[str, Any], rel_threshold: float) -> bool:
    """Pre-registered rule: |relative| ≥ threshold AND the difference CI excludes 0."""
    lo, hi = gap["diff_ci"]
    return abs(gap["relative"]) >= rel_threshold and (lo > 0 or hi < 0)
