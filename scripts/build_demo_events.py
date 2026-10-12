"""Cloud2Grid Explorer — build the precomputed event bundles the Streamlit demo reads.

    uv run python scripts/build_demo_events.py

Offline and read-only with respect to the research: it REPLAYS frozen results. No AC power flow,
GENCO inference, satellite download or training happens here or in the app. Inputs:

    frozen hero events      configs/app/demo_events.yaml (E4 heroes, never re-selected)
    grid states             S1_WEATHER_ALIGNED real-2024 states (AC targets + frozen predictions
                            of every model listed in the config, from their own experiments)
    satellite imagery       E-View frames already fetched by scripts/fetch_event_frames.py
    satellite-derived PV    data/processed/satellite/sundon/*.parquet (E3)
    model evolution         frozen published tables (copied verbatim, sha256 recorded)

Every source is checked by the licence gate for `redistribute_derived`; the build stops if any is
refused. Output (schema metadata/event_bundle_schema.yaml v0.3):

    data/demo/catalog.json, models.json, model_evolution.csv, pv_response_s1.parquet,
    attribution.json, network_nodes.parquet, network_edges.parquet
    data/demo/events/<bundle_id>/...   one replay per hero event
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from PIL import Image

from cloud2grid.evaluation import genco_metrics as gm
from cloud2grid.genco.adaptation import ref_import
from cloud2grid.licensing import gate
from cloud2grid.licensing.registry import REPO_ROOT, Registry
from cloud2grid.network.states import StateBuilder

CFG = yaml.safe_load((REPO_ROOT / "configs/app/demo_events.yaml").read_text())
ENV = yaml.safe_load((REPO_ROOT / "configs/experiments/e5b_operating_envelope.yaml").read_text())
LAYOUT = yaml.safe_load((REPO_ROOT / "configs/app/network_layout.yaml").read_text())
MC = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_matched_control.yaml").read_text())
HEROES = yaml.safe_load(
    (REPO_ROOT / "configs/experiments/e5_topology_adaptation.yaml").read_text()
)["repeat_e4"]["heroes"]
NET = "sundon_33kv"
OUT = REPO_ROOT / CFG["out_dir"]
SAT = REPO_ROOT / "data/processed/satellite/sundon"
PV_NODES = ENV["hv_generation"]["nodes"]
BATT = ENV["storage"]["node"]
LOAD_NODES = [n for s in ENV["primary_sites"].values() for n in s["node_shares"]]
# docs/SATELLITE_SCENARIO_CONSTRUCTION.md, input table
LOAD_CLASS = {
    "EPN:SUPR52": "OBSERVED",
    "EPN:SURP5A": "OBSERVED",
    "EPN:SURP5B": "OBSERVED",
    "EPN:LBUZ51": "OBSERVED",
    "EPN:LBUZ5A": "OBSERVED",
    "EPN:CHAU51": "DERIVED",
    "EPN:CHAU52": "DERIVED",
    "EPN:LEWS51": "DERIVED",
    "EPN:CHAP31": "DERIVED",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit() -> dict[str, Any]:
    run = lambda *a: subprocess.run(a, capture_output=True, text=True, cwd=REPO_ROOT).stdout.strip()  # noqa: E731
    return {
        "git_commit": run("git", "rev-parse", "HEAD"),
        "working_tree_dirty": bool(run("git", "status", "--porcelain")),
    }


def rel(p: Path) -> str:
    return str(Path(p).resolve().relative_to(REPO_ROOT))


# ------------------------------------------------------------------ licence + attribution
def attribution() -> dict[str, Any]:
    reg = Registry.load()
    decisions = []
    for sid in CFG["sources"]:
        d = gate.require(sid, "redistribute_derived", reg)  # raises if refused
        decisions.append(
            {
                "source_id": sid,
                "use": d.use,
                "allowed": d.allowed,
                "reason": str(d.reason.value if hasattr(d.reason, "value") else d.reason),
            }
        )
    sources = []
    for sid in CFG["sources"]:
        s = reg.sources[sid]
        sources.append(
            {
                "source_id": sid,
                "licence": s.licence,
                "licence_url": s.licence_url,
                "attribution": " ".join((s.attribution or "").split()),
                "modified": True,
            }
        )
    return {
        "sources": sources,
        "gate_decisions": decisions,
        "modified_notice": (
            "Cloud2Grid modified these data: satellite imagery re-encoded (WebP) and overlaid; "
            "irradiance sampled at asset locations; PV estimated with pvlib; network topology "
            "reconstructed from LTDS; loads scaled to operational data; power flows simulated."
        ),
        "attribution_text": gate.attribution_block(CFG["sources"], reg),
    }


# ------------------------------------------------------------------ models
def models() -> list[dict[str, Any]]:
    out = []
    for m in CFG["models"]:
        m = dict(m)
        if m.get("registry"):
            reg = yaml.safe_load((REPO_ROOT / m["registry"]).read_text())
            if not reg.get("frozen"):
                raise SystemExit(f"{m['registry']} is not frozen")
            sel = reg["selected"]
            ck = reg["checkpoints"][sel]
            m["selected_run"] = sel
            m["selection_flagged"] = bool(
                reg.get("selected_flagged") or reg.get("selected_without_gate_pass")
            )
            m["checkpoint_sha256"] = ck["checkpoint"]["sha256"]
            m["normalizer_sha256"] = ck["normalizer"]["sha256"]
            m["predictions"] = m.pop("predictions_template").format(selected=sel)
        else:  # zero-shot: the official transfer checkpoint, as recorded in the E5 registry
            ref = yaml.safe_load((REPO_ROOT / "metadata/e5_checkpoint_registry.yaml").read_text())
            z = ref["zero_shot_reference"]
            m["selected_run"] = f"{z['repo_id']}@{z['revision'][:10]}"
            m["checkpoint_ref"] = f"{z['repo_id']} {z['weights']} (rev {z['revision']})"
        out.append(m)
    return out


def load_predictions(m: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    p = REPO_ROOT / m["predictions"]
    return (
        pd.read_parquet(p / f"{NET}_predictions.parquet"),
        pd.read_parquet(p / f"{NET}_branch_predictions.parquet"),
    )


# ------------------------------------------------------------------ network
def network(ratings0: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """GENCO graph buses (0..36) ↔ named Sundon nodes, recovered from the element names stored
    with every branch rating, then checked against the E5b datakit_bus_index."""
    net = StateBuilder(REPO_ROOT / MC["network"]["interpretation"]).net
    nm = net.bus["name"]
    cand: dict[int, list[set[str]]] = {}
    pair_elems = []
    for r in ratings0.itertuples():
        kinds = set()
        for el in r.elements.split(";"):
            kind, name = el.split(":", 1)
            if kind == "line":
                row = net.line[net.line["name"] == name].iloc[0]
                ends = {nm[row.from_bus], nm[row.to_bus]}
            else:
                row = net.trafo.loc[int(name)]
                ends = {nm[row.hv_bus], nm[row.lv_bus]}
            kinds.add(kind)
            for b in (r.bus_a, r.bus_b):
                cand.setdefault(int(b), []).append(ends)
        pair_elems.append((int(r.bus_a), int(r.bus_b), "trafo" if kinds == {"trafo"} else "line"))
    node: dict[int, str] = {}
    for _ in range(5):  # resolve by intersection, then by elimination of already-assigned names
        for b, sets in cand.items():
            if b in node:
                continue
            taken = set(node.values())
            inter = set.intersection(*sets) - taken
            if len(inter) == 1:
                node[b] = inter.pop()
                continue
            counts = pd.Series([n for s in sets for n in s if n not in taken]).value_counts()
            if len(counts) and (len(counts) == 1 or counts.iloc[0] > counts.iloc[1]):
                node[b] = counts.index[0]
            elif len(sets) == 1 and len(sets[0] - taken) == 1:
                node[b] = (sets[0] - taken).pop()
    if len(node) != len(cand) or len(set(node.values())) != len(node):
        raise SystemExit(f"bus mapping incomplete or ambiguous: {node}")
    for k, i in ENV["datakit_bus_index"].items():
        if node[i] != k:
            raise SystemExit(f"bus {i}: derived {node[i]} != datakit_bus_index {k}")
    # nodes merged into a GENCO bus by closed bus-bus couplers (e.g. SUND11 + SUND12)
    members = {b: [n] for b, n in node.items()}
    inv = {n: b for b, n in node.items()}
    for s in net.switch[(net.switch.et == "b") & net.switch.closed].itertuples():
        a, c = nm[s.bus], nm[s.element]
        if a in inv and c not in inv:
            members[inv[a]].append(c)
        elif c in inv and a not in inv:
            members[inv[c]].append(a)
    bus = net.bus.set_index("name")
    first = next(iter(PRED.values()))[0]
    # grid supply point: the REF bus of almost every state (a few outage states differ; their
    # import is still read from their own REF bus, as in the published metrics)
    SLACK = int(first.loc[first.REF == 1, "bus"].mode().iloc[0])
    # manual electrical schematic (configs/app/network_layout.yaml), not geographic
    lay = LAYOUT["nodes"]
    missing = sorted(set(node.values()) - set(lay))
    extra = sorted(set(lay) - set(node.values()))
    if missing or extra:
        raise SystemExit(f"network_layout.yaml: missing {missing}, unknown {extra}")
    pos = {b: lay[k] for b, k in node.items()}
    rows = []
    for b in sorted(node):
        res = [n for n in members[b] if bus.at[n, "geolocation_status"] == "resolved"]
        rep = res[0] if res else node[b]
        role = (
            "pv_33kv"
            if node[b] in PV_NODES
            else "battery_33kv"
            if node[b] == BATT
            else "load_11kv"
            if node[b] in LOAD_NODES
            else str(bus.at[node[b], "role"])
        )
        rows.append(
            {
                "bus": b,
                "node_key": node[b],
                "members": ";".join(members[b]),
                "label": node[b].split(":")[1],
                "vn_kv": float(bus.at[node[b], "vn_kv"]),
                "lat": float(bus.at[rep, "geo_lat"]) if res else None,
                "lon": float(bus.at[rep, "geo_lon"]) if res else None,
                "geolocation_status": "resolved" if res else "unresolved",
                "schematic_x": float(pos[b][0]),
                "schematic_y": float(pos[b][1]),
                "role": role,
                "is_slack": bool(b == SLACK),
            }
        )
    nodes = pd.DataFrame(rows)
    region = yaml.safe_load((REPO_ROOT / "configs/networks/study_region.yaml").read_text())
    names = {r["node_key"]: r.get("substation_names") for r in region["nodes"]}
    nodes["substation"] = nodes.node_key.map(names)
    edges = pd.DataFrame(
        [
            {
                "branch_id": f"{a}-{b}",
                "bus_a": a,
                "bus_b": b,
                "from_node": node[a],
                "to_node": node[b],
                "kind": k,
                "elements": e,
                "rating_mva": float(rt),
            }
            for (a, b, k), e, rt in zip(
                pair_elems, ratings0.elements, ratings0.rating_mva, strict=True
            )
        ]
    )
    return nodes, edges


# ------------------------------------------------------------------ grid states
def grid_tables(
    mods: list[dict[str, Any]], ids: list[int], slots: pd.Series, ratings: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Long tables (slot, model, element) for AC and every model, plus per-slot summaries."""
    bus_rows, br_rows, summ = [], [], []
    ac_ref = None
    for m in mods:
        bus, br = PRED[m["id"]]
        bus = bus[bus.scenario.isin(ids)].copy()
        br = br[br.scenario.isin(ids)].copy()
        # AC reference must be identical across prediction sets (same states, same solution);
        # compared on Vm, Va and NET injection (E5c re-encodes PV as Pg instead of −Pd)
        ref = bus.assign(p_net=bus.Pg_target - bus.Pd).set_index(["scenario", "bus"])[
            ["Vm_target", "Va_target", "p_net"]
        ]
        if ac_ref is None:
            ac_ref = ref
        elif (ref - ac_ref).abs().max().max() > 1e-3:
            raise SystemExit(f"{m['id']}: AC reference differs from the first prediction set")
        sm = gm.scenario_metrics(bus, br, ratings).merge(
            ref_import(bus).reset_index(), on="scenario"
        )
        variants = [("AC", "target")] if not bus_rows else []
        variants.append((m["id"], "pred"))
        for lab, kind in variants:
            sfx = "_target" if kind == "target" else "_pred"
            b = pd.DataFrame(
                {
                    "scenario": bus.scenario,
                    "model": lab,
                    "bus": bus.bus,
                    "vm_pu": bus[f"Vm{sfx}"],
                    "va_deg": np.rad2deg(bus[f"Va{sfx}"]),
                    "p_inj_mw": bus[f"Pg{sfx}"] - bus["Pd"],
                    "q_inj_mvar": bus[f"Qg{sfx}"] - bus["Qd"],
                    "residual_p_mw": 0.0 if kind == "target" else bus["active res. (MW)"],
                }
            )
            bus_rows.append(b)
            pc, qc = ("Pft_target", "Qft_target") if kind == "target" else ("Pft", "Qft")
            d = br.groupby(["scenario", "from_bus", "to_bus"])[[pc, qc]].sum().reset_index()
            d["bus_a"] = d[["from_bus", "to_bus"]].min(axis=1)
            d["bus_b"] = d[["from_bus", "to_bus"]].max(axis=1)
            d["s"] = np.hypot(d[pc], d[qc])
            fwd = d[d.from_bus == d.bus_a].set_index(["scenario", "bus_a", "bus_b"])
            bwd = d[d.from_bus == d.bus_b].set_index(["scenario", "bus_a", "bus_b"])
            e = pd.DataFrame(
                {
                    "p_ab_mw": fwd[pc],
                    "q_ab_mvar": fwd[qc],
                    "p_ba_mw": bwd[pc].reindex(fwd.index),
                    "s_max_mva": np.fmax(fwd["s"], bwd["s"].reindex(fwd.index)),
                }
            ).reset_index()
            e = e.merge(
                ratings[["scenario", "bus_a", "bus_b", "rating_mva"]],
                on=["scenario", "bus_a", "bus_b"],
                how="left",
            )
            e["loading_pct"] = 100 * e.s_max_mva / e.rating_mva
            e["losses_mw"] = e.p_ab_mw + e.p_ba_mw
            e["model"] = lab
            e["branch_id"] = e.bus_a.astype(str) + "-" + e.bus_b.astype(str)
            br_rows.append(e.drop(columns="rating_mva"))
            s = pd.DataFrame(
                {
                    "scenario": sm.scenario,
                    "model": lab,
                    "import_mw": sm["ac_import_mw" if kind == "target" else "genco_import_mw"],
                    "max_loading_pct": sm[
                        "max_loading_ac" if kind == "target" else "max_loading_pred"
                    ],
                    "PBE_mean": 0.0 if kind == "target" else sm["PBE_mean"],
                    "P_residual": 0.0 if kind == "target" else sm["P_residual"],
                    "V_error": 0.0 if kind == "target" else sm["V_error"],
                    "angle_error": 0.0 if kind == "target" else sm["angle_error"],
                    "branch_P_error": 0.0 if kind == "target" else sm["branch_P_error"],
                    "max_loading_error": 0.0 if kind == "target" else sm["max_loading_error"],
                }
            )
            summ.append(s)
    B, R, S = (pd.concat(x, ignore_index=True) for x in (bus_rows, br_rows, summ))
    smap = dict(zip(ids, slots, strict=True))
    for t in (B, R, S):
        t.insert(0, "timestamp_utc", t.scenario.map(smap))
    return B, R, S


