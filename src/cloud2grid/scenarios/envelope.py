"""E5b — physics-informed synthetic operating envelope for Sundon (static metadata ONLY).

`build_envelope()` derives, for every controllable element of the Sundon model, a bound and a
sampling rule from STATIC / PLANNING sources only:

- LTDS Table 3a (published planning demand): winter maximum demand, 2029/30 forecast maximum
  demand, published minimum-load scaling factor and power factors per primary site;
- the E1 planning case (LTDS topology + the E1 split of site demand across the site's 11 kV load
  nodes by transformer rating) for node shares and datakit bus indices;
- the UKPN Embedded Capacity Register as attributed in configs/networks/study_region.yaml
  (registered capacities and connection dates) for 33 kV generation and storage.

No real operating time series (UKPN half-hourly, S1/S2, irradiance-derived PV, weather, events)
is read:
`SOURCES_READ` records every file opened and tests assert it stays within `ALLOWED_SOURCES`.

`EnvelopeLoadGenerator` is a drop-in gridfm-datakit load-scenario generator: it returns the
(n_bus, n_scenarios, 2) P/Q array datakit expects, so datakit's own N-1 topology and admittance
perturbation, OPF/PF solves and output tables stay exactly as in E5.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from cloud2grid.licensing.registry import REPO_ROOT

ALLOWED_SOURCES = {
    "data/raw/ukpn/ltds_demand_3a.parquet",
    "configs/networks/study_region.yaml",
    "configs/experiments/e5b_operating_envelope.yaml",
}
SOURCES_READ: set[str] = set()
ENVELOPE_CFG = REPO_ROOT / "configs/experiments/e5b_operating_envelope.yaml"


def _read(rel: str) -> Path:
    if rel not in ALLOWED_SOURCES:
        raise PermissionError(f"E5b envelope may not read {rel}")
    SOURCES_READ.add(rel)
    return REPO_ROOT / rel


def load_config() -> dict[str, Any]:
    return yaml.safe_load(_read("configs/experiments/e5b_operating_envelope.yaml").read_text())


def site_bounds(cfg: dict[str, Any]) -> pd.DataFrame:
    """Per primary site: net-demand fraction bounds of the winter maximum demand (LTDS 3a)."""
    d = pd.read_parquet(_read("data/raw/ukpn/ltds_demand_3a.parquet"))
    rows = []
    for site, spec in cfg["primary_sites"].items():
        s = d[d.functional_location == spec["functional_location"]]
        w, su = s[s.season == "Winter"], s[s.season == "Summer"]
        md = float(w.maximum_demand_24_25_mw.sum())
        fc = float(w.forecast_m_d_mw_29_30.sum())
        fmin = su.minimum_load_scaling_factor.str.rstrip("%").astype(float) / 100.0
        pf = pd.concat([w.maximum_demand_24_25_pf, su.maximum_demand_24_25_pf]).astype(float)
        rows.append(
            {
                "site": site,
                "functional_location": spec["functional_location"],
                "winter_md_mw": md,
                "forecast_md_29_30_mw": fc,
                "published_min_load_factor": float(fmin.min()),
                "lambda_lo": min(0.0, float(fmin.min())),
                "lambda_hi": max(md, fc) / md,
                "pf_lo": float(pf.min()),
                "pf_hi": float(pf.max()),
            }
        )
    return pd.DataFrame(rows).set_index("site")


def hv_generation(cfg: dict[str, Any]) -> pd.DataFrame:
    """33 kV generation (non-storage) attributed to the rule's node set, dated on/before cutoff."""
    rule = cfg["hv_generation"]
    reg = yaml.safe_load(_read("configs/networks/study_region.yaml").read_text())
    a = pd.DataFrame(reg["assets"])
    a = a[
        (a.status == "Connected")
        & (a.connection_voltage_kv == 33.0)
        & ~a.technology.str.startswith("Stored Energy")
        & a.date_connected.notna()
    ]
    a = a[pd.to_datetime(a.date_connected) <= pd.Timestamp(rule["connected_on_or_before"])]
    a = a[a.attributed_nodes.apply(lambda n: sorted(n) == sorted(rule["nodes"]))]
    return a[["ecr_row", "technology", "registered_capacity_mw", "date_connected"]].reset_index(
        drop=True
    )


def storage(cfg: dict[str, Any]) -> dict[str, Any]:
    reg = yaml.safe_load(_read("configs/networks/study_region.yaml").read_text())
    a = pd.DataFrame(reg["assets"])
    row = a[a.ecr_row == cfg["storage"]["ecr_row"]].iloc[0]
    return {
        "ecr_row": int(row.ecr_row),
        "registered_capacity_mw": float(row.registered_capacity_mw),
        "technology": row.technology,
        "date_connected": row.date_connected,
    }


