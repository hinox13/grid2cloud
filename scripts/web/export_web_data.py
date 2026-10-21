# ruff: noqa: E501
"""Export the frozen Explorer bundles (data/demo) as static browser assets for the React site.

    .venv/bin/python scripts/web/export_web_data.py            # writes web/public/data
    .venv/bin/python scripts/web/export_web_data.py --check    # exit 1 if web/public/data is stale

Reads ONLY data/demo (the published, licence-gated bundles built by scripts/build_demo_events.py and
scripts/economic_impact/build_cloud_impact_bundle.py) and the Explorer's own labels (demo/c2g/theme.py).
It recomputes nothing physical: no AC power flow, no GENCO inference, no download. It reshapes tables
into JSON, copies the observed WebP frames unchanged, and writes every number the story states as an
explicit claim (value, unit, display string, provenance class, source) so the browser only formats.
Output is deterministic: the same inputs give byte-identical files (manifest.json lists their sha256).
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "data/demo"
OUT = ROOT / "web/public/data"
STORY_EVENT = "jun15_cloud_clearing"
PLANT = "ECR:955"  # the explicit 6 MW 33 kV plant varied in the counterfactuals
H = 0.5  # hours per settlement period
SCHEMA = "web-1"

sys.path.insert(0, str(ROOT / "demo"))
from c2g import theme as T  # noqa: E402  (labels only; no Streamlit call is made)


def r(x: float, d: int = 6) -> float | None:
    """Round for JSON; NaN becomes null."""
    x = float(x)
    return None if not np.isfinite(x) else round(x, d)


def iso(t: pd.Timestamp) -> str:
    return pd.Timestamp(t).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def hhmm(t: pd.Timestamp) -> str:
    return pd.Timestamp(t).tz_convert("UTC").strftime("%H:%M")


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def num(x: float, spec: str) -> str:
    """Display string with a true minus sign, like the Explorer (theme.num)."""
    return format(x, spec).replace("-", "−")


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")


# ----------------------------------------------------------------------------- network
def network(nodes: pd.DataFrame, edges: pd.DataFrame) -> dict:
    layout = json.loads((DEMO / "network_layout.json").read_text())
    return {
        "note": "Electrical schematic (not geographic). Coordinates from configs/app/network_layout.yaml via the Explorer bundle.",
        "n_buses_model": int(sum(len(m.split(";")) for m in nodes.members)),
        "n_branches_model": int(sum(len(e.split(";")) for e in edges.elements)),
        "nodes": [
            {
                "bus": int(n.bus),
                "key": n.node_key,
                "label": n.label,
                "members": n.members.split(";"),
                "kv": r(n.vn_kv, 1),
                "lat": r(n.lat),
                "lon": r(n.lon),
                "x": r(n.schematic_x, 3),
                "y": r(n.schematic_y, 3),
                "role": n.role,
                "slack": bool(n.is_slack),
                "substation": n.substation,
            }
            for n in nodes.itertuples()
        ],
        "edges": [
            {
                "id": e.branch_id,
                "a": int(e.bus_a),
                "b": int(e.bus_b),
                "from": e.from_node,
                "to": e.to_node,
                "kind": e.kind,
                "elements": e.elements.split(";"),
                "rating_mva": r(e.rating_mva, 3),
            }
            for e in edges.itertuples()
        ],
        "layout": layout,
    }


# ----------------------------------------------------------------------------- events
def event(bundle_id: str, out: Path) -> dict:
    d = DEMO / "events" / bundle_id
    rd = lambda n: pd.read_parquet(d / n)  # noqa: E731
    meta = json.loads((d / "metadata.json").read_text())
    frames = rd("satellite/frames.parquet")
    fleet = rd("fleet_pv.parquet")
    gen = rd("pv_generation.parquet")
    irr = rd("irradiance.parquet")
    assets = rd("assets.parquet")
    summary = rd("summary.parquet")
    bus = pd.concat([rd("ac_reference.parquet"), rd("genco.parquet")], ignore_index=True)
    br = pd.concat([rd("ac_reference_branches.parquet"), rd("genco_branches.parquet")], ignore_index=True)
    nodes, edges = rd("network_nodes.parquet"), rd("network_edges.parquet")
    loads = rd("loads.parquet")

    fdir = out / "events" / bundle_id / "frames"
    fdir.mkdir(parents=True, exist_ok=True)
    frame_rows = []
    for f in frames.itertuples():
        src = d / f.image_file
        name = Path(f.image_file).name
        shutil.copyfile(src, fdir / name)  # observed imagery: copied byte-for-byte, never re-encoded
        lon0, lat0, lon1, lat1 = (float(v) for v in f.bbox_wgs84)
        frame_rows.append(
            {
                "t": iso(f.timestamp_utc),
                "served": iso(f.served_time_utc),
                "file": f"events/{bundle_id}/frames/{name}",
                "bbox": [lon0, lat0, lon1, lat1],
                "product": f.product,
                "source_event": f.source_event_id,
                "sha256": sha256(src),
            }
        )
    times = list(frames.timestamp_utc)
    # active fleet: assets with capacity in this event's PV table (later-registered plants carry 0)
    cap = gen.groupby("asset_id").capacity_mw.max()
    active = [a for a in assets.itertuples() if cap.get(a.asset_id, 0) > 0]
    active.sort(key=lambda a: -cap[a.asset_id])
    gp = gen.pivot(index="timestamp_utc", columns="asset_id", values="p_mw").reindex(times)
    gcf = gen.pivot(index="timestamp_utc", columns="asset_id", values="capacity_factor").reindex(times)
    kc = irr.pivot(index="timestamp_utc", columns="asset_id", values="clearsky_index").reindex(times)
    ghi = irr.pivot(index="timestamp_utc", columns="asset_id", values="ghi_wm2").reindex(times)
    slots = sorted(summary.timestamp_utc.unique())
    models = ["AC", *meta["models"]]
    edge_ids = list(edges.branch_id)
    flows: dict[str, dict[str, dict]] = {}
    for m in models:
        flows[m] = {}
        for s in slots:
            b = br[(br.model == m) & (br.timestamp_utc == s)].set_index("branch_id")
            v = bus[(bus.model == m) & (bus.timestamp_utc == s)].set_index("bus").sort_index()
            flows[m][iso(s)] = {
                "p_ab_mw": [r(b.at[e, "p_ab_mw"], 4) if e in b.index else None for e in edge_ids],
                "loading_pct": [r(b.at[e, "loading_pct"], 3) if e in b.index else None for e in edge_ids],
                "vm_pu": [r(v.at[i, "vm_pu"], 5) if i in v.index else None for i in nodes.bus],
            }
    summ = {}
    for m in models:
        s = summary[summary.model == m].set_index("timestamp_utc").reindex(slots)
        summ[m] = {
            c: [r(x, 5) for x in s[c]]
            for c in ("import_mw", "max_loading_pct", "PBE_mean", "P_residual", "V_error", "branch_P_error")
        }
    ac = summary[summary.model == "AC"].set_index("timestamp_utc").reindex(slots)
    chap = loads[loads.node_key == "EPN:CHAP31"].set_index("timestamp_utc").reindex(slots)
    resp = pd.read_parquet(DEMO / "pv_response_s1.parquet").set_index("scenario")
    co = json.loads((DEMO / "catalog.json").read_text())["ols_coefficients_s1"]
    ids = meta["grid_scenarios"]
    decomposition = []
    for j in range(1, len(ids)):
        a, b = resp.loc[ids[j - 1]], resp.loc[ids[j]]
        d = {k: float(b[k] - a[k]) for k in ("load_mw", "chap31_mw", "pv_injection_mw")}
        decomposition.append(
            {
                "from": iso(a.timestamp_utc),
                "to": iso(b.timestamp_utc),
                "delta": {k: r(v, 4) for k, v in d.items()},
                "terms": {
                    m: {
                        "pv": r(co[m]["pv"] * d["pv_injection_mw"], 4),
                        "load": r(co[m]["load"] * d["load_mw"], 4),
                        "battery": r(co[m]["chap31"] * d["chap31_mw"], 4),
                        "total": r(b[f"import_{m}"] - a[f"import_{m}"], 4),
                    }
                    for m in models
                },
            }
        )
    obj = {
        "id": bundle_id,
        "title": meta["title"],
        "story": meta["story"],
        "class_name": meta["class_name"],
        "selection_criteria": meta["selection_criteria"],
        "provenance": meta["provenance"],
        "source_events": meta["source_events"],
        "event_metrics": [{k: (r(v, 4) if isinstance(v, float) else v) for k, v in e.items()} for e in meta["event_metrics"]],
        "active_pv_capacity_mw": r(meta["active_pv_capacity_mw"], 6),
        "satellite_step_minutes": meta["satellite_step_minutes"],
        "grid_step_minutes": meta["grid_step_minutes"],
        "models": models,
        "frames": frame_rows,
        "fleet_pv_mw": [r(x, 5) for x in fleet.set_index("timestamp_utc").reindex(times).fleet_pv_mw],
        "assets": [
            {
                "id": a.asset_id,
                "capacity_mw": r(cap[a.asset_id], 6),
                "kv": r(a.connection_voltage_kv, 1),
                "lat": r(a.lat),
                "lon": r(a.lon),
                "p_mw": [r(x, 5) for x in gp[a.asset_id]],
                "capacity_factor": [r(x, 5) for x in gcf[a.asset_id]],
                "clearsky_index": [r(x, 5) for x in kc[a.asset_id]] if a.asset_id in kc else None,
                "ghi_wm2": [r(x, 2) for x in ghi[a.asset_id]] if a.asset_id in ghi else None,
            }
            for a in active
        ],
        "plant_id": PLANT,
        "grid_slots": [iso(s) for s in slots],
        "grid_scenarios": meta["grid_scenarios"],
        "summary": summ,
        "grid_inputs": {
            "hv_pv_mw": [r(x, 5) for x in ac.p_hv_injected_mw],
            "load_incl_battery_mw": [r(x, 5) for x in ac.load_p_mw],
            "battery_chap31_mw": [r(x, 5) for x in chap.p_mw],
            "mean_kc": [r(x, 5) for x in ac.mean_kc],
            "lines_out": [x or "" for x in ac.lines_out],
        },
        "flows": flows,
        "edge_ids": edge_ids,
        "decomposition": decomposition,
    }
    write_json(out / "events" / bundle_id / "event.json", obj)
    return obj


# ----------------------------------------------------------------------------- claims
def claims(story: dict, evo: pd.DataFrame, cat: dict, periods: pd.DataFrame, season: dict, net: dict) -> list[dict]:
    """Every number the Experience states, computed here once from the frozen sources."""
    C: list[dict] = []

    def add(cid: str, value: float, unit: str, display: str, prov: str, source: str, note: str = "") -> None:
        C.append({"id": cid, "value": r(value, 6), "unit": unit, "display": display, "provenance": prov, "source": source, "note": note})

    times = [f["t"] for f in story["frames"]]
    raw = pd.read_parquet(DEMO / "events" / STORY_EVENT / "fleet_pv.parquet")
    fleet = {iso(t): float(v) for t, v in zip(raw.timestamp_utc, raw.fleet_pv_mw, strict=True)}
    a, b = "2024-06-15T11:00:00Z", "2024-06-15T11:30:00Z"
    ev = "data/demo/events/jun15_cloud_clearing"
    add("fleet_pv_1100", fleet[a], "MW", num(fleet[a], ".2f"), "derived", f"{ev}/fleet_pv.parquet", "satellite-derived PV, all active local plants, 15-minute estimate")
    add("fleet_pv_1130", fleet[b], "MW", num(fleet[b], ".2f"), "derived", f"{ev}/fleet_pv.parquet")
    add("fleet_pv_delta", fleet[b] - fleet[a], "MW", num(fleet[b] - fleet[a], "+.2f"), "derived", f"{ev}/fleet_pv.parquet", "difference of the unrounded values")
    add("fleet_capacity", story["active_pv_capacity_mw"], "MW", num(story["active_pv_capacity_mw"], ".3f"), "derived", f"{ev}/metadata.json")
    plant_cap = next(x["capacity_mw"] for x in story["assets"] if x["id"] == PLANT)
    add("plant_capacity", plant_cap, "MW", num(plant_cap, ".0f"), "observed", f"{ev}/pv_generation.parquet", "the one plant the economic case study varies")
    other = story["active_pv_capacity_mw"] - plant_cap
    add("other_pv_capacity", other, "MW", num(other, ".1f"), "derived", f"{ev}/metadata.json", "other local PV, inside the reconstructed loads, never varied")
    add("n_pv_plants", len(story["assets"]), "plants", str(len(story["assets"])), "observed", f"{ev}/pv_generation.parquet", "registered PV assets active in 2024 (UKPN Embedded Capacity Register)")
    add("n_frames", len(times), "frames", str(len(times)), "observed", f"{ev}/satellite/frames.parquet", f"{hhmm(pd.Timestamp(times[0]))}–{hhmm(pd.Timestamp(times[-1]))} UTC, 15-minute")
    ia, ib = times.index(a), times.index(b)
    kc = pd.read_parquet(DEMO / "events" / STORY_EVENT / "irradiance.parquet").query("asset_id == @PLANT").set_index("timestamp_utc").clearsky_index
    plant = {"clearsky_index": [float(kc[pd.Timestamp(t)]) for t in times]}
    add("kc_plant_1100", plant["clearsky_index"][ia], "", num(plant["clearsky_index"][ia], ".2f"), "derived", f"{ev}/irradiance.parquet", "LSA SAF clear-sky index at the 6 MW plant")
    add("kc_plant_1130", plant["clearsky_index"][ib], "", num(plant["clearsky_index"][ib], ".2f"), "derived", f"{ev}/irradiance.parquet")
    m = story["event_metrics"][-1]
    add("cloudy_frac_start", m["field_frac_cloudy_start"] * 100, "%", f"{m['field_frac_cloudy_start'] * 100:.0f}", "derived", f"{ev}/metadata.json", f"cloudy fraction of the satellite field, event {m['event_id']}")
    add("cloudy_frac_end", m["field_frac_cloudy_end"] * 100, "%", f"{m['field_frac_cloudy_end'] * 100:.0f}", "derived", f"{ev}/metadata.json")
    add("n_buses", net["n_buses_model"], "buses", str(net["n_buses_model"]), "derived", "data/demo/network_nodes.parquet", "members of the drawn nodes (a coupled 132 kV busbar pair is drawn as one)")
    add("n_branches", net["n_branches_model"], "branches", str(net["n_branches_model"]), "derived", "data/demo/network_edges.parquet", "elements of the drawn edges (two double-section 33 kV cables are drawn as one each)")

    slots = story["grid_slots"]
    sm = pd.read_parquet(DEMO / "events" / STORY_EVENT / "summary.parquet").query("model == 'AC'")
    imp = {iso(t): float(v) for t, v in zip(sm.timestamp_utc, sm.import_mw, strict=True)}
    add("import_ac_1100", imp[a], "MW", num(imp[a], ".1f"), "simulated", f"{ev}/summary.parquet", "AC reconstruction of the historical state")
    add("import_ac_1130", imp[b], "MW", num(imp[b], ".1f"), "simulated", f"{ev}/summary.parquet")
    add("import_ac_hist_delta", imp[b] - imp[a], "MW", num(imp[b] - imp[a], "+.1f"), "simulated", f"{ev}/summary.parquet", "loads, battery and solar all changed")

    # historical change split with the published S1 regression (the PV response page's decomposition)
    resp = pd.read_parquet(DEMO / "pv_response_s1.parquet").set_index("scenario")
    sa, sb = story["grid_scenarios"][slots.index(a)], story["grid_scenarios"][slots.index(b)]
    co = cat["ols_coefficients_s1"]["AC"]
    for k, col, coef in (("load", "load_mw", "load"), ("battery", "chap31_mw", "chap31"), ("pv", "pv_injection_mw", "pv")):
        x0, x1 = float(resp.at[sa, col]), float(resp.at[sb, col])
        add(f"hist_{k}_1100", x0, "MW", num(x0, ".1f"), "derived", "data/demo/pv_response_s1.parquet", "UKPN half-hourly operational data" if k != "pv" else "the 6 MW plant, satellite-derived")
        add(f"hist_{k}_1130", x1, "MW", num(x1, ".1f"), "derived", "data/demo/pv_response_s1.parquet", "UKPN half-hourly operational data" if k != "pv" else "the 6 MW plant, satellite-derived")
        add(f"hist_{k}_term", co[coef] * (x1 - x0), "MW", num(co[coef] * (x1 - x0), "+.1f"), "simulated", "data/demo/catalog.json (ols_coefficients_s1.AC) × input change", "published S1 coefficient × this step's input change")
    terms = sum(co[c] * (float(resp.at[sb, k]) - float(resp.at[sa, k])) for c, k in (("load", "load_mw"), ("chap31", "chap31_mw"), ("pv", "pv_injection_mw")))
    add("hist_remainder", (imp[b] - imp[a]) - terms, "MW", num((imp[b] - imp[a]) - terms, "+.1f"), "simulated", "difference", "nonlinearity and losses not captured by the linear terms")

    p = periods.set_index(periods.slot_utc.dt.strftime("%H:%M"))
    q = p.loc["11:00"]
    add("plant_pv_obs_1100", q.plant_pv_mw, "MW", num(q.plant_pv_mw, ".2f"), "derived", "data/demo/cloud_impact/periods_2024-06-15.parquet", "the 6 MW plant, observed sky")
    add("plant_pv_clear_1100", q.plant_pv_clear_mw, "MW", num(q.plant_pv_clear_mw, ".2f"), "hypothetical", "data/demo/cloud_impact/periods_2024-06-15.parquet", "the 6 MW plant, clear-sky estimate")
    add("plant_pv_cf_delta", q.plant_pv_clear_mw - q.plant_pv_mw, "MW", num(q.plant_pv_clear_mw - q.plant_pv_mw, "+.2f"), "hypothetical", "periods_2024-06-15.parquet")
    add("cf_import_ac_obs_1100", q.import_AC_observed_mw, "MW", num(q.import_AC_observed_mw, ".1f"), "simulated", "periods_2024-06-15.parquet")
    add("cf_import_ac_clear_1100", q.import_AC_clear_sky_mw, "MW", num(q.import_AC_clear_sky_mw, ".1f"), "hypothetical", "periods_2024-06-15.parquet", "AC re-solved with only the plant at clear sky")
    for mdl, prov in (("AC", "simulated"), ("E5c", "predicted"), ("E5d", "predicted")):
        dv = float(q[f"import_{mdl}_clear_sky_mw"] - q[f"import_{mdl}_observed_mw"])
        add(f"cf_{mdl}_1100", dv, "MW", num(dv, "+.2f"), prov, "periods_2024-06-15.parquet", "import change if the plant had its clear-sky output at 11:00, all else fixed")

    ev_row = evo.set_index("model")
    add("n_states", ev_row.at["E5d", "n"], "states", f"{int(ev_row.at['E5d', 'n']):,}", "simulated", "data/demo/model_evolution.csv", "real half-hourly 2024 states (S1)")
    add("slope_AC", ev_row.at["E5d", "ac_slope_pv"], "MW/MW", num(ev_row.at["E5d", "ac_slope_pv"], "+.2f"), "simulated", "data/demo/model_evolution.csv")
    for mdl in ("zero_shot", "E5", "E5b", "E5c", "E5d"):
        add(f"slope_{mdl}", ev_row.at[mdl, "genco_slope_pv"], "MW/MW", num(ev_row.at[mdl, "genco_slope_pv"], "+.2f"), "predicted", "data/demo/model_evolution.csv")
        add(f"bias_{mdl}", ev_row.at[mdl, "import_bias_mw"], "MW", num(ev_row.at[mdl, "import_bias_mw"], "+.1f"), "predicted", "data/demo/model_evolution.csv", "mean predicted minus AC import")
        add(f"import_mean_{mdl}", ev_row.at[mdl, "genco_import_mean_mw"], "MW", num(ev_row.at[mdl, "genco_import_mean_mw"], ".1f"), "predicted", "data/demo/model_evolution.csv")
    # model journey: state accuracy and response accuracy per stage, each from the published table
    for mdl in ("zero_shot", "E5", "E5b", "E5c", "E5d"):
        pbe = float(ev_row.at[mdl, "PBE_mean"])
        add(f"pbe_{mdl}", pbe, "MVA", f"{pbe:.3g}" if pbe < 1 else f"{pbe:.1f}", "predicted", "data/demo/model_evolution.csv", "mean nodal power-balance error over all real states")
        add(f"corr_{mdl}", ev_row.at[mdl, "import_corr"], "", f"{ev_row.at[mdl, 'import_corr']:.2f}", "predicted", "data/demo/model_evolution.csv", "correlation of predicted and AC import")
        add(f"sign_acc_{mdl}", ev_row.at[mdl, "import_sign_accuracy"] * 100, "%", f"{ev_row.at[mdl, 'import_sign_accuracy'] * 100:.1f}", "predicted", "data/demo/model_evolution.csv", "share of states with the import direction right")
        add(f"slope_load_{mdl}", ev_row.at[mdl, "genco_slope_load"], "MW/MW", num(ev_row.at[mdl, "genco_slope_load"], "+.2f"), "predicted", "data/demo/model_evolution.csv")
        add(f"slope_battery_{mdl}", ev_row.at[mdl, "genco_slope_chap31"], "MW/MW", num(ev_row.at[mdl, "genco_slope_chap31"], "+.2f"), "predicted", "data/demo/model_evolution.csv")
    add("slope_load_AC", ev_row.at["E5d", "ac_slope_load"], "MW/MW", num(ev_row.at["E5d", "ac_slope_load"], "+.2f"), "simulated", "data/demo/model_evolution.csv")
    add("slope_battery_AC", ev_row.at["E5d", "ac_slope_chap31"], "MW/MW", num(ev_row.at["E5d", "ac_slope_chap31"], "+.2f"), "simulated", "data/demo/model_evolution.csv")
    cut = (1 - ev_row.at["E5b", "PBE_mean"] / ev_row.at["E5", "PBE_mean"]) * 100
    add("pbe_cut_E5b_vs_E5", cut, "%", f"{cut:.0f}", "predicted", "data/demo/model_evolution.csv", "real-state power-balance error, envelope-tuned vs grid-tuned")
    wrong = (1 - ev_row.at["zero_shot", "import_sign_accuracy"]) * 100
    add("zero_shot_wrong_sign", wrong, "%", f"{wrong:.1f}", "predicted", "data/demo/model_evolution.csv", "share of real states where off-the-shelf GENCO gets the import direction wrong")
    err = resp["import_E5d"] - resp["import_AC"]
    for pct in (25, 75):
        add(f"e5d_offset_q{pct}", err.quantile(pct / 100), "MW", num(err.quantile(pct / 100), "+.0f"), "predicted", "data/demo/pv_response_s1.parquet", f"{pct}th percentile of E5d minus AC import over all real states")
    add("e5d_offset_pos", (err > 0).mean() * 100, "%", f"{(err > 0).mean() * 100:.0f}", "predicted", "data/demo/pv_response_s1.parquet", "share of real states where E5d's import is above AC")
    add("import_mean_AC", ev_row.at["E5d", "ac_import_mean_mw"], "MW", num(ev_row.at["E5d", "ac_import_mean_mw"], ".1f"), "simulated", "data/demo/model_evolution.csv")

    dd = periods.import_AC_observed_mw - periods.import_AC_clear_sky_mw
    e_day, v_day = float((dd * H).sum()), float((dd * H * periods.apx_gbp_per_mwh).sum())
    add("day_cloud_mwh", e_day, "MWh", num(e_day, ".2f"), "hypothetical", "periods_2024-06-15.parquet", "AC import, observed minus clear-sky plant, × 0.5 h, 24 half-hours")
    add("day_cloud_gbp", v_day, "GBP", f"£{v_day:,.0f}", "hypothetical", "periods_2024-06-15.parquet × Elexon APX", "illustrative valuation, not a realised cost or saving")
    add("day_periods", len(periods), "half-hours", str(len(periods)), "simulated", "periods_2024-06-15.parquet")
    add("day_first", 0, "", hhmm(periods.slot_utc.min()), "simulated", "periods_2024-06-15.parquet")
    add("day_last", 0, "", hhmm(periods.slot_utc.max()), "simulated", "periods_2024-06-15.parquet")
    add("day_sp_first", periods.settlement_period.min(), "", str(int(periods.settlement_period.min())), "observed", "periods_2024-06-15.parquet")
    add("day_sp_last", periods.settlement_period.max(), "", str(int(periods.settlement_period.max())), "observed", "periods_2024-06-15.parquet")
    add("day_apx_min", periods.apx_gbp_per_mwh.min(), "GBP/MWh", f"£{periods.apx_gbp_per_mwh.min():.0f}", "observed", "Elexon APX Market Index")
    add("day_apx_max", periods.apx_gbp_per_mwh.max(), "GBP/MWh", f"£{periods.apx_gbp_per_mwh.max():.0f}", "observed", "Elexon APX Market Index")
    d1 = float(q.import_AC_observed_mw - q.import_AC_clear_sky_mw)
    add("one_cloud_mw", d1, "MW", num(d1, ".3f"), "hypothetical", "periods_2024-06-15.parquet", "AC import, observed minus clear-sky plant, 11:00 half-hour")
    e1 = d1 * H
    add("one_cloud_mwh", e1, "MWh", num(e1, ".3f"), "hypothetical", "periods_2024-06-15.parquet", "11:00 half-hour only")
    add("one_apx", q.apx_gbp_per_mwh, "GBP/MWh", f"£{q.apx_gbp_per_mwh:.2f}", "observed", "Elexon APX Market Index, SP 25")
    add("one_cloud_gbp", e1 * q.apx_gbp_per_mwh, "GBP", f"£{e1 * q.apx_gbp_per_mwh:,.0f}", "hypothetical", "periods_2024-06-15.parquet × APX")
    for k, col in (("gen_obs", "plant_pv_mw"), ("gen_clear", "plant_pv_clear_mw"), ("imp_obs", "import_AC_observed_mw"), ("imp_clear", "import_AC_clear_sky_mw")):
        e = float((periods[col] * H).sum())
        add(f"day_{k}_mwh", e, "MWh", f"{e:,.1f}", "hypothetical" if "clear" in k else ("derived" if k.startswith("gen") else "simulated"), "periods_2024-06-15.parquet")
    for k, col in (("imp_obs", "import_AC_observed_mw"), ("imp_clear", "import_AC_clear_sky_mw")):
        v = float((periods[col] * H * periods.apx_gbp_per_mwh).sum())
        add(f"day_{k}_gbp", v, "GBP", f"£{v:,.0f}", "hypothetical" if "clear" in k else "simulated", "periods_2024-06-15.parquet × APX", "illustrative")

    add("season_periods", season["periods_valued"], "half-hours", f"{season['periods_valued']:,}", "simulated", "data/demo/cloud_impact/season.json")
    for k in ("pv_attributed", "cloud_attributed"):
        s = season[k]["AC"]
        add(f"season_{k}_mwh", s["energy_mwh"], "MWh", f"{s['energy_mwh']:,.2f}", "hypothetical", "season.json")
        add(f"season_{k}_gbp", s["value_apx_gbp"], "GBP", f"£{s['value_apx_gbp']:,.0f}", "hypothetical", "season.json", "illustrative")
    dc = season["daily_context"]
    add("season_days", dc["days"], "days", str(dc["days"]), "simulated", "season.json", "days with at least one valued half-hour")
    for k in ("median", "p90", "max"):
        add(f"season_day_{k}_gbp", dc[f"cloud_value_apx_gbp_{k}"], "GBP", f"£{dc[f'cloud_value_apx_gbp_{k}']:,.0f}", "hypothetical", "season.json", f"{k} over days of the cloud-attributed illustrative value")
    add("season_day_max_date", 0, "", pd.Timestamp(dc["max_day"]).strftime("%-d %B"), "simulated", "season.json")
    t = pd.to_datetime(resp.timestamp_utc)
    add("states_span", 0, "", f"{t.min():%B}–{t.max():%B %Y}", "simulated", "data/demo/pv_response_s1.parquet", "first and last month of the real half-hourly states")
    for mdl in ("accounting", "E5c", "E5d"):
        s = season["pv_attributed"][mdl]
        add(f"season_pv_err_{mdl}", s["value_apx_error_pct"], "%", num(s["value_apx_error_pct"], "+.1f"), "predicted" if mdl != "accounting" else "simulated", "season.json")
    absd = season["absolute_mode_diagnostic"]
    add("abs_mode_E5d_gbp", absd["E5d"]["error_vs_ac_gbp"], "GBP", f"£{absd['E5d']['error_vs_ac_gbp']:,.0f}", "predicted", "season.json", "overstatement if E5d's absolute import were priced")
    pct = 100 * absd["E5d"]["error_vs_ac_gbp"] / absd["AC"]["import_value_apx_gbp"]
    add("abs_mode_E5d_pct", pct, "%", f"{pct:.0f}", "predicted", "season.json")
    return C


# ----------------------------------------------------------------------------- main
def build(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    cat = json.loads((DEMO / "catalog.json").read_text())
    evo = pd.read_csv(DEMO / "model_evolution.csv")
    net = network(pd.read_parquet(DEMO / "network_nodes.parquet"), pd.read_parquet(DEMO / "network_edges.parquet"))
    write_json(out / "network.json", net)

    events = [event(e["event_id"], out) for e in cat["events"]]
    story = next(e for e in events if e["id"] == STORY_EVENT)
    write_json(
        out / "events/index.json",
        [{k: e[k] for k in ("event_id", "title", "story", "class_name", "time_start_utc", "time_end_utc", "n_frames", "n_grid_slots")} for e in cat["events"]],
    )

    models = json.loads((DEMO / "models.json").read_text())
    ladder = {m: (added, outcome) for m, added, outcome in T.LADDER}
    ci_cols = [c for c in evo.columns if c.endswith("_ci")]
    rows = []
    for row in evo.to_dict("records"):
        rec = {k: (r(v, 8) if isinstance(v, float) else v) for k, v in row.items() if k not in ci_cols}
        for c in ci_cols:
            lo, hi = (float(x) for x in str(row[c]).strip("[]").split(","))
            rec[c] = [lo, hi]
        rows.append(rec)
    write_json(
        out / "models.json",
        {
            "models": [
                {**{k: v for k, v in m.items() if k not in ("predictions", "dataset")}, "name": T.NAMES[m["id"]], "exp": T.EXP[m["id"]], "about": T.ABOUT[m["id"]], "verdict": T.VERDICT[m["id"]],
                 "ladder_added": ladder[m["id"]][0], "ladder_outcome": ladder[m["id"]][1]}
                for m in models
            ],
            "ac": {"name": T.NAMES["AC"], "about": T.ABOUT["AC"], "verdict": T.VERDICT["AC"]},
            "evolution": rows,
            "ols_coefficients_s1": cat["ols_coefficients_s1"],
            "published_tables": cat["published_tables"],
        },
    )

    resp = pd.read_parquet(DEMO / "pv_response_s1.parquet").sort_values("scenario")
    write_json(
        out / "pv_response.json",
        {
            "note": "One row per real half-hourly 2024 state (S1). partial_<model> = import with the load and battery terms of that model's published regression removed.",
            "scenario": [int(x) for x in resp.scenario],
            "t": [iso(x) for x in resp.timestamp_utc],
            **{c: [r(x, 4) for x in resp[c]] for c in resp.columns if c not in ("scenario", "timestamp_utc")},
        },
    )

    periods = pd.read_parquet(DEMO / "cloud_impact/periods_2024-06-15.parquet").sort_values("slot_utc")
    season = json.loads((DEMO / "cloud_impact/season.json").read_text())
    prov = json.loads((DEMO / "cloud_impact/provenance.json").read_text())
    write_json(
        out / "cloud_impact.json",
        {
            "periods": {
                "slot": [iso(x) for x in periods.slot_utc],
                "settlement_date": list(periods.settlement_date.astype(str)),
                **{c: [r(x, 5) if c != "settlement_period" else int(x) for x in periods[c]] for c in periods.columns if c not in ("slot_utc", "settlement_date")},
            },
            "derived": {
                "note": "Computed here, not in the browser: energy = MW difference × 0.5 h; value = energy × the same period's APX price (illustrative).",
                **{
                    f"cloud_{m}_{k}": [r(x, 5) for x in v]
                    for m in ("AC", "E5c", "E5d")
                    for k, v in (
                        ("mw", periods[f"import_{m}_observed_mw"] - periods[f"import_{m}_clear_sky_mw"]),
                        ("mwh", (periods[f"import_{m}_observed_mw"] - periods[f"import_{m}_clear_sky_mw"]) * H),
                        ("gbp", (periods[f"import_{m}_observed_mw"] - periods[f"import_{m}_clear_sky_mw"]) * H * periods.apx_gbp_per_mwh),
                    )
                },
                "plant_pv_mwh": [r(x, 5) for x in periods.plant_pv_mw * H],
                "plant_pv_clear_mwh": [r(x, 5) for x in periods.plant_pv_clear_mw * H],
                "import_obs_mwh": [r(x, 5) for x in periods.import_AC_observed_mw * H],
                "import_clear_mwh": [r(x, 5) for x in periods.import_AC_clear_sky_mw * H],
                "import_obs_gbp": [r(x, 4) for x in periods.import_AC_observed_mw * H * periods.apx_gbp_per_mwh],
                "import_clear_gbp": [r(x, 4) for x in periods.import_AC_clear_sky_mw * H * periods.apx_gbp_per_mwh],
            },
            "season": season,
            "season_dates": sorted({x.strftime("%Y-%m-%d") for x in pd.to_datetime(resp.timestamp_utc)}),
            "definitions": prov["definitions"],
            "sources": prov["sources"],
            "apx_gap": {"slot_utc": "2024-04-13T07:00:00Z", "settlement_period": 17, "value_bound_gbp": 4.14,
                        "source": "reports/economic_impact/methodology.md (missing prices)"},
        },
    )

    att = json.loads((DEMO / "attribution.json").read_text())
    write_json(
        out / "attribution.json",
        {**att, "economic_sources": prov["sources"], "economic_gate_decisions": prov["gate_decisions"], "footer": T.ATTRIBUTION_FOOTER,
         "bundle": {"schema_version": cat["schema_version"], "git_commit": cat["git_commit"]}},
    )

    write_json(out / "claims.json", claims(story, evo, cat, periods, season, net))

    sources = sorted(p for p in DEMO.rglob("*") if p.is_file() and p.name != ".gitkeep")
    outputs = sorted(p for p in out.rglob("*") if p.is_file())
    write_json(
        out / "manifest.json",
        {
            "schema": SCHEMA,
            "generator": "scripts/web/export_web_data.py",
            "inputs": {str(p.relative_to(ROOT)): sha256(p) for p in sources},
            "outputs": {str(p.relative_to(out)): sha256(p) for p in outputs},
        },
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--check", action="store_true", help="rebuild to a temporary folder and compare with --out")
    a = ap.parse_args()
    if not a.check:
        build(a.out)
        print(f"wrote {sum(1 for _ in a.out.rglob('*') if _.is_file())} files to {a.out}")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        build(Path(tmp))
        cmp = filecmp.dircmp(tmp, a.out)
        stale: list[str] = []

        def walk(c: filecmp.dircmp, pre: str = "") -> None:
            stale.extend(pre + x for x in c.left_only + c.right_only + c.diff_files)
            for k, sub in c.subdirs.items():
                walk(sub, f"{pre}{k}/")

        walk(cmp)
        if stale:
            print("STALE:", *stale, sep="\n  ")
            return 1
    print("web data up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