def errors(B: pd.DataFrame, R: pd.DataFrame) -> pd.DataFrame:
    ac_b = B[B.model == "AC"].set_index(["scenario", "bus"])
    ac_r = R[R.model == "AC"].set_index(["scenario", "branch_id"])
    out = []
    for m in B.model.unique():
        if m == "AC":
            continue
        b = B[B.model == m].set_index(["scenario", "bus"])
        r = R[R.model == m].set_index(["scenario", "branch_id"])
        eb = (
            pd.DataFrame(
                {
                    "timestamp_utc": b.timestamp_utc,
                    "model": m,
                    "element_type": "bus",
                    "dvm_pu": b.vm_pu - ac_b.vm_pu,
                    "dva_deg": b.va_deg - ac_b.va_deg,
                    "dp_mw": b.p_inj_mw - ac_b.p_inj_mw,
                    "residual_p_mw": b.residual_p_mw,
                }
            )
            .reset_index()
            .rename(columns={"bus": "element_id"})
        )
        er = (
            pd.DataFrame(
                {
                    "timestamp_utc": r.timestamp_utc,
                    "model": m,
                    "element_type": "branch",
                    "dp_mw": r.p_ab_mw - ac_r.p_ab_mw,
                    "dloading_pct": r.loading_pct - ac_r.loading_pct,
                }
            )
            .reset_index()
            .rename(columns={"branch_id": "element_id"})
        )
        eb["element_id"] = eb["element_id"].astype(str)
        out += [eb, er]
    e = pd.concat(out, ignore_index=True)
    e["scenario_family"] = "S1"
    return e


