"""E2 — validate the reconstructed network against UKPN operational measurements.

    uv run --env-file .env python scripts/validate_operational.py \
        [--config configs/networks/sundon_base_ltds.yaml]

Inputs are observations only (primary-transformer flows/currents, customer circuit flows, grid-
transformer import) plus LTDS parameters; validation targets are metered circuits never used as
inputs. Timestamps are selected by data completeness and a seeded stratified sample — never by
model error, and GENCO is not involved.

Scenarios: V0_none (primary, uncalibrated); V1_* place the residual "observed − modelled import"
at candidate nodes for the unobserved 33 kV customers (diagnostic only).

Outputs
    reports/experiments/e2_validation/{summary.json, results.parquet}
    reports/tables/e2_metrics_by_circuit.csv, e2_topology_diagnostics.csv, e2_timestamps.csv
    reports/figures/e2_measurement_coverage.png, e2_obs_vs_sim_<scenario>.png,
                    e2_unobserved_residual.png, e2_current_validation.png
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandapower as pp  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from cloud2grid.evaluation.metrics import flow_metrics  # noqa: E402
from cloud2grid.licensing.registry import REPO_ROOT  # noqa: E402
from cloud2grid.network import measurements as ms  # noqa: E402
from cloud2grid.network import model, plots  # noqa: E402
from cloud2grid.network import scenarios as scn  # noqa: E402

DEFAULT_CONFIG = REPO_ROOT / "configs" / "networks" / "sundon_base_ltds.yaml"
OUT = REPO_ROOT / "reports" / "experiments" / "e2_validation"
TABLES = REPO_ROOT / "reports" / "tables"
FIGS = REPO_ROOT / "reports" / "figures"
RAW = REPO_ROOT / "data" / "raw" / "ukpn"


def rating_mva(net: pp.pandapowerNet, line_idx: int) -> float:
    vn = net.bus.vn_kv.at[net.line.from_bus.at[line_idx]]
    return math.sqrt(3) * vn * float(net.line.max_i_ka.at[line_idx])


def select_timestamps(
    cfg: dict, demand: pd.DataFrame, imp: pd.Series, p_obs: pd.DataFrame, targets: list[str]
) -> tuple[pd.DatetimeIndex, dict[str, int]]:
    sel = cfg["timestamp_selection"]
    complete = demand.notna().all(axis=1) & imp.notna()
    present = p_obs.reindex(columns=targets).notna().sum(axis=1).reindex(demand.index).fillna(0)
    eligible = demand.index[complete & (present >= sel["min_validation_circuits_present"])]
    df = pd.DataFrame(index=eligible)
    df["month"] = eligible.strftime("%Y-%m")
    df["block"] = eligible.hour // 6
    rng = np.random.default_rng(sel["seed"])
    picks = []
    for _, grp in df.groupby(["month", "block"]):
        k = min(sel["per_month_per_6h_block"], len(grp))
        picks.extend(rng.choice(grp.index.to_numpy(), size=k, replace=False))
    chosen = pd.DatetimeIndex(sorted(picks))
    counts = {
        "timestamps_with_all_inputs": int(complete.sum()),
        "eligible_with_min_targets": len(eligible),
        "selected": len(chosen),
        "months_covered": int(df.loc[chosen, "month"].nunique()) if len(chosen) else 0,
    }
    return chosen, counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    cfg = scn.load_config(args.config)
    variant = cfg["scenario"]["name"]
    is_base = not cfg["scenario"]["changes"]
    # The baseline keeps its original output paths; variants never overwrite them.
    out_dir = OUT if is_base else OUT / "scenarios" / variant
    sfx = "" if is_base else f"_{variant}"
    region = yaml.safe_load((REPO_ROOT / cfg["region"]).read_text())
    for d in (out_dir, TABLES, FIGS):
        d.mkdir(parents=True, exist_ok=True)

    circuits = pd.read_parquet(RAW / "ltds_circuits.parquet")
    t2 = pd.read_parquet(RAW / "ltds_transformers_2w.parquet")
    d3 = pd.read_parquet(RAW / "ltds_demand_3a.parquet")
    n = cfg["network"]
    net, _ = model.build_network(
        region, circuits, t2, n["slack_node"], n["coupled_nodes"], n["slack_vm_pu"]
    )
    bus = {name: i for i, name in net.bus["name"].items()}

    s = ms.load_series(REPO_ROOT / cfg["measurements_dir"])
    signs = ms.check_transformer_signs(cfg, s)
    if not signs["ok"].all():
        raise SystemExit(f"sign evidence disagrees:\n{signs}")
    p_targets = cfg["validation"]["active_power"]
    i_targets = cfg["validation"]["current"]
    meters = ms.map_meters(region, net, p_targets + i_targets)
    flagged = cfg.get("flagged_circuits", {})
    core = [c for c in p_targets if c not in flagged]

    # ---- data quality: observations beyond 1.5 × rating are treated as malformed (counted)
    mult = cfg["timestamp_selection"]["max_abs_flow_rating_multiple"]
    p_obs = s.circuit_p.copy()
    dq = {}
    for line, mm in meters.items():
        if line in p_obs:
            bad = p_obs[line].abs() > mult * rating_mva(net, mm.index)
            dq[line] = int(bad.sum())
            p_obs.loc[bad, line] = np.nan
    chap = s.circuit_p["lne_SUND_CHAP"]
    chap_line = net.line.index[net.line.name == "lne_SUND_CHAP"][0]
    dq["lne_SUND_CHAP (input) beyond 1.5x rating"] = int(
        (chap.abs() > mult * rating_mva(net, chap_line)).sum()
    )
    dq["lne_SUND_CHAP (input) beyond 1.0x rating"] = int(
        (chap.abs() > rating_mva(net, chap_line)).sum()
    )

    ts_file = REPO_ROOT / cfg.get("validation_timestamps", "reports/tables/e2_timestamps.csv")
    fixed_ts = (
        pd.DatetimeIndex(pd.read_csv(ts_file, parse_dates=["timestamp"])["timestamp"])
        if ts_file.exists()
        else pd.DatetimeIndex([])
    )
    monthly = pd.read_parquet(RAW / "op_33kv_monthly.parquet")
    scales = scn.resolve_scales(cfg, s, monthly, fixed_ts)
    cfg_eff = scn.apply_scales(cfg, scales)
    outage_rules = scn.changes(cfg, "observed_outages")
    demand = ms.nodal_demand(cfg_eff, s, d3)
    dp = pd.concat({k: v.p_mw for k, v in demand.items()}, axis=1)
    dq_ = pd.concat({k: v.q_mvar for k, v in demand.items()}, axis=1)
    imp = ms.observed_import(cfg, s)
    chosen, sel_counts = select_timestamps(cfg, dp, imp, p_obs, p_targets)
    if is_base:
        pd.DataFrame({"timestamp": chosen}).to_csv(TABLES / "e2_timestamps.csv", index=False)
    else:
        # identical validation timestamps for every variant (selection is input-availability
        # based; measurement-scale variants do not change availability)
        if not set(fixed_ts) <= set(chosen.union(dp.index[dp.notna().all(axis=1)])):
            raise SystemExit("variant inputs unavailable at some baseline validation timestamps")
        chosen = fixed_ts
        sel_counts = {**sel_counts, "selected": len(chosen), "timestamps_source": str(ts_file)}

    loads = {node: pp.create_load(net, bus[node], 0.0, 0.0, name=node) for node in dp.columns}
    scen = cfg["unobserved_injection_scenarios"]
    cand_nodes = sorted({nd for nodes in scen.values() for nd in nodes})
    sgens = {
        node: pp.create_sgen(net, bus[node], 0.0, 0.0, name=f"unobserved@{node}")
        for node in cand_nodes
    }

    rows, runs, excluded = [], [], []
    for ts in chosen:
        for node, idx in loads.items():
            net.load.loc[idx, ["p_mw", "q_mvar"]] = [dp.at[ts, node], dq_.at[ts, node]]
        net.line["in_service"] = True
        out_lines: list[str] = []
        for rule in outage_rules:
            net.sgen["p_mw"] = 0.0
            pp.runpp(net, calculate_voltage_angles=True)
            sim0 = {ln: ms.model_flow(net, meters[ln])[0] for ln in core}
            obs0 = {ln: p_obs[ln].get(ts, np.nan) if ln in p_obs else np.nan for ln in core}
            out_lines = scn.detect_outages(sim0, obs0, rule)
            for ln in out_lines:
                net.line.loc[meters[ln].index, "in_service"] = False
                excluded.append(
                    {
                        "timestamp": ts,
                        "line": ln,
                        "observed_mw": obs0[ln],
                        "model_all_closed_mw": sim0[ln],
                    }
                )
        u = 0.0
        for name, nodes in scen.items():
            net.sgen["p_mw"] = 0.0
            ok = True
            for _ in range(3 if nodes else 1):
                for node in nodes:
                    net.sgen.loc[sgens[node], "p_mw"] = u / len(nodes)
                try:
                    pp.runpp(net, calculate_voltage_angles=True)
                except pp.LoadflowNotConverged:
                    ok = False
                    break
                if not nodes:
                    u = float(net.res_ext_grid.p_mw.sum()) - float(imp[ts])  # V0 residual
                    break
                u += float(net.res_ext_grid.p_mw.sum()) - float(imp[ts])
            runs.append(
                {
                    "timestamp": ts,
                    "scenario": name,
                    "converged": ok,
                    "unobserved_injection_mw": u if nodes else 0.0,
                    "v0_residual_mw": u if not nodes else np.nan,
                }
            )
            if not ok:
                continue
            for line in p_targets + i_targets:
                mm = meters[line]
                sim_p, sim_i = ms.model_flow(net, mm)
                obs_p = p_obs[line].get(ts, np.nan) if line in p_obs else np.nan
                if line in out_lines:  # zero reading used as outage evidence: not scored
                    obs_p = np.nan
                obs_i = s.circuit_i[line].get(ts, np.nan) if line in s.circuit_i else np.nan
                rows.append(
                    {
                        "timestamp": ts,
                        "scenario": name,
                        "line": line,
                        "obs_p": obs_p,
                        "sim_p": sim_p,
                        "obs_i": obs_i,
                        "sim_i": sim_i,
                    }
                )
            rows.append(
                {
                    "timestamp": ts,
                    "scenario": name,
                    "line": "IMPORT_TOTAL",
                    "obs_p": float(imp[ts]),
                    "sim_p": float(net.res_ext_grid.p_mw.sum()),
                    "obs_i": np.nan,
                    "sim_i": np.nan,
                }
            )
            rows.append(
                {
                    "timestamp": ts,
                    "scenario": name,
                    "line": "_state",
                    "obs_p": np.nan,
                    "sim_p": np.nan,
                    "vm_min": float(net.res_bus.vm_pu.min()),
                    "vm_max": float(net.res_bus.vm_pu.max()),
                    "max_line_loading": float(net.res_line.loading_percent.max()),
                    "max_trafo_loading": float(net.res_trafo.loading_percent.max()),
                }
            )
    res = pd.DataFrame(rows)
    run_df = pd.DataFrame(runs)
    net.line["in_service"] = True
    res.to_parquet(out_dir / "results.parquet", index=False)

    # ---- metrics
    thr = cfg["direction_threshold_mw"]
    met = []
    for (name, line), g in res[~res.line.isin(["_state"])].groupby(["scenario", "line"]):
        kind = "current" if line in i_targets else "active_power"
        if kind == "active_power":
            m = flow_metrics(
                g.set_index("timestamp")["sim_p"], g.set_index("timestamp")["obs_p"], thr
            )
        else:
            m = flow_metrics(g.set_index("timestamp")["sim_i"], g.set_index("timestamp")["obs_i"])
        met.append(
            {
                "scenario": name,
                "line": line,
                "kind": kind,
                "mapping": meters[line].mapping if line in meters else "aggregate",
                "flagged": line in flagged,
                "core": line in core,
                **m,
            }
        )
    metrics = pd.DataFrame(met)
    metrics.to_csv(TABLES / f"e2_metrics_by_circuit{sfx}.csv", index=False)

    def aggregate(name: str, lines: list[str]) -> dict:
        g = res[(res.scenario == name) & res.line.isin(lines)]
        return flow_metrics(g["sim_p"], g["obs_p"], thr)

    agg = {
        name: {
            "core_p_circuits": aggregate(name, core),
            "all_p_circuits": aggregate(name, p_targets),
            "import": aggregate(name, ["IMPORT_TOTAL"]),
        }
        for name in scen
    }

    # ---- pre-registered verdict (primary scenario)
    prim = cfg["primary_scenario"]
    mp = metrics[(metrics.scenario == prim) & metrics.core].set_index("line")
    conv = float(run_df[run_df.scenario == prim]["converged"].mean())
    structural_ok = json.loads(
        (REPO_ROOT / "reports/experiments/e1_network/structural_validation.json").read_text()
    )["ok"]
    imp_nmae = agg[prim]["import"]["nmae"]

    def level(spec: dict, r_min: float, nmae_max: float) -> dict:
        fit = (mp["r"] >= r_min) & (mp["nmae"] <= nmae_max)
        dir_ok = mp["direction_agreement"].fillna(1.0) >= spec["direction_agreement_min"]
        checks = {
            "structural": structural_ok,
            "convergence": conv >= spec["pf_convergence_rate"],
            "share_fit": float(fit.mean()) >= spec["share_core_circuits_meeting_fit"],
            "direction": bool(dir_ok.all()),
            "import": imp_nmae is not None and imp_nmae <= spec["import_nmae_max"],
        }
        return {
            "passed": all(checks.values()),
            "checks": checks,
            "share_fit": float(fit.mean()),
            "circuits_failing_fit": mp.index[~fit].tolist(),
            "circuits_failing_direction": mp.index[~dir_ok].tolist(),
        }

    crit = cfg["verdict_criteria"]
    a = level(crit["A_strong"], 0.9, 0.15)
    b = level(crit["B_usable_with_limitations"], 0.8, 0.30)
    verdict = (
        "A_STRONG"
        if a["passed"]
        else ("B_USABLE_WITH_LIMITATIONS" if b["passed"] else "C_NOT_DEFENSIBLE")
    )

    # ---- topology / measurement diagnostics (observation-only where stated)
    diag = []
    out_of_sund = {
        "CHAU_SU33_1": -1,
        "SU33_CHAU_2": 1,
        "SU33_CHAU_3": 1,
        "SU33_LBUZT_1": -1,
        "SU33_LBUZT_2_(1)": 1,
        "SU33_LEWS_1": -1,
        "SU33_LEWS_2": 1,
        "SU33_SU11_1": 1,
        "SU33_SU11_3": 1,
        "SU33_SU11_4": -1,
        "SUND_LBUZ_3(1)": 1,
        "lne_SUND_CHAP": 1,
    }
    outflow = sum(s.circuit_p[k] * v for k, v in out_of_sund.items())
    t2_proxy = ms.transformer_demand(s, "sundon_11kv_t2", "hv_to_lv")
    kcl = (imp - outflow - t2_proxy).dropna()
    diag.append(
        {
            "diagnostic": "observation-only KCL at Sundon 33 kV busbar",
            "detail": "import(GT) − Σ metered outgoing P − Sundon T2 P (proxy for "
            "current-only SU33_SU11_2)",
            "n": len(kcl),
            "median_mw": float(kcl.median()) if len(kcl) else None,
            "p05_mw": float(kcl.quantile(0.05)) if len(kcl) else None,
            "p95_mw": float(kcl.quantile(0.95)) if len(kcl) else None,
        }
    )
    for line, mm in meters.items():
        if mm.mapping != "exact":
            diag.append(
                {"diagnostic": f"meter mapping {mm.mapping}", "detail": f"{line}: {mm.note}"}
            )
    for c in region["measurements"]["circuits"]:
        if not c["node_match"]:
            diag.append(
                {
                    "diagnostic": "operational index node mismatch",
                    "detail": f"{c['ltds_line_name']}: index {c['from_node']}->{c['to_node']} "
                    "not both LTDS nodes",
                }
            )
    pairs = net.line.apply(
        lambda r: (
            tuple(sorted((r.from_bus, r.to_bus))),
            round(r.r_ohm_per_km * r.length_km, 6),
            round(r.x_ohm_per_km * r.length_km, 6),
        ),
        axis=1,
    )
    for _key, grp in net.line.groupby(pairs):
        if len(grp) > 1:
            diag.append(
                {
                    "diagnostic": "LTDS duplicate-looking records (same nodes, identical R/X)",
                    "detail": ", ".join(grp["name"]),
                }
            )
    for line in s.circuit_p.columns:
        ser = s.circuit_p[line].dropna()
        if len(ser):
            idle = float((ser.abs() < 0.05).mean())
            if idle > 0.2:
                diag.append(
                    {
                        "diagnostic": "circuit frequently idle (|P| < 0.05 MW)",
                        "detail": f"{line}: {idle:.1%} of {len(ser)} half-hours",
                    }
                )
    diag.append(
        {
            "diagnostic": "customer circuit beyond rating",
            "detail": "lne_SUND_CHAP |P| > 1.0×rating in "
            f"{dq['lne_SUND_CHAP (input) beyond 1.0x rating']} "
            f"half-hours, > 1.5×rating in {dq['lne_SUND_CHAP (input) beyond 1.5x rating']} "
            f"(rating {rating_mva(net, chap_line):.1f} MVA); observed range "
            f"{chap.min():.1f}..{chap.max():.1f} MW",
        }
    )
    # data-only unobserved-injection residual (import − Σ observed nodal demand), all timestamps
    resid = (imp - dp.sum(axis=1, min_count=dp.shape[1])).dropna()
    by_hour = resid.groupby(resid.index.hour).median()
    diag.append(
        {
            "diagnostic": "data-only residual import − Σ nodal demand (≈ losses − unobserved "
            "33 kV customer injection)",
            "detail": f"n={len(resid)}; median {resid.median():.2f} MW; hourly median range "
            f"{by_hour.min():.2f}..{by_hour.max():.2f} MW "
            f"(min at {int(by_hour.idxmin())}h UTC)",
        }
    )
    # switching/outage signature: metered ~0 while the all-closed planning model carries flow
    prim_rows = res[(res.scenario == cfg["primary_scenario"]) & res.line.isin(p_targets)]
    for line, g in prim_rows.groupby("line"):
        k = int(((g["obs_p"].abs() < 0.05) & (g["sim_p"].abs() > 1.0)).sum())
        if k:
            diag.append(
                {
                    "diagnostic": "possible open circuit / outage (planning model assumes closed)",
                    "detail": f"{line}: observed |P| < 0.05 MW while model > 1 MW in {k} of "
                    f"{g['obs_p'].notna().sum()} sampled states",
                    "n": k,
                }
            )
    # residual vs the battery-customer circuit, separated by hour band (PV = 0 at night)
    chap_r = s.circuit_p["lne_SUND_CHAP"].reindex(resid.index)
    for label, hours in [
        ("night 22-03 UTC (PV = 0)", [22, 23, 0, 1, 2, 3]),
        ("midday 10-14 UTC", [10, 11, 12, 13, 14]),
    ]:
        x = pd.concat([resid, chap_r], axis=1).dropna()
        x = x[x.index.hour.isin(hours)]
        x.columns = ["r", "c"]
        k = np.polyfit(x["c"], x["r"], 1) if len(x) > 10 else [np.nan, np.nan]
        diag.append(
            {
                "diagnostic": f"residual vs lne_SUND_CHAP flow, {label}",
                "detail": f"corr {x['r'].corr(x['c']):+.3f}, slope {k[0]:+.3f} "
                "(0 expected if the customer meter and the import meters agree)",
                "n": len(x),
            }
        )
    calm = resid[chap_r.abs() < 2]
    for season, months in [("summer May-Aug", [5, 6, 7, 8]), ("winter Nov-Feb", [11, 12, 1, 2])]:
        mid = calm[calm.index.hour.isin([10, 11, 12, 13, 14]) & calm.index.month.isin(months)]
        nig = calm[calm.index.hour.isin([22, 23, 0, 1, 2, 3]) & calm.index.month.isin(months)]
        diag.append(
            {
                "diagnostic": f"PV signature, battery idle (|CHAP| < 2 MW), {season}",
                "detail": "median residual midday − night (negative = unobserved midday "
                "injection, e.g. 33 kV PV)",
                "n": len(mid) + len(nig),
                "median_mw": float(mid.median() - nig.median()) if len(mid) and len(nig) else None,
            }
        )
    inputs = {
        **{
            f"tx:{t}": s.tx_p[t] if cfg["transformer_series"].get(t) else s.tx_i[t]
            for t in cfg["import_series"]
        },
        **{f"load:{k}": v for k, v in dp.items()},
    }
    avail = pd.DataFrame({k: v.reindex(dp.index).notna() for k, v in inputs.items()})
    by_year = avail.groupby(avail.index.year).mean().round(3)
    for col in by_year.columns:
        diag.append(
            {
                "diagnostic": "input availability by year",
                "detail": f"{col}: " + ", ".join(f"{y}={v:.0%}" for y, v in by_year[col].items()),
            }
        )
    pd.DataFrame(diag).to_csv(TABLES / f"e2_topology_diagnostics{sfx}.csv", index=False)

    # ---- figures
    cls = pd.read_csv(TABLES / "e1_measurement_series.csv").set_index("series_id")["class"]
    edge_class = {}
    for line in net.line.name:
        edge_class[line] = {"active_power": "active_power", "current_only": "current_only"}.get(
            cls.get(line, ""), "none"
        )
    edge_class["SU33_LBUZT_2_(5)"] = "active_power"  # metered via composite SU33_LBUZT_2_(1)
    plots.plot_topology(
        net,
        FIGS / f"e2_measurement_coverage{sfx}.png",
        edge_class=edge_class,
        title="Sundon: half-hourly measurement coverage per LTDS circuit "
        "(composite SU33_LBUZT_2_(1) drawn on its first LTDS section)",
    )
    for name in scen:
        g = res[(res.scenario == name) & res.line.isin(p_targets + ["IMPORT_TOTAL"])]
        plots.plot_obs_vs_sim(
            g.rename(columns={"obs_p": "obs", "sim_p": "sim"}),
            FIGS / f"e2_obs_vs_sim_{name}{sfx}.png",
            f"Active power, simulated vs observed (MW) — scenario {name}"
            + (" [PRIMARY]" if name == prim else " [diagnostic]"),
        )
    gi = res[(res.scenario == prim) & res.line.isin(i_targets)]
    plots.plot_obs_vs_sim(
        gi.rename(columns={"obs_i": "obs", "sim_i": "sim"}),
        FIGS / f"e2_current_validation{sfx}.png",
        f"Current magnitude, simulated vs observed (A) — {prim}",
    )
    fig, ax = plt.subplots(1, 2, figsize=(12, 4))
    hr = resid.groupby(resid.index.hour)
    ax[0].fill_between(
        hr.quantile(0.1).index,
        hr.quantile(0.1),
        hr.quantile(0.9),
        alpha=0.3,
        color="#0571b0",
        label="p10–p90",
    )
    ax[0].plot(hr.median().index, hr.median(), color="#0571b0", label="median")
    ax[0].axhline(0, color="#999", lw=0.8)
    ax[0].set_xlabel("hour (UTC)")
    ax[0].set_ylabel("MW")
    ax[0].set_title("import − Σ observed nodal demand, by hour", fontsize=9)
    ax[0].legend(fontsize=8)
    mo = resid.groupby(resid.index.to_period("M").astype(str)).median()
    ax[1].plot(range(len(mo)), mo.to_numpy(), marker="o", ms=3, color="#e66101")
    ax[1].set_xticks(range(0, len(mo), 3))
    ax[1].set_xticklabels(mo.index[::3], rotation=60, fontsize=7)
    ax[1].axhline(0, color="#999", lw=0.8)
    ax[1].set_title("monthly median of the same residual", fontsize=9)
    fig.suptitle(
        "Unobserved 33 kV customers + losses (data only; negative = net injection)", fontsize=10
    )
    fig.tight_layout()
    fig.savefig(FIGS / f"e2_unobserved_residual{sfx}.png", dpi=150)
    plt.close(fig)

    states = (
        res[res.line == "_state"]
        .groupby("scenario")[["vm_min", "vm_max", "max_line_loading", "max_trafo_loading"]]
        .agg(["min", "max"])
    )
    summary = {
        "variant": cfg["scenario"],
        "measurement_scales": scales,
        "observed_outages": excluded,
        "selection": sel_counts,
        "data_quality_dropped_or_flagged": dq,
        "sign_conventions": signs.to_dict(orient="records"),
        "meter_mapping": {
            k: {"mapping": v.mapping, "end": v.end, "note": v.note} for k, v in meters.items()
        },
        "flagged_circuits": flagged,
        "core_circuits": core,
        "convergence": run_df.groupby("scenario")["converged"].mean().to_dict(),
        "v0_residual_mw": run_df[run_df.scenario == prim]["v0_residual_mw"]
        .describe()
        .round(3)
        .to_dict(),
        "state_ranges": states.set_axis(["|".join(c) for c in states.columns], axis=1)
        .round(4)
        .to_dict(orient="index")
        if len(states)
        else {},
        "aggregate": agg,
        "verdict": {
            "primary_scenario": prim,
            "level": verdict,
            "A": a,
            "B": b,
            "pf_convergence_rate": conv,
            "import_nmae": imp_nmae,
        },
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    show = metrics[metrics.scenario == prim][
        ["line", "kind", "core", "n", "mae", "rmse", "bias", "r", "nmae", "direction_agreement"]
    ]
    print(
        json.dumps(
            {
                "selection": sel_counts,
                "convergence": summary["convergence"],
                "verdict": summary["verdict"],
            },
            indent=1,
            default=str,
        )
    )
    print(show.round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
