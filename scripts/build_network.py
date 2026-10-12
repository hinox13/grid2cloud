"""E1 — reconstruct the study-region network (pandapower) from LTDS records.

    uv run --env-file .env python scripts/build_network.py \
        [--config configs/networks/sundon_base_ltds.yaml] [--skip-export]

Steps: build network (+ parameter provenance) → structural validation → serialise → AC power-
flow sanity cases (LTDS planning peak; one observed operating state) → solar spatial-diversity
geometry → OpenGridFM export (datakit's own AC PF, graphkit load check) → figures.

No satellite, weather, PV-model or GENCO computation is performed.

Outputs
    reports/experiments/e1_network/{summary.json, structural_validation.json, network.json}
    reports/tables/e1_parameter_provenance.csv, e1_solar_geometry.csv, e1_sanity_cases.csv
    reports/figures/e1_topology.png, e1_solar_geometry.png
    data/processed/opengridfm/<region>/raw/*.parquet  (gitignored)
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandapower as pp
import pandas as pd
import yaml

from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.network import measurements as ms
from cloud2grid.network import model, plots
from cloud2grid.network.ukpn_regions import haversine_km

DEFAULT_CONFIG = REPO_ROOT / "configs" / "networks" / "sundon_base_ltds.yaml"
OUT = REPO_ROOT / "reports" / "experiments" / "e1_network"
TABLES = REPO_ROOT / "reports" / "tables"
FIGS = REPO_ROOT / "reports" / "figures"
RAW = REPO_ROOT / "data" / "raw" / "ukpn"


def load_inputs(cfg: dict[str, Any]) -> dict[str, Any]:
    region = yaml.safe_load((REPO_ROOT / cfg["region"]).read_text())
    return {
        "region": region,
        "circuits": pd.read_parquet(RAW / "ltds_circuits.parquet"),
        "t2": pd.read_parquet(RAW / "ltds_transformers_2w.parquet"),
        "demand_3a": pd.read_parquet(RAW / "ltds_demand_3a.parquet"),
    }


def build(cfg: dict[str, Any], inp: dict[str, Any]) -> tuple[pp.pandapowerNet, pd.DataFrame]:
    n = cfg["network"]
    return model.build_network(
        inp["region"],
        inp["circuits"],
        inp["t2"],
        slack_node=n["slack_node"],
        coupled_nodes=n["coupled_nodes"],
        slack_vm_pu=n["slack_vm_pu"],
    )


def add_load_elements(net: pp.pandapowerNet, cfg: dict[str, Any]) -> dict[str, int]:
    bus = {name: i for i, name in net.bus["name"].items()}
    out = {}
    for spec in cfg["loads"]:
        out[spec["node"]] = pp.create_load(
            net, bus[spec["node"]], p_mw=0.0, q_mvar=0.0, name=spec["node"]
        )
    return out


def set_loads(net: pp.pandapowerNet, loads: dict[str, int], values: dict[str, tuple]) -> None:
    for node, idx in loads.items():
        p, q = values[node]
        net.load.loc[idx, ["p_mw", "q_mvar"]] = [p, q]


def sanity(net: pp.pandapowerNet, label: str) -> dict[str, Any]:
    pp.runpp(net, calculate_voltage_angles=True)
    imp = float(net.res_ext_grid.p_mw.sum())
    losses = float(net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum())
    demand = float(net.res_load.p_mw.sum()) - float(net.res_sgen.p_mw.sum() if len(net.sgen) else 0)
    by_kv = net.res_bus.join(net.bus.vn_kv).groupby("vn_kv").vm_pu.agg(["min", "max"])
    return {
        "case": label,
        "converged": bool(net.converged),
        "import_mw": round(imp, 3),
        "demand_mw": round(demand, 3),
        "losses_mw": round(losses, 3),
        "power_balance_residual_mw": round(imp - demand - losses, 6),
        "vm_min_pu": round(float(net.res_bus.vm_pu.min()), 4),
        "vm_max_pu": round(float(net.res_bus.vm_pu.max()), 4),
        **{f"vm_{int(k)}kv_range": f"{r['min']:.4f}-{r['max']:.4f}" for k, r in by_kv.iterrows()},
        "max_line_loading_pct": round(float(net.res_line.loading_percent.max()), 1),
        "max_line_loading_name": str(net.line.name.at[net.res_line.loading_percent.idxmax()]),
        "max_trafo_loading_pct": round(float(net.res_trafo.loading_percent.max()), 1),
        "ext_grid_sign": "positive p_mw = import into the model (pandapower generator convention)",
    }


def planning_peak_values(cfg: dict[str, Any], inp: dict[str, Any], net: pp.pandapowerNet) -> dict:
    """LTDS 3a winter maximum demand per site (PUBLISHED), split across that site's load nodes
    in proportion to the summer rating of the transformers feeding each node (ASSUMED)."""
    d = inp["demand_3a"]
    season = cfg["planning_peak_case"]["season"]
    trafo_lv = net.bus.name.loc[net.trafo.lv_bus].to_numpy()
    ratings = pd.Series(net.trafo.sn_mva.to_numpy(), index=trafo_lv).groupby(level=0).sum()
    rows = d[(d.season == season)]
    values, notes = {}, []
    by_site: dict[str, list[str]] = {}
    for spec in cfg["loads"]:
        by_site.setdefault(spec["pf_site_floc"], []).append(spec["node"])
    for floc, nodes in by_site.items():
        site_rows = rows[rows.functional_location == floc]
        if floc.startswith("EPN-S0000000D"):  # BSP-level 33 kV row is not a primary demand
            for node in nodes:
                values[node] = (0.0, 0.0)
            notes.append(f"{nodes}: 33 kV customer node(s) set to 0 (not a primary in LTDS 3a)")
            continue
        total = float(site_rows.maximum_demand_24_25_mw.sum())
        pf = float(site_rows.maximum_demand_24_25_pf.iloc[0])
        w = np.array([ratings.get(n, 0.0) for n in nodes])
        w = w / w.sum() if w.sum() > 0 else np.full(len(nodes), 1 / len(nodes))
        for node, share in zip(nodes, w, strict=True):
            p = total * share
            values[node] = (p, p * np.tan(np.arccos(pf)))
        notes.append(f"{floc}: {total:.1f} MW (pf {pf}) over {nodes}")
    region_flocs = {site["site_floc"] for site in inp["region"]["sites"]}
    bsp = rows[
        rows.functional_location.isin(region_flocs)
        & rows.functional_location.str.startswith("EPN-S0000000D")
    ]
    return {
        "values": values,
        "notes": notes,
        "ltds_bsp_max_demand_mw": float(bsp.maximum_demand_24_25_mw.sum()) if len(bsp) else None,
    }


def solar_geometry(region: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    a = pd.DataFrame(region["assets"])
    a["capacity_mw"] = a["capacity_mw_connected"]
    sol = a[a["is_solar"] & (a["status"] == "Connected")].sort_values(
        "capacity_mw", ascending=False
    )
    total = float(sol["capacity_mw"].sum())
    sol = sol.assign(cum_share=sol["capacity_mw"].cumsum() / total)
    major = sol[sol["cum_share"].shift(fill_value=0) < 0.95]
    pairs = [
        {
            "a": f"{x.capacity_mw:g} MW",
            "b": f"{y.capacity_mw:g} MW",
            "distance_km": round(haversine_km(x.lat, x.lon, y.lat, y.lon), 2),
        }
        for x, y in itertools.combinations(major.itertuples(), 2)
    ]
    lat, lon = major["lat"], major["lon"]
    ew = haversine_km(lat.mean(), lon.min(), lat.mean(), lon.max())
    ns = haversine_km(lat.min(), lon.mean(), lat.max(), lon.mean())
    d = [p["distance_km"] for p in pairs]
    summary = {
        "connected_solar_assets": len(sol),
        "connected_solar_mw": round(total, 3),
        "assets_for_95pct": len(major),
        "mw_for_95pct": round(float(major["capacity_mw"].sum()), 3),
        "share_of_total": round(float(major["capacity_mw"].sum()) / total, 4),
        "pairwise_km": pairs,
        "min_pairwise_km": min(d) if d else None,
        "max_pairwise_km": max(d) if d else None,
        "bbox": {
            "lat_min": float(lat.min()),
            "lat_max": float(lat.max()),
            "lon_min": float(lon.min()),
            "lon_max": float(lon.max()),
        },
        "extent_ew_km": round(ew, 2),
        "extent_ns_km": round(ns, 2),
        "lsa_saf_pixel_km_nominal": 3.0,
        "note": "Geometry only. Coordinates are ECR asset locations (PUBLISHED); "
        "no weather data used.",
        "accepted_not_connected_solar_mw": float(
            a[a["is_solar"] & (a["status"] != "Connected")]["registered_capacity_mw"].sum()
        ),
    }
    table = major[
        [
            "ecr_register",
            "ecr_row",
            "capacity_mw",
            "connection_voltage_kv",
            "lat",
            "lon",
            "date_connected",
            "site_floc",
            "attribution_route",
            "cum_share",
        ]
    ]
    return table, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--skip-export", action="store_true")
    args = parser.parse_args()
    cfg = yaml.safe_load(args.config.read_text())
    inp = load_inputs(cfg)
    region = inp["region"]
    for d in (OUT, TABLES, FIGS):
        d.mkdir(parents=True, exist_ok=True)

    net, prov = build(cfg, inp)
    prov.to_csv(TABLES / "e1_parameter_provenance.csv", index=False)
    structural = model.structural_checks(net, region)
    (OUT / "structural_validation.json").write_text(json.dumps(structural, indent=2, default=str))
    pp.to_json(net, str(OUT / "network.json"))

    loads = add_load_elements(net, cfg)
    peak = planning_peak_values(cfg, inp, net)
    set_loads(net, loads, peak["values"])
    cases = [sanity(net, "LTDS 3a winter planning peak (unobserved 33 kV customers = 0)")]
    nets_for_export = [pp.from_json_string(pp.to_json(net))]

    s = ms.load_series(REPO_ROOT / cfg["measurements_dir"])
    sign_table = ms.check_transformer_signs(cfg, s)
    if not sign_table["ok"].all():
        raise SystemExit(f"transformer sign evidence disagrees:\n{sign_table}")
    demand = ms.nodal_demand(cfg, s, inp["demand_3a"])
    imp_obs = ms.observed_import(cfg, s)
    dp = pd.concat({k: v.p_mw for k, v in demand.items()}, axis=1)
    complete = dp.notna().all(axis=1) & imp_obs.notna()
    # Deterministic "typical" observed state: the complete timestamp with median import.
    ts = (imp_obs[complete] - imp_obs[complete].median()).abs().idxmin()
    set_loads(net, loads, {k: (v.at[ts, "p_mw"], v.at[ts, "q_mvar"]) for k, v in demand.items()})
    obs_case = sanity(net, f"observed state {ts.isoformat()} (median import; customers = 0)")
    obs_case["observed_import_mw"] = round(float(imp_obs[ts]), 3)
    cases.append(obs_case)
    nets_for_export.append(pp.from_json_string(pp.to_json(net)))
    pd.DataFrame(cases).to_csv(TABLES / "e1_sanity_cases.csv", index=False)

    geo_table, geo = solar_geometry(region)
    geo_table.to_csv(TABLES / "e1_solar_geometry.csv", index=False)

    export: dict[str, Any] = {"status": "skipped"}
    if not args.skip_export:
        from cloud2grid.genco import opengridfm_export as ox

        try:
            raw, compare = ox.export_states(
                nets_for_export, "sundon_33kv", REPO_ROOT / "data" / "processed" / "opengridfm"
            )
            balance = ox.power_balance_check(raw)
            load = ox.graphkit_load_check(raw.parent)
            export = {
                "status": "ok",
                "dataset_dir": str(raw.relative_to(REPO_ROOT)),
                "scenarios": ["planning_peak", f"observed_{ts.isoformat()}"],
                "datakit_vs_pandapower": compare.to_dict(orient="records"),
                "power_balance_from_exported_tables": balance.to_dict(orient="records"),
                "graphkit_load": load,
            }
        except Exception as exc:  # report, never hide
            import traceback

            export = {
                "status": "blocked",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc().splitlines()[-8:],
            }

    edge_class = {}
    for c in region["measurements"]["circuits"]:
        if c["quantity"] == "active_power_mw":
            edge_class[c["ltds_line_name"]] = "active_power"
        elif c["quantity"] == "current_amps":
            edge_class[c["ltds_line_name"]] = "current_only"
    plots.plot_topology(
        net,
        FIGS / "e1_topology.png",
        title=f"{region['region_id']} — reconstructed 132/33/11 kV model (LTDS planning topology)",
    )
    sites = pd.DataFrame(region["sites"])
    assets = pd.DataFrame(region["assets"]).assign(capacity_mw=lambda d: d["capacity_mw_connected"])
    assets = assets[assets["status"] == "Connected"]
    plots.plot_solar_geometry(
        assets,
        sites,
        FIGS / "e1_solar_geometry.png",
        f"Sundon: connected solar (ECR coordinates). {geo['assets_for_95pct']} assets = "
        f"{geo['share_of_total']:.0%} of {geo['connected_solar_mw']:.1f} MW; "
        f"pairwise {geo['min_pairwise_km']}–{geo['max_pairwise_km']} km",
    )

    summary = {
        "region_id": region["region_id"],
        "selection_mode": region["selection"]["mode"],
        "network": {
            "buses": len(net.bus),
            "lines": len(net.line),
            "transformers": len(net.trafo),
            "bus_couplers": len(net.switch),
            "ext_grids": len(net.ext_grid),
            "load_nodes": len(loads),
            "buses_by_kv": net.bus.vn_kv.value_counts().sort_index().to_dict(),
            "geolocation_status": net.bus.geolocation_status.value_counts().to_dict(),
        },
        "structural_ok": structural["ok"],
        "provenance_counts": prov["class"].value_counts().to_dict(),
        "provenance_by_element": prov.groupby(["element", "class"])
        .size()
        .unstack(fill_value=0)
        .to_dict(orient="index"),
        "sign_conventions": sign_table.to_dict(orient="records"),
        "planning_peak_notes": peak["notes"],
        "ltds_bsp_max_demand_mw": peak["ltds_bsp_max_demand_mw"],
        "sanity_cases": cases,
        "solar_geometry": geo,
        "opengridfm_export": export,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(
        json.dumps(
            {k: summary[k] for k in ("network", "structural_ok", "provenance_counts")},
            indent=1,
            default=str,
        )
    )
    print(pd.DataFrame(cases).T.to_string())
    print(json.dumps(export, indent=1, default=str)[:3000])
    return 0 if structural["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