# ------------------------------------------------------------------ satellite + PV
def satellite(ev: dict[str, Any], dst: Path, t0: pd.Timestamp, t1: pd.Timestamp) -> pd.DataFrame:
    idx = pd.read_csv(REPO_ROOT / CFG["frames"]["index"])
    idx = idx[idx.event_id.isin(ev["source_events"]) & idx.accepted]
    idx["slot"] = pd.to_datetime(idx.radiation_slot, utc=True)
    idx = idx[(idx.slot >= t0) & (idx.slot <= t1)].sort_values("slot").drop_duplicates("slot")
    cb, cr = CFG["frames"]["context_bbox"], CFG["frames"]["crop_bbox"]
    (dst / "satellite").mkdir(parents=True, exist_ok=True)
    rows = []
    for k, r in enumerate(idx.itertuples()):
        src = REPO_ROOT / r.local_path
        if sha256(src) != r.sha256:
            raise SystemExit(f"frame hash mismatch: {src}")
        im = Image.open(src).convert("RGB")
        w, h = im.size
        box = (
            round((cr["lon_min"] - cb["lon_min"]) / (cb["lon_max"] - cb["lon_min"]) * w),
            round((cb["lat_max"] - cr["lat_max"]) / (cb["lat_max"] - cb["lat_min"]) * h),
            round((cr["lon_max"] - cb["lon_min"]) / (cb["lon_max"] - cb["lon_min"]) * w),
            round((cb["lat_max"] - cr["lat_min"]) / (cb["lat_max"] - cb["lat_min"]) * h),
        )
        name = f"satellite/frame_{k:03d}.webp"
        im.crop(box).save(dst / name, "WEBP", quality=CFG["frames"]["webp_quality"], method=6)
        rows.append(
            {
                "timestamp_utc": r.slot,
                "served_time_utc": pd.Timestamp(r.rgb_time),
                "radiation_slot_utc": r.slot,
                "time_delta_min": r.time_delta_min,
                "product": "EO:EUM:DAT:MSG:EVIEW",
                "image_file": name,
                "bbox_wgs84": [cr["lon_min"], cr["lat_min"], cr["lon_max"], cr["lat_max"]],
                "crs": "EPSG:4326 (plate carrée, as served by EUMETView WMS)",
                "source_event_id": r.event_id,
                "source_sha256": r.sha256,
            }
        )
    return pd.DataFrame(rows)


