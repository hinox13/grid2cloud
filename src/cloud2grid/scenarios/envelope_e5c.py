"""E5c — generator-aware envelope sampler and paired physics probes (static metadata only).

Loads and the CHAP31 battery come from the E5b envelope sampler unchanged
(`cloud2grid.scenarios.envelope`). Generation at LBUZ31/32/33 is re-sampled with the
pre-registered zero-inflated level mixture (configs/experiments/e5c_generator_aware.yaml):
solar and wind levels each have exact-zero and exact-full mass, so Pgen = 0 occurs often.
No real operating, satellite or weather value is read (`SOURCES_READ` ⊆ `ALLOWED_SOURCES`).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import yaml

from cloud2grid.scenarios import envelope as e5b

E5C_CFG = "configs/experiments/e5c_generator_aware.yaml"
ALLOWED_SOURCES = e5b.ALLOWED_SOURCES | {E5C_CFG}
SOURCES_READ = e5b.SOURCES_READ


def load_config() -> dict[str, Any]:
    if E5C_CFG not in ALLOWED_SOURCES:
        raise PermissionError(E5C_CFG)
    SOURCES_READ.add(E5C_CFG)
    return yaml.safe_load((e5b.REPO_ROOT / E5C_CFG).read_text())


def level_mixture(rng: np.random.Generator, n: int, mix: dict[str, dict]) -> np.ndarray:
    """Draw n levels in [0, 1] from the pre-registered mixture (exact-zero / exact-full mass)."""
    names = list(mix)
    p = np.array([mix[k]["probability"] for k in names], dtype=float)
    if not np.isclose(p.sum(), 1.0):
        raise ValueError("mixture probabilities must sum to 1")
    comp = rng.choice(len(names), size=n, p=p)
    out = np.empty(n)
    for j, k in enumerate(names):
        m = comp == j
        spec = mix[k]
        out[m] = spec["value"] if "value" in spec else rng.uniform(*spec["uniform"], m.sum())
    return out


class E5cLoadGenerator(e5b.EnvelopeLoadGenerator):
    """E5b envelope (loads, battery) + zero-inflated generation at the LBUZ buses.

    Generation is still written as negative demand for datakit's solvers (PowerModels would turn a
    generator bus into a PV bus); the tables are re-encoded to explicit generator nodes after the
    solve (cloud2grid.genco.generator_aware)."""

    def __init__(self) -> None:
        super().__init__()
        self.cfg5c = load_config()

    def sample(self, n: int, seed: int) -> pd.DataFrame:
        df = super().sample(n, seed)
        g = self.cfg5c["envelope"]
        mix = g["generation_sampling"]["per_resource_level_mixture"]
        rng = np.random.default_rng([seed, 5_000_003])  # independent stream for generation
        s_lvl, w_lvl = level_mixture(rng, n, mix), level_mixture(rng, n, mix)
        cap = g["generation_capacity"]
        total = s_lvl * cap["solar_mw"] + w_lvl * cap["wind_mw"]
        nodes = list(self.cfg5c["representation"]["gen_buses"].values())
        for node in nodes:
            df[f"P:{node}"] = -total / len(nodes)
            df[f"Q:{node}"] = 0.0
        df["solar_level"], df["wind_level"] = s_lvl, w_lvl
        df["generation_mw"] = total
        return df


# ------------------------------------------------------------------ paired physics probes
def probe_pairs(base: pd.DataFrame, seed: int, cfg: dict[str, Any] | None = None) -> pd.DataFrame:
    """For every base state: three pairs (pv, battery, load), each changing ONE input.

    Returns one row per STATE: probe_id, probe_type, member (A/B), perturbed node, x (Δ net
    withdrawal B − A at that node, MW) and the full injection vector (P:/Q: columns)."""
    cfg = cfg or load_config()
    env = e5b.load_config()
    rng = np.random.default_rng([seed, 7_000_001])
    gen_nodes = list(cfg["representation"]["gen_buses"].values())
    cap_total = sum(cfg["envelope"]["generation_capacity"].values())
    half = cap_total / 2
    batt = env["storage"]["node"]
    bound = env["storage"]["bound_mw"]
    loads = [n for s in env["primary_sites"].values() for n in s["node_shares"]]
    inj = [c for c in base.columns if c.startswith(("P:", "Q:"))]
    rows = []
    for i, a in base[inj].reset_index(drop=True).iterrows():
        # --- pv
        g_a = -sum(a[f"P:{n}"] for n in gen_nodes)
        d = rng.uniform(1.0, half)
        g_b = float(np.clip(g_a + d if g_a <= half else g_a - d, 0.0, cap_total))
        b = a.copy()
        for n in gen_nodes:
            b[f"P:{n}"] = -g_b / len(gen_nodes)
        rows += _pair(i, "pv", "+".join(gen_nodes), a, b, -(g_b - g_a))
        # --- battery
        p_a = a[f"P:{batt}"]
        d = rng.uniform(5.0, 25.0)
        p_b = float(np.clip(p_a - np.sign(p_a) * d if p_a != 0 else p_a + d, -bound, bound))
        b = a.copy()
        b[f"P:{batt}"] = p_b
        rows += _pair(i, "battery", batt, a, b, p_b - p_a)
        # --- load (one primary node)
        node = loads[rng.integers(len(loads))]
        p0 = a[f"P:{node}"]
        mag = max(0.5, rng.uniform(0.2, 0.6) * abs(p0))
        sign = 1.0 if p0 < 0.5 else rng.choice([-1.0, 1.0])
        p1 = p0 + sign * mag
        b = a.copy()
        q_ratio = a[f"Q:{node}"] / p0 if abs(p0) > 1e-9 else 0.29  # keep the state's power factor
        b[f"P:{node}"], b[f"Q:{node}"] = p1, p1 * q_ratio
        rows += _pair(i, "load", node, a, b, p1 - p0)
    return pd.DataFrame(rows)


def _pair(i: int, kind: str, node: str, a: pd.Series, b: pd.Series, x: float) -> list[dict]:
    pid = f"{kind}_{i:04d}"
    return [
        {"probe_id": pid, "probe_type": kind, "member": m, "node": node, "x_mw": x, **s.to_dict()}
        for m, s in (("A", a), ("B", b))
    ]
