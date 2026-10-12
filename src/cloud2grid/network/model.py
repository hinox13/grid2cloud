"""Build a pandapower network for a study region from LTDS records (E1).

Inputs: the frozen study region (configs/networks/study_region.yaml), the raw LTDS tables
(T1 circuits, T2a 2-winding transformers) and metadata/network_assumptions.yaml.

Every parameter written to the model is recorded in a provenance table with class
PUBLISHED / DERIVED / ASSUMED / MISSING and the assumption ID where applicable.
Bus names are licence-area-scoped LTDS node keys (e.g. "EPN:SUND31"); raw node codes are
never used unscoped.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandapower as pp
import pandas as pd

S_BASE_MVA = 100.0  # A01_percent_base_100mva
F_HZ = 50.0


@dataclass
class Provenance:
    rows: list[dict[str, Any]] = field(default_factory=list)

    def add(
        self,
        element: str,
        element_id: str,
        parameter: str,
        value: Any,
        unit: str,
        cls: str,
        source: str,
    ) -> None:
        self.rows.append(
            {
                "element": element,
                "element_id": element_id,
                "parameter": parameter,
                "value": value,
                "unit": unit,
                "class": cls,
                "source": source,
            }
        )

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def _num(value: Any) -> float | None:
    v = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(v) else float(v)


def bus_nominal_kv(node: dict[str, Any]) -> float:
    """Nominal busbar voltage: 132/33 from LTDS operating voltage; primary LV busbars 11 kV."""
    if node["role"] == "primary_lv_busbar":
        return 11.0  # transformer monthly index nominal_voltage (PUBLISHED)
    return float(node["kv"])


def circuit_params(rec: dict[str, Any], vn_kv: float) -> dict[str, float | None]:
    """LTDS T1 percent values (100 MVA base) → ohms / nF per km."""
    zb = vn_kv**2 / S_BASE_MVA
    r_pct = _num(rec.get("positive_sequence_impedance_r_percent"))
    x_pct = _num(rec.get("positive_sequence_impedance_x_percent"))
    b_pct = _num(rec.get("susceptance_b_percent"))
    length = _num(rec.get("circuit_length"))
    total_len = length if length and length > 0 else 1.0
    out: dict[str, float | None] = {"length_km": total_len, "length_published": length}
    out["r_ohm_per_km"] = None if r_pct is None else r_pct / 100 * zb / total_len
    out["x_ohm_per_km"] = None if x_pct is None else x_pct / 100 * zb / total_len
    if b_pct is None:
        out["c_nf_per_km"] = None
    else:
        b_siemens = b_pct / 100 / zb
        out["c_nf_per_km"] = b_siemens / (2 * math.pi * F_HZ) * 1e9 / total_len
    out["max_i_ka"] = (
        None
        if _num(rec.get("rating_amps_summer")) is None
        else (_num(rec.get("rating_amps_summer")) / 1000)
    )
    out["max_i_ka_winter"] = (
        None
        if _num(rec.get("rating_amps_winter")) is None
        else (_num(rec.get("rating_amps_winter")) / 1000)
    )
    return out


def transformer_params(rec: dict[str, Any]) -> dict[str, float | None]:
    """LTDS T2a percent values (100 MVA base) → pandapower vk/vkr on the unit's summer rating."""
    sn = _num(rec.get("transformer_rating_mva_summer"))
    r_pct = _num(rec.get("positive_sequence_impedance_r_percent"))
    x_pct = _num(rec.get("positive_sequence_impedance_x_percent"))
    out: dict[str, float | None] = {
        "sn_mva": sn,
        "sn_mva_winter": _num(rec.get("transformer_rating_mva_winter")),
        "vn_hv_kv": _num(rec.get("voltage_hv")),
        "vn_lv_kv": _num(rec.get("voltage_lv")),
        "tap_min_percent": _num(rec.get("tap_range_min_percent")),
        "tap_max_percent": _num(rec.get("tap_range_max_percent")),
    }
    if sn is None or r_pct is None or x_pct is None:
        out["vk_percent"] = out["vkr_percent"] = None
    else:
        out["vk_percent"] = math.hypot(r_pct, x_pct) * sn / S_BASE_MVA
        out["vkr_percent"] = r_pct * sn / S_BASE_MVA
    return out


