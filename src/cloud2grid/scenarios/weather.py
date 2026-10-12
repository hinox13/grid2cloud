"""Weather-driven Sundon states (E4), following docs/SATELLITE_SCENARIO_CONSTRUCTION.md exactly.

PV classes (by E0 site link + connection voltage, `solar.aggregate.bus_rules`):
    HV   >= 33 kV assets (2024: ECR:955, 6 MW) — NOT inside observed loads → explicit sgen,
         split equally over the E0 node set (LBUZ31/32/33).
    EMB  <= 11 kV assets — already inside the observed primary-transformer flows.

S1 synchronous  (base half-hour T, satellite slot s with floor(s, 30 min) = T):
    B(T) + sgen_HV = P_HV(s);  EMB untouched (adding it would double count).
Transplant      (base T, base slot s0 = T, donor slot s'):
    B(T) + sgen_HV = P_HV(s');  per load node n:
    L(n) = L_obs(n, T) + P_EMB(n, s0) − P_EMB(n, s')      (gross up, then replace)
Sign convention: sgen.p_mw >= 0 injects; load.p_mw >= 0 consumes; PV at unity power factor.
Only historically ACTIVE capacity enters (P_sat already carries active capacity at each slot).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandapower as pp
import pandas as pd

from cloud2grid.network.states import StateBuilder


@dataclass(frozen=True)
class PVForcing:
    """Per-slot satellite-driven PV split into HV and embedded-by-node components (MW)."""

    hv: pd.Series  # slot → MW injected at the HV node set
    emb: pd.DataFrame  # slot × load node → MW (embedded, inside observed loads)
    fleet: pd.DataFrame  # slot → fleet_pv_mw, active_capacity_mw, fleet_cf, mean_kc, ghi
    hv_nodes: tuple[str, ...]

    @classmethod
    def from_series(
        cls, pv_by_asset: pd.DataFrame, injection_nodes: dict[str, list[str]], hv_assets: set[str]
    ) -> PVForcing:
        pa = pv_by_asset[pv_by_asset["active_capacity_mw"] > 0].copy()
        pa["slot"] = pd.to_datetime(pa["slot"], utc=True)
        hv = pa[pa["asset_id"].isin(hv_assets)].groupby("slot")["estimated_pv_mw"].sum(min_count=1)
        rows = []
        for r in pa[~pa["asset_id"].isin(hv_assets)].itertuples():
            nodes = injection_nodes[r.asset_id]
            for n in nodes:
                rows.append((r.slot, n, r.estimated_pv_mw / len(nodes)))
        emb = (
            pd.DataFrame(rows, columns=["slot", "node", "mw"])
            .pivot_table(index="slot", columns="node", values="mw", aggfunc="sum")
            .fillna(0.0)
        )
        g = pa.groupby("slot")
        fleet = pd.DataFrame(
            {
                "fleet_pv_mw": g["estimated_pv_mw"].sum(min_count=1),
                "active_capacity_mw": g["active_capacity_mw"].sum(),
                "mean_kc": g["clearsky_index"].mean(),
                "mean_ghi": g["ghi"].mean(),
                "usable": g["status"].apply(lambda s: bool(s.eq("GOOD").all())),
            }
        )
        fleet["fleet_cf"] = fleet["fleet_pv_mw"] / fleet["active_capacity_mw"]
        hv_nodes = sorted({n for a in hv_assets for n in injection_nodes[a]})
        return cls(hv=hv, emb=emb, fleet=fleet, hv_nodes=tuple(hv_nodes))


class WeatherStates:
    """Builds S1 / transplant states on one StateBuilder network (mutated in place)."""

    def __init__(self, builder: StateBuilder, forcing: PVForcing) -> None:
        self.b = builder
        self.f = forcing
        net = builder.net
        self.sgen = {
            n: pp.create_sgen(net, builder.bus[n], 0.0, 0.0, name=f"pv_hv@{n}")
            for n in forcing.hv_nodes
        }

    def _set_hv(self, mw: float) -> None:
        for idx in self.sgen.values():
            self.b.net.sgen.loc[idx, ["p_mw", "q_mvar"]] = [mw / len(self.sgen), 0.0]

    def synchronous(self, slot: pd.Timestamp) -> dict[str, Any]:
        base = slot.floor("30min")
        info = self.b.apply(base)
        p_hv = float(self.f.hv.get(slot, float("nan")))
        if not pd.notna(p_hv):
            raise KeyError(f"no HV PV at {slot}")
        self._set_hv(p_hv)
        return {
            **info,
            "slot": slot,
            "donor_slot": slot,
            "p_hv_injected_mw": p_hv,
            "emb_delta_mw": 0.0,
        }

    def transplant(self, base: pd.Timestamp, donor: pd.Timestamp) -> dict[str, Any]:
        """B(base) with the PV of `donor`; embedded PV grossed up at base, replaced by donor."""
        info = self.b.apply(base)
        p_hv = float(self.f.hv.get(donor, float("nan")))
        if not pd.notna(p_hv):
            raise KeyError(f"no HV PV at donor {donor}")
        self._set_hv(p_hv)
        e0 = self.f.emb.loc[base] if base in self.f.emb.index else None
        e1 = self.f.emb.loc[donor] if donor in self.f.emb.index else None
        if e0 is None or e1 is None:
            raise KeyError("embedded PV missing at base or donor slot")
        delta_total = 0.0
        for node, idx in self.b.loads.items():
            d = float(e0.get(node, 0.0)) - float(e1.get(node, 0.0))
            if d:
                self.b.net.load.loc[idx, "p_mw"] += d
                delta_total += d
        return {
            **info,
            "slot": base,
            "donor_slot": donor,
            "p_hv_injected_mw": p_hv,
            "emb_delta_mw": delta_total,
        }


def load_forcing(pv_model_cfg: dict[str, Any], pv_series: Any) -> PVForcing:
    """PV forcing from the E3 per-asset series with E0 links and voltage-based classes."""
    from cloud2grid.licensing.registry import REPO_ROOT
    from cloud2grid.network import scenarios as scn
    from cloud2grid.solar import aggregate, inventory

    inv = inventory.load(pv_model_cfg)
    net_cfg = scn.load_config(REPO_ROOT / pv_model_cfg["network_config"])
    site: dict[str, list[str]] = {}
    for spec in net_cfg["loads"]:
        site.setdefault(spec["pf_site_floc"], []).append(spec["node"])
    nodes = aggregate.bus_rules(inv, site, pv_model_cfg["buses"])
    thr = pv_model_cfg["buses"]["hv_threshold_kv"]
    hv = {
        a
        for a, kv in zip(inv["asset_id"], inv["connection_voltage_kv"], strict=True)
        if pd.notna(kv) and kv >= thr
    }
    pv = pd.read_parquet(pv_series) if not isinstance(pv_series, pd.DataFrame) else pv_series
    return PVForcing.from_series(pv, nodes, hv)


def slot_meta(f: PVForcing, slot: pd.Timestamp, prefix: str = "") -> dict[str, Any]:
    """Weather/PV descriptors of a slot (pre-registered conditioning variables)."""
    row = f.fleet.loc[slot]
    prev = f.hv.get(slot - pd.Timedelta(minutes=15), float("nan"))
    return {
        f"{prefix}fleet_pv_mw": float(row["fleet_pv_mw"]),
        f"{prefix}fleet_cf": float(row["fleet_cf"]),
        f"{prefix}mean_kc": float(row["mean_kc"]),
        f"{prefix}mean_ghi": float(row["mean_ghi"]),
        f"{prefix}abs_hv_ramp_mw": abs(float(f.hv.get(slot, float("nan"))) - float(prev)),
    }


def populations(
    builder: StateBuilder, forcing: PVForcing, period: list[str]
) -> dict[str, pd.DatetimeIndex]:
    """Pre-registered E4 populations (configs/experiments/e4_matched_control.yaml).

    timeline: usable 15-min slots (E3 QC) whose half-hour base B(floor(s, 30 min)) is complete;
    primary:  the timeline slots at :00/:30 (UKPN half-hour T ↔ satellite slot T).
    """
    start, end = (pd.Timestamp(x) for x in period)
    usable = forcing.fleet.index[forcing.fleet["usable"]]
    usable = usable[(usable >= start) & (usable <= end + pd.Timedelta(minutes=15))]
    base_ok = builder.complete().reindex(usable.floor("30min")).fillna(False).to_numpy()
    timeline = usable[base_ok]
    primary = timeline[(timeline.minute % 30) == 0]
    return {"primary": primary[primary <= end], "timeline": timeline}
