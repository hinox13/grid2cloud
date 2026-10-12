"""E5d — paired synthetic states for response supervision (static metadata only).

Base states come from the E5c envelope sampler (`envelope_e5c.E5cLoadGenerator`). For every base
state, three pairs (pv, battery, load) are drawn; in each pair member B equals member A in every
injection except ONE controllable element. Perturbation magnitudes are drawn from the
pre-registered small / moderate / large classes (configs/experiments/e5d_response_training.yaml
`response_pairs`), defined from static capacities and envelope bounds — never from real ramps.
No real operating, satellite or weather value is read (`SOURCES_READ` ⊆ `ALLOWED_SOURCES`).
"""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import pandas as pd
import yaml

from cloud2grid.scenarios import envelope as e5b
from cloud2grid.scenarios import envelope_e5c as e5c

E5D_CFG = "configs/experiments/e5d_response_training.yaml"
ALLOWED_SOURCES = e5c.ALLOWED_SOURCES | {E5D_CFG}
SOURCES_READ = e5b.SOURCES_READ
TYPES = ("pv", "battery", "load")


def load_config() -> dict[str, Any]:
    if E5D_CFG not in ALLOWED_SOURCES:
        raise PermissionError(E5D_CFG)
    SOURCES_READ.add(E5D_CFG)
    return yaml.safe_load((e5b.REPO_ROOT / E5D_CFG).read_text())


def base_states(n: int, seed: int) -> pd.DataFrame:
    """E5c envelope states (loads, battery, zero-inflated generation), unchanged sampler."""
    return e5c.E5cLoadGenerator().sample(n, seed)


def injection_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c.startswith(("P:", "Q:"))]


def base_hash(row: pd.Series, cols: list[str]) -> str:
    """Identity of a base state: its full injection vector (rounded to 1e-9 MW)."""
    v = np.round(row[cols].to_numpy(dtype=float), 9) + 0.0  # + 0.0: no signed zeros
    return hashlib.sha256(v.tobytes()).hexdigest()[:16]


def _draw_class(rng: np.random.Generator, classes: dict[str, dict]) -> str:
    names = list(classes)
    p = np.array([classes[k]["p"] for k in names], dtype=float)
    return names[rng.choice(len(names), p=p / p.sum())]


def _move(rng: np.random.Generator, a: float, mag: float, lo: float, hi: float) -> float:
    """a ± mag (direction ½/½); flip if outside [lo, hi]; if both are, clip to the roomier side."""
    up = rng.random() < 0.5
    cands = (a + mag, a - mag) if up else (a - mag, a + mag)
    for c in cands:
        if lo - 1e-12 <= c <= hi + 1e-12:
            return float(np.clip(c, lo, hi))
    return float(hi if (hi - a) >= (a - lo) else lo)


def response_pairs(base: pd.DataFrame, seed: int, set_name: str) -> pd.DataFrame:
    """One row per STATE: probe_id, probe_type, magnitude_class, member (A/B), node, x_mw
    (Δ net withdrawal B − A at the perturbed node), base_id, base_hash and the full injection
    vector (P:/Q: columns)."""
    cfg = load_config()
    c5 = e5c.load_config()
    env = e5b.build_envelope()
    rp = cfg["response_pairs"]
    mags = rp["magnitudes"]
    rng = np.random.default_rng([seed, 7_000_002])
    gen_nodes = list(c5["representation"]["gen_buses"].values())
    cap_pv = float(mags["pv"]["capacity_mw"])
    batt = env["cfg"]["storage"]["node"]
    cap_b = float(mags["battery"]["capacity_mw"])
    el = env["elements"]
    loads = el[el.element.str.startswith("load ")].set_index("node")[["min_mw", "max_mw"]]
    inj = injection_columns(base)
    rows: list[dict] = []
    for i, a in base[inj].reset_index(drop=True).iterrows():
        h = base_hash(a, inj)
        # --- pv: total LBUZ generation, equal split, Q = 0
        g_a = float(-sum(a[f"P:{n}"] for n in gen_nodes))
        cls = _draw_class(rng, mags["pv"]["classes"])
        if cls == "on_off":
            g_b = 0.0 if g_a > 0 else float(rng.uniform(0.05, cap_pv))
        else:
            g_b = _move(
                rng, g_a, rng.uniform(*mags["pv"]["classes"][cls]["abs_delta_mw"]), 0.0, cap_pv
            )
        b = a.copy()
        for n in gen_nodes:
            b[f"P:{n}"] = -g_b / len(gen_nodes)
        rows += _pair(set_name, i, "pv", cls, "+".join(gen_nodes), a, b, -(g_b - g_a), h)
        # --- battery: CHAP31, unity pf
        p_a = float(a[f"P:{batt}"])
        cls = _draw_class(rng, mags["battery"]["classes"])
        mag = rng.uniform(*mags["battery"]["classes"][cls]["abs_delta_mw"])
        p_b = _move(rng, p_a, mag, min(-cap_b, p_a), max(cap_b, p_a))
        b = a.copy()
        b[f"P:{batt}"] = p_b
        rows += _pair(set_name, i, "battery", cls, batt, a, b, p_b - p_a, h)
        # --- load: one primary node, power factor kept
        node = loads.index[rng.integers(len(loads))]
        lo, hi = loads.loc[node, "min_mw"], loads.loc[node, "max_mw"]
        p0 = float(a[f"P:{node}"])
        cls = _draw_class(rng, mags["load"]["classes"])
        frac = rng.uniform(*mags["load"]["classes"][cls]["abs_delta_frac_of_max"])
        mag = max(float(mags["load"]["min_abs_delta_mw"]), frac * hi)
        p1 = _move(rng, p0, mag, min(lo, p0), max(hi, p0))
        q_ratio = a[f"Q:{node}"] / p0 if abs(p0) > 1e-9 else 0.29
        b = a.copy()
        b[f"P:{node}"], b[f"Q:{node}"] = p1, p1 * q_ratio
        rows += _pair(set_name, i, "load", cls, node, a, b, p1 - p0, h)
    return pd.DataFrame(rows)


def _pair(
    set_name: str,
    i: int,
    kind: str,
    cls: str,
    node: str,
    a: pd.Series,
    b: pd.Series,
    x: float,
    h: str,
) -> list[dict]:
    pid = f"{set_name}_{kind}_{i:05d}"
    return [
        {
            "probe_id": pid,
            "probe_type": kind,
            "magnitude_class": cls,
            "member": m,
            "node": node,
            "x_mw": x,
            "base_id": i,
            "base_hash": h,
            **s.to_dict(),
        }
        for m, s in (("A", a), ("B", b))
    ]


def changed_elements(pairs: pd.DataFrame, tol: float = 1e-12) -> pd.Series:
    """Per probe_id: the injection columns that differ between A and B (one-variable check)."""
    inj = injection_columns(pairs)
    a = pairs[pairs.member == "A"].set_index("probe_id")[inj]
    b = pairs[pairs.member == "B"].set_index("probe_id").reindex(a.index)[inj]
    diff = (a - b).abs() > tol
    return diff.apply(lambda r: sorted(c for c in inj if r[c]), axis=1)
