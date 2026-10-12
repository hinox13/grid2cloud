"""Historical Sundon operating states B(t) — the E2 construction, reusable (E4).

Exactly the steps of scripts/validate_operational.py (E2), which stays the validated reference:
network from LTDS (`model.build_network`), loads at the 11 kV primary busbars and customer nodes
from observed flows (`measurements.nodal_demand`, with the interpretation's measurement scales),
the observed-outage rule (`scenarios.detect_outages`, historical timestamps only), and E2's
primary scenario V0 (no unobserved injection). Nothing here is fitted to GENCO or to weather.

UKPN half-hourly values are 30-min time-weighted averages labelled by PERIOD START (each month
runs from day 1 00:00 to the last day 23:30): B(T) represents [T, T+30 min).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandapower as pp
import pandas as pd
import yaml

from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.network import measurements as ms
from cloud2grid.network import model
from cloud2grid.network import scenarios as scn

RAW = REPO_ROOT / "data" / "raw" / "ukpn"


@dataclass
class StateBuilder:
    config: Path
    cfg: dict[str, Any] = field(init=False)
    net: pp.pandapowerNet = field(init=False)
    dp: pd.DataFrame = field(init=False)
    dq: pd.DataFrame = field(init=False)
    imp: pd.Series = field(init=False)

    def __post_init__(self) -> None:
        cfg = scn.load_config(self.config)
        region = yaml.safe_load((REPO_ROOT / cfg["region"]).read_text())
        circuits = pd.read_parquet(RAW / "ltds_circuits.parquet")
        t2 = pd.read_parquet(RAW / "ltds_transformers_2w.parquet")
        d3 = pd.read_parquet(RAW / "ltds_demand_3a.parquet")
        n = cfg["network"]
        net, _ = model.build_network(
            region, circuits, t2, n["slack_node"], n["coupled_nodes"], n["slack_vm_pu"]
        )
        s = ms.load_series(REPO_ROOT / cfg["measurements_dir"])
        signs = ms.check_transformer_signs(cfg, s)
        if not signs["ok"].all():
            raise ValueError(f"sign evidence disagrees:\n{signs}")
        p_targets = cfg["validation"]["active_power"]
        self.meters = ms.map_meters(region, net, p_targets + cfg["validation"]["current"])
        flagged = cfg.get("flagged_circuits", {})
        self.core = [c for c in p_targets if c not in flagged]
        # same data-quality screen as E2: |P| beyond mult × rating treated as missing
        mult = cfg["timestamp_selection"]["max_abs_flow_rating_multiple"]
        p_obs = s.circuit_p.copy()
        for line, mm in self.meters.items():
            if line in p_obs:
                vn = net.bus.vn_kv.at[net.line.from_bus.at[mm.index]]
                rating = np.sqrt(3) * vn * float(net.line.max_i_ka.at[mm.index])
                p_obs.loc[p_obs[line].abs() > mult * rating, line] = np.nan
        self.p_obs = p_obs
        fixed = pd.DatetimeIndex(
            pd.read_csv(
                REPO_ROOT / cfg.get("validation_timestamps", "reports/tables/e2_timestamps.csv"),
                parse_dates=["timestamp"],
            )["timestamp"]
        )
        monthly = pd.read_parquet(RAW / "op_33kv_monthly.parquet")
        self.scales = scn.resolve_scales(cfg, s, monthly, fixed)
        cfg_eff = scn.apply_scales(cfg, self.scales)
        demand = ms.nodal_demand(cfg_eff, s, d3)
        self.dp = pd.concat({k: v.p_mw for k, v in demand.items()}, axis=1)
        self.dq = pd.concat({k: v.q_mvar for k, v in demand.items()}, axis=1)
        self.imp = ms.observed_import(cfg, s)
        self.outage_rules = scn.changes(cfg, "observed_outages")
        self.bus = {name: i for i, name in net.bus["name"].items()}
        self.loads = {
            node: pp.create_load(net, self.bus[node], 0.0, 0.0, name=node)
            for node in self.dp.columns
        }
        self.cfg, self.net = cfg, net

    @property
    def interpretation(self) -> str:
        return self.cfg["scenario"]["name"]

    def complete(self) -> pd.Series:
        """Half-hours with every load input and the observed import (E2 'all inputs' rule)."""
        return self.dp.notna().all(axis=1) & self.imp.reindex(self.dp.index).notna()

    def apply(self, ts: pd.Timestamp) -> dict[str, Any]:
        """Set self.net to B(ts) (loads + observed outages; V0). Returns what was applied."""
        if not bool(self.complete().get(ts, False)):
            raise KeyError(f"incomplete inputs at {ts}")
        net = self.net
        for node, idx in self.loads.items():
            net.load.loc[idx, ["p_mw", "q_mvar"]] = [self.dp.at[ts, node], self.dq.at[ts, node]]
        net.line["in_service"] = True
        if len(net.sgen):  # E2 detects outages on the all-closed state WITHOUT injections
            net.sgen["p_mw"] = 0.0
            net.sgen["q_mvar"] = 0.0
        out_lines: list[str] = []
        for rule in self.outage_rules:
            pp.runpp(net, calculate_voltage_angles=True)
            sim0 = {ln: ms.model_flow(net, self.meters[ln])[0] for ln in self.core}
            obs0 = {
                ln: self.p_obs[ln].get(ts, np.nan) if ln in self.p_obs else np.nan
                for ln in self.core
            }
            out_lines = scn.detect_outages(sim0, obs0, rule)
            for ln in out_lines:
                net.line.loc[self.meters[ln].index, "in_service"] = False
        return {"timestamp": ts, "lines_out": out_lines}

    def load_by_node(self, ts: pd.Timestamp) -> pd.DataFrame:
        return pd.DataFrame({"p_mw": self.dp.loc[ts], "q_mvar": self.dq.loc[ts]})