def build_network(
    region: dict[str, Any],
    circuits: pd.DataFrame,
    t2: pd.DataFrame,
    slack_node: str,
    coupled_nodes: list[list[str]] | None = None,
    slack_vm_pu: float = 1.0,
) -> tuple[pp.pandapowerNet, pd.DataFrame]:
    """Create the pandapower net (no loads/injections yet) and its provenance table."""
    prov = Provenance()
    net = pp.create_empty_network(name=region["region_id"], f_hz=F_HZ, sn_mva=S_BASE_MVA)

    bus_idx: dict[str, int] = {}
    for node in region["nodes"]:
        vn = bus_nominal_kv(node)
        geo = None
        if node["geolocation_status"] == "resolved":
            geo = (node["lon"], node["lat"])
        idx = pp.create_bus(net, vn_kv=vn, name=node["node_key"], geodata=geo, type="b")
        net.bus.loc[idx, "geolocation_status"] = node["geolocation_status"]
        net.bus.loc[idx, "geo_lat"] = geo[1] if geo else np.nan  # never interpolated
        net.bus.loc[idx, "geo_lon"] = geo[0] if geo else np.nan
        net.bus.loc[idx, "role"] = node["role"]
        bus_idx[node["node_key"]] = idx
        prov.add(
            "bus",
            node["node_key"],
            "vn_kv",
            vn,
            "kV",
            "PUBLISHED",
            "LTDS T1 operating_voltage"
            if node["role"] != "primary_lv_busbar"
            else "transformer monthly index nominal_voltage",
        )
        prov.add(
            "bus",
            node["node_key"],
            "geodata",
            None if geo is None else f"{geo[1]:.5f},{geo[0]:.5f}",
            "deg",
            "PUBLISHED" if geo else "MISSING",
            "Grid/Primary Sites spatial_coordinates via site FLOC"
            if geo
            else f"geolocation_status={node['geolocation_status']} (not interpolated)",
        )

    t1 = circuits.set_index("id")
    t2i = t2.set_index("id")
    for br in region["branches"]:
        bid, fb, tb = br["branch_id"], bus_idx[br["from"]], bus_idx[br["to"]]
        if br["ltds_table"] == "T1":
            rec = t1.loc[br["ltds_id"]].to_dict()
            vn = net.bus.at[fb, "vn_kv"]
            p = circuit_params(rec, vn)
            if None in (p["r_ohm_per_km"], p["x_ohm_per_km"], p["c_nf_per_km"], p["max_i_ka"]):
                for k in ("r_ohm_per_km", "x_ohm_per_km", "c_nf_per_km", "max_i_ka"):
                    if p[k] is None:
                        prov.add("line", bid, k, None, "", "MISSING", "LTDS T1")
                continue  # never fill silently: the branch is left out and reported MISSING
            idx = pp.create_line_from_parameters(
                net,
                fb,
                tb,
                length_km=p["length_km"],
                r_ohm_per_km=p["r_ohm_per_km"],
                x_ohm_per_km=p["x_ohm_per_km"],
                c_nf_per_km=p["c_nf_per_km"],
                max_i_ka=p["max_i_ka"],
                name=br["ltds_line_name"],
            )
            net.line.loc[idx, "branch_id"] = bid
            net.line.loc[idx, "max_i_ka_winter"] = p["max_i_ka_winter"]
            src = f"LTDS T1 id={br['ltds_id']}"
            prov.add(
                "line",
                bid,
                "length_km",
                p["length_published"],
                "km",
                "PUBLISHED" if p["length_published"] else "MISSING",
                src,
            )
            for k, unit in (
                ("r_ohm_per_km", "ohm/km"),
                ("x_ohm_per_km", "ohm/km"),
                ("c_nf_per_km", "nF/km"),
            ):
                prov.add(
                    "line", bid, k, p[k], unit, "DERIVED", f"{src}; percent on 100 MVA base [A01]"
                )
            prov.add(
                "line",
                bid,
                "max_i_ka",
                p["max_i_ka"],
                "kA",
                "PUBLISHED",
                f"{src} rating_amps_summer",
            )
            prov.add(
                "line",
                bid,
                "max_i_ka_winter",
                p["max_i_ka_winter"],
                "kA",
                "PUBLISHED",
                f"{src} rating_amps_winter",
            )
        else:
            rec = t2i.loc[br["ltds_id"]].to_dict()
            p = transformer_params(rec)
            if p["vk_percent"] is None:
                prov.add("trafo", bid, "vk_percent", None, "%", "MISSING", "LTDS T2a")
                continue
            idx = pp.create_transformer_from_parameters(
                net,
                hv_bus=fb,
                lv_bus=tb,
                sn_mva=p["sn_mva"],
                vn_hv_kv=p["vn_hv_kv"],
                vn_lv_kv=p["vn_lv_kv"],
                vk_percent=p["vk_percent"],
                vkr_percent=p["vkr_percent"],
                pfe_kw=0.0,
                i0_percent=0.0,
                shift_degree=0.0,
                tap_side="hv",
                tap_neutral=0,
                tap_pos=0,
                tap_min=0,
                tap_max=0,
                tap_step_percent=0.0,
                name=f"{rec.get('hv_substation')} -> {rec.get('lv_substation')}",
            )
            net.trafo.loc[idx, "branch_id"] = bid
            net.trafo.loc[idx, "sn_mva_winter"] = p["sn_mva_winter"]
            src = f"LTDS T2a id={br['ltds_id']}"
            for k, unit in (
                ("sn_mva", "MVA"),
                ("vn_hv_kv", "kV"),
                ("vn_lv_kv", "kV"),
                ("tap_min_percent", "%"),
                ("tap_max_percent", "%"),
            ):
                prov.add("trafo", bid, k, p[k], unit, "PUBLISHED", src)
            for k in ("vk_percent", "vkr_percent"):
                prov.add(
                    "trafo",
                    bid,
                    k,
                    p[k],
                    "%",
                    "DERIVED",
                    f"{src}; percent on 100 MVA base rescaled to sn_mva [A01]",
                )
            prov.add("trafo", bid, "tap_pos", 0, "", "ASSUMED", "A02_neutral_taps")
            prov.add(
                "trafo", bid, "pfe_kw/i0_percent", 0, "", "ASSUMED", "A03_no_magnetising_branch"
            )
            prov.add(
                "trafo",
                bid,
                "shift_degree",
                0,
                "deg",
                "ASSUMED",
                f"A04_zero_phase_shift (published vector group {rec.get('vector_group')})",
            )

    for group in coupled_nodes or []:
        for other in group[1:]:
            pp.create_switch(
                net,
                bus_idx[group[0]],
                bus_idx[other],
                et="b",
                closed=True,
                name=f"coupler {group[0]}-{other}",
            )
            prov.add(
                "switch",
                f"{group[0]}-{other}",
                "closed",
                True,
                "",
                "ASSUMED",
                "A06_sundon_132kv_coupler_closed",
            )

    pp.create_ext_grid(
        net,
        bus_idx[slack_node],
        vm_pu=slack_vm_pu,
        va_degree=0.0,
        name=f"external grid at {slack_node}",
    )
    prov.add(
        "ext_grid",
        slack_node,
        "vm_pu",
        slack_vm_pu,
        "pu",
        "ASSUMED",
        "A05_external_grid_sundon_gis_132kv",
    )
    return net, prov.frame()