def pv_tables(t0: pd.Timestamp, t1: pd.Timestamp) -> dict[str, pd.DataFrame]:
    pa = pd.read_parquet(SAT / "pv_by_asset.parquet")
    pa = pa[(pa.slot >= t0) & (pa.slot <= t1)]
    irr = pa.rename(columns={"slot": "timestamp_utc", "acquisition_time": "acquisition_time_utc"})[
        [
            "timestamp_utc",
            "asset_id",
            "acquisition_time_utc",
            "ghi",
            "dhi",
            "dni",
            "ghi_clearsky",
            "clearsky_index",
            "quality_flag",
            "status",
            "pixel_id",
            "native_pixel_id",
        ]
    ].rename(
        columns={"ghi": "ghi_wm2", "dhi": "dhi_wm2", "dni": "dni_wm2", "status": "quality_status"}
    )
    pv = pa.rename(columns={"slot": "timestamp_utc"})[
        [
            "timestamp_utc",
            "asset_id",
            "active_capacity_mw",
            "capacity_factor",
            "estimated_pv_mw",
            "status",
        ]
    ].rename(
        columns={
            "active_capacity_mw": "capacity_mw",
            "estimated_pv_mw": "p_mw",
            "status": "quality_status",
        }
    )
    pb = pd.read_parquet(SAT / "pv_by_bus.parquet")
    pb = pb[(pb.timestamp >= t0) & (pb.timestamp <= t1)].rename(
        columns={"timestamp": "timestamp_utc", "bus_id": "node_key", "estimated_pv_mw": "p_mw"}
    )
    return {"irradiance": irr, "pv_generation": pv, "pv_by_bus": pb}