def build_envelope() -> dict[str, Any]:
    """Every controllable element with min / max / sign / source / sampling (machine-readable)."""
    cfg = load_config()
    sites = site_bounds(cfg)
    gen = hv_generation(cfg)
    st = storage(cfg)
    rows = []
    for site, spec in cfg["primary_sites"].items():
        b = sites.loc[site]
        for node, share in spec["node_shares"].items():
            p_md = b.winter_md_mw * share
            rows.append(
                {
                    "element": f"load {node}",
                    "node": node,
                    "role": "primary net demand (11 kV)",
                    "min_mw": round(b.lambda_lo * p_md, 4),
                    "max_mw": round(b.lambda_hi * p_md, 4),
                    "sign": "± (export only if the LTDS minimum-load factor is negative)"
                    if b.lambda_lo < 0
                    else "≥ 0",
                    "source": f"LTDS 3a {b.functional_location}: winter MD {b.winter_md_mw} MW, "
                    f"2029/30 forecast {b.forecast_md_29_30_mw} MW, min-load factor "
                    f"{b.published_min_load_factor:+.3f}; E1 node share {share:.4f}",
                    "sampling": "hierarchical: global level G + site deviation + node jitter; "
                    f"pf U({b.pf_lo}, {b.pf_hi})",
                }
            )
    cap = {
        t: float(gen.loc[gen.technology.str.startswith(t), "registered_capacity_mw"].sum())
        for t in ("Solar", "Wind")
    }
    for node in cfg["hv_generation"]["nodes"]:
        rows.append(
            {
                "element": f"generation {node}",
                "node": node,
                "role": "33 kV generation (export)",
                "min_mw": 0.0,
                "max_mw": round(
                    (cap["Solar"] + cap["Wind"]) / len(cfg["hv_generation"]["nodes"]), 4
                ),
                "sign": "export (≤ 0 as net load)",
                "source": "ECR rows "
                + ", ".join(
                    f"{r.ecr_row} ({r.technology} {r.registered_capacity_mw} MW, "
                    f"{r.date_connected})"
                    for r in gen.itertuples()
                )
                + "; equal split over the node set (E3 rule)",
                "sampling": "S~U(0,1) × solar capacity + W~U(0,1) × wind capacity",
            }
        )
    c = st["registered_capacity_mw"]
    stc = cfg["storage"]
    rows.append(
        {
            "element": f"storage {cfg['storage']['node']}",
            "node": cfg["storage"]["node"],
            "role": "bidirectional battery / customer",
            "min_mw": -c,
            "max_mw": c,
            "sign": "± (import = charging, export = discharging)",
            "source": f"ECR row {st['ecr_row']} ({st['technology'][:13]}) registered/export "
            f"{c} MW, connected {st['date_connected']}; LTDS T5 52.1 MVA = {c}/0.95 (same plant)",
            "sampling": f"mixture: {stc['idle_probability']:.0%} idle U(±{stc['idle_band_mw']}), "
            f"else U(−{c}, +{c}); unity power factor",
        }
    )
    return {
        "sites": sites,
        "hv_generation": gen,
        "hv_capacity_mw": cap,
        "storage": st,
        "elements": pd.DataFrame(rows),
        "cfg": cfg,
    }


class EnvelopeLoadGenerator:
    """gridfm-datakit load-scenario generator sampling the E5b envelope (static bounds only)."""

    def __init__(self) -> None:
        self.env = build_envelope()

    def sample(self, n: int, seed: int) -> pd.DataFrame:
        """n independent operating states → per-node P/Q (MW, MVAr; load convention)."""
        cfg, sites = self.env["cfg"], self.env["sites"]
        h = cfg["hierarchy"]
        rng = np.random.default_rng(seed)
        out: dict[str, np.ndarray] = {}
        g = rng.uniform(0.0, 1.0, n)  # global demand level (no time/weather information)
        for site, spec in cfg["primary_sites"].items():
            b = sites.loc[site]
            eps = rng.uniform(-h["site_deviation"], h["site_deviation"], n)
            lam = b.lambda_lo + (b.lambda_hi - b.lambda_lo) * np.clip(g + eps, 0.0, 1.0)
            pf = rng.uniform(b.pf_lo, b.pf_hi, n)
            nodes = list(spec["node_shares"])
            shares = np.array([spec["node_shares"][k] for k in nodes])
            jit = shares * (1 + rng.uniform(-h["node_jitter"], h["node_jitter"], (n, len(nodes))))
            jit = jit / jit.sum(axis=1, keepdims=True)
            for j, node in enumerate(nodes):
                p = lam * b.winter_md_mw * jit[:, j]
                out[f"P:{node}"] = p
                out[f"Q:{node}"] = p * np.tan(np.arccos(pf))
        cap = self.env["hv_capacity_mw"]
        s_lvl, w_lvl = rng.uniform(0, 1, n), rng.uniform(0, 1, n)
        hv = s_lvl * cap["Solar"] + w_lvl * cap["Wind"]
        for node in cfg["hv_generation"]["nodes"]:
            out[f"P:{node}"] = -hv / len(cfg["hv_generation"]["nodes"])
            out[f"Q:{node}"] = np.zeros(n)
        st = cfg["storage"]
        c = self.env["storage"]["registered_capacity_mw"]
        idle = rng.uniform(0, 1, n) < st["idle_probability"]
        p_b = np.where(
            idle, rng.uniform(-st["idle_band_mw"], st["idle_band_mw"], n), rng.uniform(-c, c, n)
        )
        out[f"P:{st['node']}"] = p_b
        out[f"Q:{st['node']}"] = np.zeros(n)
        df = pd.DataFrame(out)
        df["global_level"], df["solar_level"], df["wind_level"] = g, s_lvl, w_lvl
        return df

    def __call__(
        self, net: Any, n_scenarios: int, scenarios_log: str, max_iter: int, seed: int
    ) -> np.ndarray:
        """datakit interface: (n_bus, n_scenarios, 2) array; buses not in the envelope stay 0."""
        idx = self.env["cfg"]["datakit_bus_index"]
        n_bus = net.Pd.shape[0]
        df = self.sample(n_scenarios, seed)
        arr = np.zeros((n_bus, n_scenarios, 2))
        for node, k in idx.items():
            arr[k, :, 0] = df[f"P:{node}"].to_numpy()
            arr[k, :, 1] = df[f"Q:{node}"].to_numpy()
        with open(scenarios_log, "a") as f:
            f.write(f"E5b envelope generator, seed {seed}, {n_scenarios} scenarios\n")
        return arr