# --------------------------------------------------------------------------- validation


def structural_checks(net: pp.pandapowerNet, region: dict[str, Any]) -> dict[str, Any]:
    """Machine-readable structural validation (README §43 Network, E1 §8)."""
    import networkx as nx
    from pandapower.topology import create_nxgraph

    checks: dict[str, dict[str, Any]] = {}

    def check(name: str, ok: bool, detail: Any) -> None:
        checks[name] = {"ok": bool(ok), "detail": detail}

    names = net.bus["name"]
    check(
        "unique_scoped_bus_ids",
        names.is_unique and names.str.match(r"^(EPN|LPN|SPN):").all(),
        {"n_buses": len(names), "duplicates": names[names.duplicated()].tolist()},
    )
    expected = {b["branch_id"] for b in region["branches"]}
    built = set(net.line.get("branch_id", pd.Series(dtype=str))) | set(
        net.trafo.get("branch_id", pd.Series(dtype=str))
    )
    check(
        "all_region_branches_built",
        expected == built,
        {"missing": sorted(expected - built), "extra": sorted(built - expected)},
    )
    valid_bus = set(net.bus.index)
    check(
        "line_endpoints_valid",
        net.line.from_bus.isin(valid_bus).all()
        and net.line.to_bus.isin(valid_bus).all()
        and (net.line.from_bus != net.line.to_bus).all(),
        {"n_lines": len(net.line)},
    )
    check(
        "trafo_endpoints_valid",
        net.trafo.hv_bus.isin(valid_bus).all() and net.trafo.lv_bus.isin(valid_bus).all(),
        {"n_trafos": len(net.trafo)},
    )
    vf = net.bus.vn_kv.loc[net.line.from_bus].to_numpy()
    vt = net.bus.vn_kv.loc[net.line.to_bus].to_numpy()
    check(
        "line_voltage_consistency",
        np.allclose(vf, vt),
        {"mismatched_lines": net.line.name[~np.isclose(vf, vt)].tolist()},
    )
    hv_ok = np.isclose(
        net.trafo.vn_hv_kv, net.bus.vn_kv.loc[net.trafo.hv_bus].to_numpy(), rtol=0.06
    )
    lv_ok = np.isclose(
        net.trafo.vn_lv_kv, net.bus.vn_kv.loc[net.trafo.lv_bus].to_numpy(), rtol=0.06
    )
    check(
        "trafo_voltage_consistency (±6% rated vs bus nominal)",
        hv_ok.all() and lv_ok.all(),
        {
            "off_nominal_lv_ratio": net.trafo.name[
                ~np.isclose(net.trafo.vn_lv_kv, net.bus.vn_kv.loc[net.trafo.lv_bus].to_numpy())
            ].tolist()
        },
    )
    num = net.line[["r_ohm_per_km", "x_ohm_per_km", "c_nf_per_km", "max_i_ka"]]
    check(
        "finite_positive_line_parameters",
        np.isfinite(num.to_numpy()).all()
        and (num[["r_ohm_per_km", "x_ohm_per_km", "max_i_ka"]] > 0).all().all()
        and (num["c_nf_per_km"] >= 0).all(),
        {},
    )
    tnum = net.trafo[["sn_mva", "vk_percent", "vkr_percent"]]
    check(
        "finite_positive_trafo_parameters",
        np.isfinite(tnum.to_numpy()).all()
        and (tnum > 0).all().all()
        and (net.trafo.vkr_percent < net.trafo.vk_percent).all(),
        {},
    )
    pairs = net.line.apply(lambda r: tuple(sorted((r.from_bus, r.to_bus))), axis=1)
    dup = net.line[pairs.duplicated(keep=False)]
    check(
        "duplicate_circuits_reported",
        True,
        {
            "parallel_or_duplicate": dup[["name", "from_bus", "to_bus"]]
            .assign(
                from_bus=lambda d: net.bus.name.loc[d.from_bus].to_numpy(),
                to_bus=lambda d: net.bus.name.loc[d.to_bus].to_numpy(),
            )
            .to_dict(orient="records")
        },
    )
    g = create_nxgraph(net, respect_switches=True)
    comps = list(nx.connected_components(g))
    check(
        "single_connected_component",
        len(comps) == 1,
        {"n_components": len(comps), "sizes": sorted(len(c) for c in comps)},
    )
    deg = dict(g.degree())
    isolated = [net.bus.name.at[b] for b in net.bus.index if deg.get(b, 0) == 0]
    check("no_isolated_buses", not isolated, {"isolated": isolated})
    slack = set(net.ext_grid.bus)
    trafo_reach = all(
        any(nx.has_path(g, s, b) for s in slack)
        for b in set(net.trafo.lv_bus) | set(net.trafo.hv_bus)
    )
    check("transformers_connected_to_slack", trafo_reach, {})
    leaves = [net.bus.name.at[b] for b, d in deg.items() if d == 1]
    check("leaf_buses_reported", True, {"leaf_buses": sorted(leaves)})

    pp.runpp(net, init="flat", calculate_voltage_angles=True)  # zero-injection state
    ybus = net._ppc["internal"]["Ybus"].toarray()
    branch_y = ybus - np.diag(np.diag(ybus))
    check(
        "ybus_constructed",
        np.isfinite(ybus).all(),
        {"shape": list(ybus.shape), "nnz": int(np.count_nonzero(ybus))},
    )
    check("ybus_offdiag_symmetric (no phase shifters)", np.allclose(branch_y, branch_y.T), {})
    return {"ok": all(c["ok"] for c in checks.values()), "checks": checks}