def assets() -> pd.DataFrame:
    from cloud2grid.solar import inventory

    pvm = yaml.safe_load((REPO_ROOT / "configs/experiments/e3_pv_model.yaml").read_text())
    a = inventory.load(pvm)
    a = a[a.status == "Connected"]
    return pd.DataFrame(
        {
            "asset_id": a.asset_id,
            "technology": a.technology,
            "capacity_mw": a.capacity_mw.astype(float),
            "connection_voltage_kv": a.connection_voltage_kv,
            "attributed_nodes": a.attributed_nodes.map(
                lambda v: ";".join(v) if isinstance(v, list | tuple | np.ndarray) else str(v)
            ),
            "lat": a.lat.astype(float),
            "lon": a.lon.astype(float),
        }
    ).reset_index(drop=True)


# ------------------------------------------------------------------ S1-wide PV response
def pv_response(mods: list[dict[str, Any]], gates: pd.DataFrame) -> pd.DataFrame:
    """Per S1 state: import (AC and each model) and its partial residual on PV injection, i.e.
    import minus the fitted intercept, load and CHAP31 terms of the published OLS
    (scripts/evaluate_e5b.py import_sensitivity). The slope through these points IS the
    published PV slope; nothing is re-fitted differently."""
    root = REPO_ROOT / CFG["grid_population"]["dataset"] / NET / "raw"
    b = pd.read_parquet(root / "bus_data.parquet", columns=["scenario", "bus", "Pd"])
    p = b.pivot(index="scenario", columns="bus", values="Pd")
    idx = ENV["datakit_bus_index"]
    f = pd.DataFrame(index=p.index)
    f["load_mw"] = p[[idx[n] for n in LOAD_NODES]].sum(axis=1)
    f["chap31_mw"] = p[idx[BATT]]
    f["pv_injection_mw"] = -p[[idx[n] for n in PV_NODES]].sum(axis=1)
    X = np.column_stack([np.ones(len(f)), f.load_mw, f.chap31_mw, f.pv_injection_mw])
    out = f.reset_index()
    out["timestamp_utc"] = out.scenario.map(gates.set_index("scenario").slot)
    ys = {"AC": ref_import(PRED[mods[0]["id"]][0]).ac_import_mw}
    ys.update({m["id"]: ref_import(PRED[m["id"]][0]).genco_import_mw for m in mods})
    for lab, y in ys.items():
        y = y.reindex(f.index).to_numpy()
        coef = np.linalg.lstsq(X, y, rcond=None)[0]
        out[f"import_{lab}"] = y
        out[f"partial_{lab}"] = y - X[:, :3] @ coef[:3]
        out.attrs[lab] = coef.tolist()
    return out


# ------------------------------------------------------------------ main
PRED: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}


def main() -> int:
    commit = git_commit()  # before anything under data/demo is rewritten
    att = attribution()
    mods = models()
    for m in mods:
        PRED[m["id"]] = load_predictions(m)
    gp = CFG["grid_population"]
    gates = pd.read_parquet(REPO_ROOT / gp["gates"])
    gates = gates[gates.rejected.isna()].copy()
    gates["scenario"] = gates.scenario.astype(int)
    gates["slot"] = pd.to_datetime(gates.slot, utc=True)
    ratings = pd.read_parquet(REPO_ROOT / gp["dataset"] / NET / "branch_ratings.parquet")
    nodes, edges = network(ratings[ratings.scenario == 0])
    ev_tab = pd.read_csv(REPO_ROOT / "reports/tables/e3_candidate_events.csv")
    ev_tab["start"] = pd.to_datetime(ev_tab.start, utc=True)
    ev_tab["end"] = pd.to_datetime(ev_tab.end, utc=True)

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "events").mkdir(parents=True)
    (OUT / ".gitkeep").touch()
    ast = assets()
    catalog = []
    for ev in CFG["events"]:
        unknown = set(ev["source_events"]) - set(HEROES)
        if unknown:
            raise SystemExit(f"{ev['bundle_id']}: {unknown} are not frozen hero events")
        e = ev_tab[ev_tab.event_id.isin(ev["source_events"])]
        t0, t1 = e.start.min(), e.end.max()
        g = gates[(gates.slot >= t0) & (gates.slot <= t1)].sort_values("slot")
        ids = g.scenario.tolist()
        dst = OUT / "events" / ev["bundle_id"]
        dst.mkdir(parents=True)
        frames = satellite(ev, dst, t0, t1)
        frames.to_parquet(dst / "satellite/frames.parquet", index=False)
        pv = pv_tables(t0, t1)
        for k, v in pv.items():
            v.to_parquet(dst / f"{k}.parquet", index=False)
        B, R, S = grid_tables(mods, ids, g.slot, ratings)
        fleet = pv["pv_generation"].groupby("timestamp_utc").p_mw.sum().rename("fleet_pv_mw")
        common = g.set_index("scenario")[
            ["slot", "fleet_pv_mw", "p_hv_injected_mw", "load_p_mw", "mean_kc", "lines_out"]
        ]
        S = S.merge(common.drop(columns="slot").reset_index(), on="scenario", how="left")
        lo = B[B.model == "AC"]
        loads = lo[lo.bus.isin(nodes[nodes.node_key.isin(list(LOAD_CLASS))].bus)].merge(
            nodes[["bus", "node_key"]], on="bus"
        )
        loads = pd.DataFrame(
            {
                "timestamp_utc": loads.timestamp_utc,
                "node_key": loads.node_key,
                "p_mw": -loads.p_inj_mw,
                "q_mvar": -loads.q_inj_mvar,
                "class": loads.node_key.map(LOAD_CLASS),
            }
        )
        loads.to_parquet(dst / "loads.parquet", index=False)
        B[B.model == "AC"].assign(element_type="bus").to_parquet(
            dst / "ac_reference.parquet", index=False
        )
        R[R.model == "AC"].assign(element_type="branch").to_parquet(
            dst / "ac_reference_branches.parquet", index=False
        )
        B[B.model != "AC"].assign(element_type="bus").to_parquet(dst / "genco.parquet", index=False)
        R[R.model != "AC"].assign(element_type="branch").to_parquet(
            dst / "genco_branches.parquet", index=False
        )
        errors(B, R).to_parquet(dst / "errors.parquet", index=False)
        S.to_parquet(dst / "summary.parquet", index=False)
        fleet.reset_index().to_parquet(dst / "fleet_pv.parquet", index=False)
        nodes.to_parquet(dst / "network_nodes.parquet", index=False)
        edges.to_parquet(dst / "network_edges.parquet", index=False)
        ast.to_parquet(dst / "assets.parquet", index=False)
        srcs = {
            rel(REPO_ROOT / m["predictions"] / f"{NET}_{t}.parquet"): sha256(
                REPO_ROOT / m["predictions"] / f"{NET}_{t}.parquet"
            )
            for m in mods
            for t in ("predictions", "branch_predictions")
        }
        for f in ("pv_by_asset.parquet", "pv_by_bus.parquet"):
            srcs[rel(SAT / f)] = sha256(SAT / f)
        srcs[gp["gates"]] = sha256(REPO_ROOT / gp["gates"])
        meta = {
            "schema_version": CFG["bundle_schema_version"],
            "event_id": ev["bundle_id"],
            "title": ev["title"],
            "story": " ".join(ev["story"].split()),
            "source_events": ev["source_events"],
            "event_class": sorted(e.event_class.unique().tolist()),
            "class_name": sorted(e.class_name.unique().tolist()),
            "selection_criteria": (
                "frozen E3 meteorological ranking (configs/experiments/e3_event_discovery.yaml); "
                "frozen E4 hero list — never selected on GENCO behaviour"
            ),
            "time_start_utc": t0.isoformat(),
            "time_end_utc": t1.isoformat(),
            "satellite_step_minutes": 15,
            "grid_step_minutes": 30,
            "grid_slots_utc": [s.isoformat() for s in g.slot],
            "grid_population": gp["family"],
            "grid_scenarios": ids,
            "network_config": MC["network"]["interpretation"],
            "network_variant": Path(MC["network"]["interpretation"]).stem,
            "active_pv_capacity_mw": float(e.fleet_capacity_mw.max()),
            "event_metrics": e[
                [
                    "event_id",
                    "mean_kc",
                    "std_kc_time",
                    "max_abs_ramp",
                    "field_frac_cloudy_start",
                    "field_frac_cloudy_end",
                ]
            ].to_dict("records"),
            "models": [m["id"] for m in mods],
            "provenance": {
                "satellite_frame": "OBSERVED (EUMETSAT E-View RGB imagery)",
                "irradiance": "DERIVED (LSA SAF MDSSFTD retrieval sampled at assets)",
                "pv": "DERIVED (satellite-driven ESTIMATED PV, never measured)",
                "loads": "OBSERVED or DERIVED per node (UKPN operational data)",
                "ac_reference": "SIMULATED (AC power flow on the reconstructed network)",
                "genco": "PREDICTED (frozen GENCO checkpoints)",
                "errors": "DERIVED (GENCO − AC)",
            },
            **commit,
            "source_hashes": srcs,
        }
        (dst / "metadata.json").write_text(json.dumps(meta, indent=2, default=str))
        (dst / "attribution.json").write_text(json.dumps(att, indent=2))
        catalog.append(
            {
                k: meta[k]
                for k in (
                    "event_id",
                    "title",
                    "story",
                    "source_events",
                    "class_name",
                    "time_start_utc",
                    "time_end_utc",
                )
            }
            | {"n_frames": len(frames), "n_grid_slots": len(ids)}
        )
        print(f"{ev['bundle_id']}: {len(frames)} frames, {len(ids)} grid states")

    # ---- global tables
    pt = CFG["published_tables"]
    tables = [pt[k] for k in ("real_transfer", "import_diagnostic", "pv_response") if k in pt]
    lab = {"zero-shot (E4)": "zero_shot", "zero-shot": "zero_shot"}
    evo = None
    for t in tables:
        d = pd.read_csv(REPO_ROOT / t)
        d["model"] = d.model.map(lambda m: lab.get(m, m))
        evo = (
            d
            if evo is None
            else evo.merge(
                d.drop(columns=[c for c in d if c in evo and c != "model"]), on="model", how="left"
            )
        )
    missing = {m["id"] for m in mods} - set(evo.model)
    if missing:
        raise SystemExit(f"published tables lack {missing}")
    evo.to_csv(OUT / "model_evolution.csv", index=False)
    resp = pv_response(mods, gates)
    resp.to_parquet(OUT / "pv_response_s1.parquet", index=False)
    coefs = {
        k: dict(zip(["intercept", "load", "chap31", "pv"], v, strict=True))
        for k, v in resp.attrs.items()
    }
    for m in mods:  # the partial-residual slopes must equal the published PV slopes
        pub = float(evo.set_index("model").at[m["id"], "genco_slope_pv"])
        if abs(coefs[m["id"]]["pv"] - pub) > 1e-6:
            raise SystemExit(f"{m['id']}: PV slope {coefs[m['id']]['pv']} != published {pub}")
    nodes.to_parquet(OUT / "network_nodes.parquet", index=False)
    story = yaml.safe_load((REPO_ROOT / "configs/app/story_jun15.yaml").read_text())
    if story["event"] not in {e["bundle_id"] for e in CFG["events"]}:
        raise SystemExit(f"story event {story['event']} is not a demo bundle")
    (OUT / "story_jun15.json").write_text(json.dumps(story, indent=2))
    (OUT / "network_layout.json").write_text(
        json.dumps({k: LAYOUT.get(k, {}) for k in ("bands", "groups", "busbars")}, indent=2)
    )
    edges.to_parquet(OUT / "network_edges.parquet", index=False)
    (OUT / "attribution.json").write_text(json.dumps(att, indent=2))
    (OUT / "models.json").write_text(json.dumps(mods, indent=2))
    (OUT / "catalog.json").write_text(
        json.dumps(
            {
                "schema_version": CFG["bundle_schema_version"],
                "events": catalog,
                "models": [m["id"] for m in mods],
                "ols_coefficients_s1": coefs,
                "published_tables": {v: sha256(REPO_ROOT / v) for v in tables},
                **commit,
            },
            indent=2,
        )
    )
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"wrote {OUT} ({size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
