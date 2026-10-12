"""E5 evaluation — synthetic learning curve + gate + selection, freeze, then E4 repeated exactly.

    uv run python scripts/evaluate_e5.py synthetic     # held-out synthetic test; gate; selection
    uv run python scripts/evaluate_e5.py freeze        # writes metadata/e5_checkpoint_registry.yaml
    uv run --env-file .env python scripts/evaluate_e5.py weather   # only after freeze

`synthetic` reads only the synthetic pools (data/interim/e5/synthetic) and GENCO predictions on
them; it applies the pre-registered gate and selection (configs/experiments/
e5_topology_adaptation.yaml) and never opens a weather family. `weather` refuses to run unless
the registry is frozen, then re-scores the E4 populations (same AC datasets, gates, donors,
bootstrap, metrics, ramp bins, events) with the frozen checkpoint AND its normalizer, beside the
E4 zero-shot predictions.

Outputs (synthetic)
    reports/tables/e5_learning_curve.csv, e5_seed_results.csv, e5_synthetic_summary.csv,
    e5_import_diagnostic.csv (synthetic rows); reports/figures/e5_learning_curve.png;
    reports/experiments/e5/synthetic_evaluation.json
Outputs (weather) — see `cmd_weather`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from cloud2grid.evaluation import genco_metrics as gm  # noqa: E402
from cloud2grid.evaluation import statistics as st  # noqa: E402
from cloud2grid.evaluation import transitions as tr  # noqa: E402
from cloud2grid.genco import adaptation as ad  # noqa: E402
from cloud2grid.genco import runner  # noqa: E402
from cloud2grid.licensing.registry import REPO_ROOT  # noqa: E402

CFG = ad.CFG
ZS = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_zero_shot.yaml").read_text())
MC = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_matched_control.yaml").read_text())
RS = yaml.safe_load(
    (REPO_ROOT / "configs/experiments/e5_representation_sensitivity.yaml").read_text()
)
BOOT = ZS["statistics"]["bootstrap"]
E4W = REPO_ROOT / "data/interim/e4"
E4FAM = REPO_ROOT / "reports/experiments/e4/families"
OUT = REPO_ROOT / "reports/experiments/e5"
TABLES = REPO_ROOT / "reports/tables"
FIGS = REPO_ROOT / "reports/figures"
REGISTRY = REPO_ROOT / "metadata/e5_checkpoint_registry.yaml"
NET = ad.NETWORK
CORE = [
    "PBE_mean",
    "PBE_max",
    "P_residual",
    "Q_residual",
    "V_error",
    "angle_error",
    "branch_P_error",
    "branch_Q_error",
    "dc_P_residual",
]
S2_SEEDS = MC["families"]["S2_MATCHED_PV_CONTROL"]["seeds"]


# ------------------------------------------------------------------ shared scoring
def pred_dir(run: str, target: str) -> Path:
    """E4 zero-shot predictions on E4 families are reused from E4 (identical files)."""
    if (
        run == "zero_shot"
        and not target.startswith("synthetic")
        and "MERGED" not in target
        and "__norm_" not in target
    ):
        return E4W / "predictions" / target
    return ad.WORK / "predictions" / run / target


def base_ratings(ids: list[int] | np.ndarray) -> pd.DataFrame:
    """Intact-network LTDS ratings by bus pair (E4: S0 reuses the S1 export's), per scenario."""
    r = pd.read_parquet(E4W / "datasets/S1_WEATHER_ALIGNED" / NET / "branch_ratings.parquet")
    base = r[r["scenario"] == 0].drop(columns="scenario")
    return base.merge(pd.DataFrame({"scenario": np.asarray(ids, dtype=int)}), how="cross")


def read_raw(root: Path, ids: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = root / NET / "raw"
    f = [("scenario", "in", [int(i) for i in ids])]
    bus = pd.read_parquet(raw / "bus_data.parquet", filters=f)
    br = pd.read_parquet(raw / "branch_data.parquet", filters=f)
    return bus.drop(columns="scenario_partition", errors="ignore"), br.drop(
        columns="scenario_partition", errors="ignore"
    )


def score(
    run: str, target: str, dc: pd.DataFrame, ratings: pd.DataFrame | None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = pred_dir(run, target)
    bus = pd.read_parquet(d / f"{NET}_predictions.parquet")
    branch = pd.read_parquet(d / f"{NET}_branch_predictions.parquet")
    m = gm.scenario_metrics(bus, branch, ratings)
    m = m.merge(dc.reset_index(), on="scenario", how="left")
    m = m.merge(ad.ref_import(bus).reset_index(), on="scenario", how="left")
    return m, bus


def summarise(m: pd.DataFrame, bus: pd.DataFrame | None, block: str = "block") -> dict[str, Any]:
    row: dict[str, Any] = {"n": int(len(m)), "blocks": int(m[block].nunique())}
    for c in CORE:
        if c not in m or not m[c].notna().any():
            continue
        if c == "PBE_max":
            row[c] = float(m[c].max())
            continue
        ci = st.block_mean_ci(m[c], m[block], BOOT["resamples"], BOOT["seed"])
        row[c] = ci["mean"]
        row[f"{c}_ci"] = [round(ci["ci_low"], 6), round(ci["ci_high"], 6)]
    row["genco_vs_dc_active_ratio"] = row["P_residual"] / row["dc_P_residual"]
    row.update(ad.import_diagnostic(m.set_index("scenario")[["ac_import_mw", "genco_import_mw"]]))
    if bus is not None:
        row["vm_tracking_median_r"] = ad.voltage_tracking(bus)
    return row


# ------------------------------------------------------------------ synthetic
def synthetic_runs() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((OUT / "runs").glob("*.json"))]


def cmd_synthetic() -> dict:
    man = ad.assert_synthetic_dataset(ad.ALLOWED_ROOT)
    test = ad.pool_ids(man, "test").tolist()
    val = ad.pool_ids(man, "val").tolist()
    blocks = man.set_index("scenario")["load_block"]
    frames = {}
    for name, ids in (("synthetic_test", test), ("synthetic_val", val)):
        b, br = read_raw(ad.ALLOWED_ROOT, ids)
        frames[name] = gm.dc_baseline_frames(b, br)
    rat = {"synthetic_test": base_ratings(test), "synthetic_val": base_ratings(val)}

    rows, per_scenario = [], []
    runs = [
        {
            "run": "zero_shot",
            "n_train": 0,
            "seed": None,
            "init": "pretrained",
            "representation": "SUNDON_ORIGINAL",
        }
    ] + synthetic_runs()
    runs = [r for r in runs if r.get("representation", "SUNDON_ORIGINAL") == "SUNDON_ORIGINAL"]
    for r in runs:
        rec: dict[str, Any] = {k: r.get(k) for k in ("run", "n_train", "seed", "init")}
        if not (pred_dir(r["run"], "synthetic_test") / f"{NET}_predictions.parquet").exists():
            continue
        m, bus = score(r["run"], "synthetic_test", frames["synthetic_test"], rat["synthetic_test"])
        m["block"] = blocks.reindex(m["scenario"]).to_numpy()
        rec.update(summarise(m, bus))
        mv, _ = (
            score(r["run"], "synthetic_val", frames["synthetic_val"], None)
            if (pred_dir(r["run"], "synthetic_val") / f"{NET}_predictions.parquet").exists()
            else (None, None)
        )
        rec["val_pool_PBE_mean"] = float(mv["PBE_mean"].mean()) if mv is not None else np.nan
        rec["val_pool_P_residual"] = float(mv["P_residual"].mean()) if mv is not None else np.nan
        for k in ("wall_s", "best_epoch", "epochs_run", "best_validation_loss"):
            rec[k] = r.get(k)
        rec["gpu"] = (r.get("environment") or {}).get("gpu")
        rec["normalizer_baseMVA"] = (r.get("normalizer") or {}).get(
            "baseMVA", 116.00 if r["run"] == "zero_shot" else None
        )
        rec["normalizer_sha256"] = (r.get("normalizer") or {}).get("sha256")
        rec["checkpoint_sha256"] = (r.get("checkpoint") or {}).get("sha256")
        pj = OUT / "predict" / f"{r['run']}__synthetic_test.json"
        if pj.exists():
            rec["inference_s_per_scenario"] = json.loads(pj.read_text())["seconds_per_scenario"]
        rows.append(rec)
        per_scenario.append(
            m.assign(run=r["run"], n_train=r["n_train"], seed=r["seed"], init=r["init"])
        )
    S = pd.DataFrame(rows)
    zs = S[S.run == "zero_shot"].iloc[0].to_dict()
    gates = []
    for rec in rows:
        g = ad.gate(rec, zs) if rec["run"] != "zero_shot" else {"pass": False}
        rec.update({f"gate_{k}": v for k, v in g.items()})
        rec.update(ad.explicit_checks(rec))
        gates.append(g)
    S = pd.DataFrame(rows)
    S.to_csv(TABLES / "e5_seed_results.csv", index=False)
    pd.concat(per_scenario, ignore_index=True).to_parquet(
        OUT / "synthetic_scenario_metrics.parquet", index=False
    )

    # learning curve: mean over seeds + spread, per init and N (0 = zero-shot)
    metrics = [
        "PBE_mean",
        "PBE_max",
        "P_residual",
        "Q_residual",
        "V_error",
        "angle_error",
        "branch_P_error",
        "branch_Q_error",
        "import_mae_mw",
        "import_sign_accuracy",
        "import_corr",
        "import_dynamic_range",
        "vm_tracking_median_r",
        "wall_s",
    ]
    lc = []
    for (init, n), g in S.groupby(["init", "n_train"]):
        row: dict[str, Any] = {"init": init, "n_train": int(n), "seeds": int(len(g))}
        for c in metrics:
            if c in g and g[c].notna().any():
                row[c] = float(g[c].mean())
                row[f"{c}_min"] = float(g[c].min())
                row[f"{c}_max"] = float(g[c].max())
                row[f"{c}_std"] = float(g[c].std(ddof=1)) if len(g) > 1 else 0.0
        row["dc_P_residual"] = float(g["dc_P_residual"].mean())
        row["all_seeds_pass_gate"] = bool(g["gate_pass"].all()) if n else False
        row["any_seed_passes_gate"] = bool(g["gate_pass"].any()) if n else False
        lc.append(row)
    LC = pd.DataFrame(lc).sort_values(["init", "n_train"])
    LC.to_csv(TABLES / "e5_learning_curve.csv", index=False)
    summary_cols = [
        "run",
        "init",
        "n_train",
        "seed",
        *[c for c in CORE if c in S],
        "genco_vs_dc_active_ratio",
        "import_sign_accuracy",
        "import_mae_mw",
        "import_corr",
        "import_dynamic_range",
        "vm_tracking_median_r",
        "gate_pass",
        "gate_dc_parity",
        "val_pool_PBE_mean",
    ]
    S[[c for c in summary_cols if c in S]].to_csv(TABLES / "e5_synthetic_summary.csv", index=False)
    S[
        [
            "run",
            "init",
            "n_train",
            "seed",
            "import_sign_accuracy",
            "import_mae_mw",
            "import_corr",
            "import_dynamic_range",
            "ac_import_mean_mw",
            "genco_import_mean_mw",
        ]
    ].assign(population="held-out synthetic test").to_csv(
        TABLES / "e5_import_diagnostic.csv", index=False
    )

    ft = LC[LC.init == "pretrained"].set_index("n_train")
    pass_sizes = [int(n) for n in ft.index if n and ft.at[n, "all_seeds_pass_gate"]]
    sat = None
    if 1000 in ft.index and 10000 in ft.index:
        imp = {c: float(1 - ft.at[10000, c] / ft.at[1000, c]) for c in ("PBE_mean", "P_residual")}
        sat = {"improvement_1k_to_10k": imp, "saturated": all(v < 0.05 for v in imp.values())}
    cand = S[(S.init == "pretrained") & (S.run != "zero_shot") & S.gate_pass.astype(bool)]
    selected = None
    if len(cand):
        best = cand.val_pool_PBE_mean.min()
        tie = cand[cand.val_pool_PBE_mean <= best * 1.01].sort_values(
            ["n_train", "val_pool_PBE_mean"]
        )
        selected = tie.iloc[0]["run"]
    res = {
        "zero_shot_reference_on_test": {
            k: zs[k] for k in ("PBE_mean", "P_residual", "dc_P_residual")
        },
        "gate": CFG["adaptation_gate"],
        "runs_passing_gate": S.loc[S.gate_pass.astype(bool), "run"].tolist(),
        "first_size_all_seeds_pass": min(pass_sizes) if pass_sizes else None,
        "saturation_rule": sat,
        "selection_rule": CFG["checkpoint_selection"]["criterion"],
        "selected": selected,
        "outcome_if_none": None if selected else "E5-C_TOPOLOGY_ADAPTATION_INSUFFICIENT",
        "test_pool": {"n": len(test), "sha256": ad.sha256_ids(test)},
        "val_pool": {"n": len(val), "sha256": ad.sha256_ids(val)},
        **runner.git_commit(),
    }
    (OUT / "synthetic_evaluation.json").write_text(json.dumps(res, indent=2, default=str))
    learning_curve_figure(LC, zs)
    cols = [
        "run",
        "PBE_mean",
        "P_residual",
        "dc_P_residual",
        "import_sign_accuracy",
        "import_dynamic_range",
        "vm_tracking_median_r",
        "gate_pass",
        "val_pool_PBE_mean",
    ]
    print(S[[c for c in cols if c in S]].to_string())
    print(
        json.dumps(
            {
                k: res[k]
                for k in (
                    "runs_passing_gate",
                    "first_size_all_seeds_pass",
                    "saturation_rule",
                    "selected",
                )
            },
            indent=1,
            default=str,
        )
    )
    return res


def learning_curve_figure(LC: pd.DataFrame, zs: dict) -> None:
    fig, axes = plt.subplots(1, 4, figsize=(16, 3.8))
    x0 = 30  # where N = 0 (zero-shot) is drawn on the log axis
    for ax, (c, unit) in zip(
        axes,
        [("PBE_mean", "MVA"), ("P_residual", "MW"), ("branch_P_error", "MW"), ("V_error", "pu")],
        strict=True,
    ):
        for init, style in (("pretrained", "o-"), ("scratch", "s--")):
            g = LC[(LC.init == init) & (LC.n_train > 0)]
            if g.empty or c not in g:
                continue
            ax.errorbar(
                g.n_train,
                g[c],
                yerr=[g[c] - g[f"{c}_min"], g[f"{c}_max"] - g[c]],
                fmt=style,
                capsize=3,
                label="fine-tuned (pretrained)" if init == "pretrained" else "from scratch",
            )
        ax.plot([x0], [zs[c]], "kx", ms=9, label="zero-shot (E4 model)")
        if c == "P_residual":
            ax.axhline(zs["dc_P_residual"], color="grey", ls=":", label="DC-PF (same states)")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("Sundon synthetic training states (zero-shot at left)")
        ax.set_title(f"{c} ({unit})", fontsize=9)
        ax.legend(fontsize=6)
    fig.suptitle(
        "GENCO topology-only adaptation on Sundon: held-out synthetic test "
        "(mean over seeds; bars = seed range)",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(FIGS / "e5_learning_curve.png", dpi=120)
    plt.close(fig)


# ------------------------------------------------------------------ freeze
def cmd_freeze() -> None:
    res = json.loads((OUT / "synthetic_evaluation.json").read_text())
    sel = res["selected"]
    if not sel:
        raise SystemExit("no checkpoint passed the gate: E5-C — weather is NOT evaluated")
    rec = json.loads((OUT / "runs" / f"{sel}.json").read_text())
    S = pd.read_csv(TABLES / "e5_seed_results.csv").set_index("run")
    reg = {
        "schema": "cloud2grid E5 checkpoint registry v1",
        "frozen": True,
        "frozen_before_weather_evaluation": True,
        "selection_basis": "synthetic only: gate on held-out synthetic test, then "
        + CFG["checkpoint_selection"]["criterion"],
        "selected": sel,
        "evaluable_on_weather": [sel],
        "zero_shot_reference": {**ZS["model"], "normalizer": "E4 fixed S0 base (116.0 MVA)"},
        "checkpoints": {
            sel: {
                "n_train": rec["n_train"],
                "seed": rec["seed"],
                "init": rec["init"],
                "representation": rec["representation"],
                "checkpoint": rec["checkpoint"],
                "normalizer": rec["normalizer"],
                "normalizer_fitted_on": rec["normalizer_fitted_on"],
                "training_split_sha256": rec["split_sha256"],
                "best_epoch": rec["best_epoch"],
                "epochs_run": rec["epochs_run"],
                "best_validation_loss": rec["best_validation_loss"],
                "val_pool_PBE_mean": float(S.at[sel, "val_pool_PBE_mean"]),
                "held_out_synthetic_test": {
                    k: float(S.at[sel, k]) for k in ("PBE_mean", "P_residual", "dc_P_residual")
                },
                "init_checkpoint": rec["init_checkpoint"],
                "graphkit_config": rec["graphkit_config"],
                "mlflow_run": rec["mlflow_run"],
            }
        },
        "all_runs": {
            r: {
                "checkpoint_sha256": S.at[r, "checkpoint_sha256"],
                "normalizer_sha256": S.at[r, "normalizer_sha256"],
                "gate_pass": bool(S.at[r, "gate_pass"]),
            }
            for r in S.index
            if r != "zero_shot"
        },
        **runner.git_commit(),
    }
    REGISTRY.write_text(yaml.safe_dump(reg, sort_keys=False, allow_unicode=True))
    print(yaml.safe_dump(reg["checkpoints"], sort_keys=False))


# ------------------------------------------------------------------ weather (after freeze)
def frozen_selection() -> tuple[str, dict]:
    if not REGISTRY.exists():
        raise SystemExit("registry missing: weather families stay hidden")
    reg = yaml.safe_load(REGISTRY.read_text())
    if not reg.get("frozen"):
        raise SystemExit("registry not frozen: weather families stay hidden")
    sel = reg["selected"]
    c = reg["checkpoints"][sel]
    for k in ("checkpoint", "normalizer"):
        if ad.sha256_file(REPO_ROOT / c[k]["path"]) != c[k]["sha256"]:
            raise SystemExit(f"{sel}: {k} changed after freezing")
    return sel, reg


_DC_CACHE: dict[str, pd.DataFrame] = {}


def family_frame(
    fam: str,
    run: str,
    dataset_base: Path = E4W / "datasets",
    ratings_from: str | None = None,
    tag: str = "",
    gates_path: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """E4 family_metrics generalised: same AC dataset, gates, ratings and DC baseline; GENCO
    predictions from `run` (E4 files for zero_shot)."""
    gates = pd.read_parquet(gates_path or E4FAM / f"{fam}_gates.parquet")
    d = pred_dir(run, fam + tag)
    bus = pd.read_parquet(d / f"{NET}_predictions.parquet")
    branch = pd.read_parquet(d / f"{NET}_branch_predictions.parquet")
    rpath = dataset_base / (ratings_from or fam) / NET / "branch_ratings.parquet"
    ratings = pd.read_parquet(rpath) if rpath.exists() else None
    if ratings_from is not None and ratings is not None:
        base = ratings[ratings["scenario"] == 0].drop(columns="scenario")
        ratings = base.merge(pd.DataFrame({"scenario": bus["scenario"].unique()}), how="cross")
    key = str(dataset_base / fam)
    if key not in _DC_CACHE:
        _DC_CACHE[key] = gm.dc_baseline(dataset_base / fam / NET / "raw")
    m = gm.scenario_metrics(bus, branch, ratings)
    m = m.merge(_DC_CACHE[key].reset_index(), on="scenario", how="left")
    m = m.merge(ad.ref_import(bus).reset_index(), on="scenario", how="left")
    acc = gates[gates["rejected"].isna()].copy()
    acc["scenario"] = acc["scenario"].astype(int)
    m = m.merge(acc, on="scenario", how="left")
    base_fam = fam.split("_s1")[0] if fam.startswith("S2_") else fam
    m["scenario_family"] = base_fam
    m["scenario_id"] = fam + ":" + m["scenario"].astype(str)
    m["block"] = (
        pd.to_datetime(m["slot"], utc=True).dt.strftime("%Y-%m-%d")
        if "slot" in m
        else m["load_block"]
    )
    return m, bus, branch


def runtime_of(run: str, fam: str) -> float:
    if run == "zero_shot":
        return json.loads((REPO_ROOT / "reports/experiments/e4/runs" / f"{fam}.json").read_text())[
            "seconds_per_scenario"
        ]
    return json.loads((OUT / "predict" / f"{run}__{fam}.json").read_text())["seconds_per_scenario"]


def ramp_table(trans: dict[str, pd.DataFrame], T: dict[str, pd.DataFrame]) -> pd.DataFrame:
    fb = CFG["repeat_e4"]["ramp_bins_frozen"]
    edges = [-np.inf, *fb["edges"][1:-1], np.inf]
    rows = []
    prim = {k: v[v["within_halfhour"]].copy() for k, v in trans.items()}
    for k, p in prim.items():
        p["ramp_bin"] = pd.cut(
            p["abs_dPV_injected_mw"], bins=edges, labels=fb["labels"], include_lowest=True
        )
        pe = T[k].set_index("scenario")
        p["PBE_mean_j"] = pe.loc[p["scenario_j"], "PBE_mean"].to_numpy()
        prim[k] = p
    for lab in fb["labels"]:
        a = prim["zero_shot"][prim["zero_shot"]["ramp_bin"].astype(str) == lab]
        b = prim["adapted"][prim["adapted"]["ramp_bin"].astype(str) == lab]
        assert a[["scenario_i", "scenario_j"]].equals(b[["scenario_i", "scenario_j"]])
        r: dict[str, Any] = {
            "ramp_bin": lab,
            "n": len(b),
            "abs_dPV_range_mw": f"{b.abs_dPV_injected_mw.min():.3f}–"
            f"{b.abs_dPV_injected_mw.max():.3f}",
        }
        for c in ("dP_ac_mean_abs", "dVm_ac_mean_abs", "dVa_ac_mean_abs"):
            r[c] = float(b[c].mean())
        for tagk, g in (("zero_shot", a), ("adapted", b)):
            for c in ("dP_err_mean_abs", "dVm_err_mean_abs", "dVa_err_mean_abs", "dQ_err_mean_abs"):
                ci = st.block_mean_ci(g[c], g["block"], BOOT["resamples"], BOOT["seed"])
                r[f"{tagk}_{c}"] = ci["mean"]
                r[f"{tagk}_{c}_ci"] = [round(ci["ci_low"], 6), round(ci["ci_high"], 6)]
            r[f"{tagk}_tracking_ratio_median"] = float(g["dP_tracking_ratio"].median())
            r[f"{tagk}_end_state_PBE_mean"] = float(g["PBE_mean_j"].mean())
        rows.append(r)
    return pd.DataFrame(rows)


def event_windows() -> pd.DataFrame:
    ev = pd.read_csv(TABLES / "e3_candidate_events.csv")
    ev["start"] = pd.to_datetime(ev["start"], utc=True)
    ev["end"] = pd.to_datetime(ev["end"], utc=True)
    return ev


def in_window(slots: pd.Series, e: Any) -> pd.Series:
    s = pd.to_datetime(slots, utc=True)
    return (s >= e.start) & (s <= e.end)


def hero_outputs(ev: pd.DataFrame, T: dict, tb: dict, tbr: dict) -> dict[str, str]:
    hero_dir = OUT / "hero"
    hero_dir.mkdir(parents=True, exist_ok=True)
    not_eval = {}
    for eid in CFG["repeat_e4"]["heroes"]:
        e = ev[ev.event_id == eid].iloc[0]
        frames = {}
        for k in ("zero_shot", "adapted"):
            s = T[k][in_window(T[k]["slot"], e)].sort_values("slot")
            frames[k] = s
        if frames["adapted"].empty:
            not_eval[eid] = "no complete E2 base state in the event window"
            continue
        z, a = frames["zero_shot"].set_index("scenario"), frames["adapted"].set_index("scenario")
        ids = a.index.to_numpy()
        # E4 hero schema (zero-shot values, identical meaning to reports/experiments/e4/hero)
        out = pd.DataFrame(
            {
                "slot": a["slot"],
                "fleet_pv_mw": a["fleet_pv_mw"],
                "p_hv_injected_mw": a["p_hv_injected_mw"],
                "fleet_cf": a["fleet_cf"],
                "mean_kc": a["mean_kc"],
                "ac_import_mw": a["ac_import_mw"],
                "genco_import_mw": z.loc[ids, "genco_import_mw"],
                "PBE_mean": z.loc[ids, "PBE_mean"],
                "V_error": z.loc[ids, "V_error"],
                "angle_error": z.loc[ids, "angle_error"],
                "branch_P_error": z.loc[ids, "branch_P_error"],
                "max_loading_ac": a["max_loading_ac"],
                "max_loading_error": z.loc[ids, "max_loading_error"],
                "dc_P_residual": a["dc_P_residual"],
            }
        )
        for c in (
            "genco_import_mw",
            "PBE_mean",
            "V_error",
            "angle_error",
            "branch_P_error",
            "max_loading_error",
        ):
            out[f"adapted_{c}"] = a[c]
        # selected elements, chosen from the AC response ONLY (largest AC range in the window)
        bra = tbr["adapted"][tbr["adapted"].scenario.isin(ids)]
        brz = tbr["zero_shot"][tbr["zero_shot"].scenario.isin(ids)]
        rng = bra.groupby(["from_bus", "to_bus"])["Pft_target"].agg(lambda x: x.max() - x.min())
        for f, t in rng.sort_values(ascending=False).index[:2]:
            for lab, src, col in (
                ("ac", bra, "Pft_target"),
                ("zero_shot", brz, "Pft"),
                ("adapted", bra, "Pft"),
            ):
                v = src[(src.from_bus == f) & (src.to_bus == t)].groupby("scenario")[col].sum()
                out[f"branch_{f}_{t}_P_{lab}_mw"] = v.reindex(ids).to_numpy()
        ba = tb["adapted"][tb["adapted"].scenario.isin(ids) & (tb["adapted"].REF == 0)]
        bz = tb["zero_shot"][tb["zero_shot"].scenario.isin(ids)]
        vb = ba.groupby("bus")["Vm_target"].agg(lambda x: x.max() - x.min()).idxmax()
        for lab, src, cm, ca in (
            ("ac", ba, "Vm_target", "Va_target"),
            ("zero_shot", bz, "Vm_pred", "Va_pred"),
            ("adapted", ba, "Vm_pred", "Va_pred"),
        ):
            g = src[src.bus == vb].set_index("scenario")
            out[f"bus_{vb}_Vm_{lab}_pu"] = g[cm].reindex(ids).to_numpy()
            out[f"bus_{vb}_Va_{lab}_deg"] = np.rad2deg(g[ca].reindex(ids).to_numpy())
        out.to_csv(hero_dir / f"{eid}.csv", index=False)
        hero_figure(eid, e, out, vb)
    return not_eval


def hero_figure(eid: str, e: Any, s: pd.DataFrame, vb: int) -> None:
    fig, ax = plt.subplots(5, 1, figsize=(8.5, 11), sharex=True)
    t = pd.to_datetime(s["slot"], utc=True)
    ax[0].plot(t, s["fleet_pv_mw"], "o-", label="fleet PV (satellite-driven estimate)")
    ax[0].plot(t, s["p_hv_injected_mw"], "s--", label="injected at 33 kV (model)")
    ax[0].set_ylabel("MW")
    ax[1].plot(t, s["ac_import_mw"], "ko-", label="AC reference")
    ax[1].plot(t, s["genco_import_mw"], "x--", color="tab:red", label="GENCO zero-shot (E4)")
    ax[1].plot(t, s["adapted_genco_import_mw"], "^-", color="tab:green", label="GENCO adapted (E5)")
    ax[1].set_ylabel("grid import (MW)")
    bcols = [c for c in s if c.startswith("branch_") and c.endswith("_P_ac_mw")]
    if bcols:
        b = bcols[0].replace("_P_ac_mw", "")
        ax[2].plot(t, s[f"{b}_P_ac_mw"], "ko-", label="AC")
        ax[2].plot(t, s[f"{b}_P_zero_shot_mw"], "x--", color="tab:red", label="zero-shot")
        ax[2].plot(t, s[f"{b}_P_adapted_mw"], "^-", color="tab:green", label="adapted")
        ax[2].set_ylabel(f"{b} P (MW)", fontsize=7)
    ax[3].plot(t, s[f"bus_{vb}_Vm_ac_pu"], "ko-", label="AC")
    ax[3].plot(t, s[f"bus_{vb}_Vm_zero_shot_pu"], "x--", color="tab:red", label="zero-shot")
    ax[3].plot(t, s[f"bus_{vb}_Vm_adapted_pu"], "^-", color="tab:green", label="adapted")
    ax[3].set_ylabel(f"bus {vb} Vm (pu)", fontsize=7)
    ax[4].semilogy(t, s["PBE_mean"], "x--", color="tab:red", label="PBE zero-shot (MVA)")
    ax[4].semilogy(t, s["adapted_PBE_mean"], "^-", color="tab:green", label="PBE adapted (MVA)")
    ax[4].semilogy(t, s["dc_P_residual"], "k:", label="DC-PF active residual (MW)")
    ax[4].set_ylabel("error")
    for a_ in ax:
        a_.legend(fontsize=6)
    fig.suptitle(
        f"{eid} ({e['class_name']}): AC vs GENCO zero-shot vs topology-adapted", fontsize=9
    )
    fig.text(
        0.01,
        0.005,
        "PV: EUMETSAT LSA SAF MDSSFTD → pvlib (estimate). Network: UKPN (CC BY "
        "4.0). GENCO: gridfm/genco-pf-transfer (+ E5 synthetic fine-tune).",
        fontsize=6,
    )
    fig.autofmt_xdate()
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    fig.savefig(FIGS / f"e5_hero_{eid}.png", dpi=120)
    plt.close(fig)


def cmd_weather() -> None:
    sel, reg = frozen_selection()
    ev = event_windows()
    fams = {
        "S0_STANDARD_SYNTHETIC": "S1_WEATHER_ALIGNED",
        "S1_WEATHER_ALIGNED": None,
        "S1_WEATHER_ALIGNED_BASE_LTDS": None,
        "E4D_TIMELINE": None,
    }
    M: dict[str, dict[str, pd.DataFrame]] = {"zero_shot": {}, "adapted": {}}
    TB: dict[str, pd.DataFrame] = {}
    TBR: dict[str, pd.DataFrame] = {}
    for ck, run in (("zero_shot", "zero_shot"), ("adapted", sel)):
        for fam, rf in fams.items():
            m, b, br = family_frame(fam, run, ratings_from=rf)
            m["genco_runtime_s"] = runtime_of(run, fam)
            M[ck][fam] = m
            if fam == "E4D_TIMELINE":
                TB[ck], TBR[ck] = b, br
        s2 = []
        for s in S2_SEEDS:
            m, _, _ = family_frame(f"S2_MATCHED_PV_CONTROL_s{s}", run)
            m["control_seed"] = s
            m["genco_runtime_s"] = runtime_of(run, f"S2_MATCHED_PV_CONTROL_s{s}")
            s2.append(m)
        M[ck]["S2_MATCHED_PV_CONTROL"] = pd.concat(s2, ignore_index=True)

    # ---- per-scenario table (E4 schema + checkpoint)
    rename = {
        "slot": "timestamp",
        "p_hv_injected_mw": "PV_injected_MW",
        "fleet_pv_mw": "PV_MW",
        "fleet_cf": "PV_capacity_factor",
        "abs_hv_ramp_mw": "PV_ramp_MW",
        "ac_converged": "AC_converged",
        "genco_runtime_s": "runtime",
    }
    keep = [
        "scenario_id",
        "scenario_family",
        "slot",
        "control_seed",
        "fleet_pv_mw",
        "p_hv_injected_mw",
        "fleet_cf",
        "mean_kc",
        "abs_hv_ramp_mw",
        "ac_converged",
        *CORE,
        "max_loading_error",
        "max_loading_ac",
        "overload_ac",
        "overload_pred",
        "vlim_ac",
        "vlim_pred",
        "ac_import_mw",
        "genco_import_mw",
        "genco_runtime_s",
        "block",
        "donor_slot",
        "load_p_mw",
    ]
    parts = []
    for ck in M:
        for _fam, m in M[ck].items():
            parts.append(m[[c for c in keep if c in m]].assign(checkpoint=ck))
    allm = pd.concat(parts, ignore_index=True)
    allm.rename(columns=rename).to_parquet(TABLES / "e5_scenario_metrics.parquet", index=False)

    # ---- family summaries (both checkpoints)
    rows = []
    for ck in M:
        for fam, m in M[ck].items():
            r = summarise(m, None)
            r.update(
                {
                    "checkpoint": ck,
                    "family": fam
                    if fam != "S2_MATCHED_PV_CONTROL"
                    else "S2_MATCHED_PV_CONTROL (10 seeds pooled)",
                }
            )
            for flag in ("overload_ac", "overload_pred", "vlim_ac", "vlim_pred"):
                if flag in m:
                    r[f"n_{flag}"] = int(m[flag].fillna(False).sum())
            rows.append(r)
        for s, m in M[ck]["S2_MATCHED_PV_CONTROL"].groupby("control_seed"):
            rows.append(
                {"checkpoint": ck, "family": f"S2_MATCHED_PV_CONTROL_s{s}", **summarise(m, None)}
            )
    FS = pd.DataFrame(rows)
    lead = ["checkpoint", "family"]
    FS = FS[lead + [c for c in FS if c not in lead]]
    FS.to_csv(TABLES / "e5_family_summary.csv", index=False)

    # ---- gaps (adapted = primary; zero-shot recomputed as a check against E4)
    gaps, seed_gaps = [], []
    gap_metrics = [
        "PBE_mean",
        "P_residual",
        "Q_residual",
        "V_error",
        "angle_error",
        "branch_P_error",
        "branch_Q_error",
        "max_loading_error",
    ]
    for ck in M:
        S1, S0, S2 = (
            M[ck]["S1_WEATHER_ALIGNED"],
            M[ck]["S0_STANDARD_SYNTHETIC"],
            M[ck]["S2_MATCHED_PV_CONTROL"],
        )
        s2_mean = S2.groupby("slot")[gap_metrics].mean().add_suffix("_s2")
        paired = (
            S1.set_index("slot")[gap_metrics + ["block"]].join(s2_mean, how="inner").reset_index()
        )
        for c in gap_metrics:
            g2 = st.gap_paired(paired, c, f"{c}_s2", "block", BOOT["resamples"], BOOT["seed"])
            gaps.append(
                {
                    "checkpoint": ck,
                    "metric": c,
                    "comparison": "S1 − S2_MATCHED_PV_CONTROL (paired; mean over 10 seeds)",
                    **g2,
                    "material": st.material(g2, 0.10),
                }
            )
            g0 = st.gap_unpaired(
                S1[c], S1["block"], S0[c], S0["block"], BOOT["resamples"], BOOT["seed"]
            )
            gaps.append(
                {
                    "checkpoint": ck,
                    "metric": c,
                    "comparison": "S1 − S0_STANDARD_SYNTHETIC (operating distribution incl. "
                    "load level, N-1, admittance perturbation — not weather)",
                    **g0,
                    "material": st.material(g0, 0.10),
                }
            )
            for s, m in S2.groupby("control_seed"):
                p = (
                    S1.set_index("slot")[[c, "block"]]
                    .join(m.set_index("slot")[[c]].add_suffix("_s2"), how="inner")
                    .reset_index()
                )
                gs = st.gap_paired(p, c, f"{c}_s2", "block", BOOT["resamples"], BOOT["seed"])
                seed_gaps.append({"checkpoint": ck, "metric": c, "control_seed": s, **gs})
    GP = pd.DataFrame(gaps)
    GP.to_csv(TABLES / "e5_generalisation_gaps.csv", index=False)
    pd.DataFrame(seed_gaps).to_csv(TABLES / "e5_seed_gaps.csv", index=False)

    # ---- conditioning on the pre-registered weather variables (adapted, S1)
    cond = []
    S1a = M["adapted"]["S1_WEATHER_ALIGNED"]
    for var in ("fleet_cf", "mean_kc", "abs_hv_ramp_mw"):
        q = pd.qcut(S1a[var], 4, labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")
        for lab, g in S1a.groupby(q, observed=True):
            for c in ("PBE_mean", "P_residual", "V_error", "branch_P_error"):
                ci = st.block_mean_ci(g[c], g["block"], BOOT["resamples"], BOOT["seed"])
                cond.append(
                    {
                        "variable": var,
                        "bin": str(lab),
                        "range": f"{g[var].min():.3f}–{g[var].max():.3f}",
                        "metric": c,
                        **ci,
                    }
                )
    pd.DataFrame(cond).to_csv(TABLES / "e5_conditioning.csv", index=False)

    # ---- E4-D transitions, frozen ramp bins
    trans, T = {}, {}
    for ck in M:
        T[ck] = M[ck]["E4D_TIMELINE"]
        pairs = tr.consecutive_pairs(T[ck][["scenario", "slot", "p_hv_injected_mw"]])
        t_ = tr.transition_metrics(TB[ck], TBR[ck], pairs)
        t_["block"] = pd.to_datetime(t_["slot_i"], utc=True).dt.strftime("%Y-%m-%d")
        trans[ck] = t_
    RC = ramp_table(trans, T)
    RC.to_csv(TABLES / "e5_ramp_conditioned.csv", index=False)
    ev_rows = []
    for e in ev.itertuples():
        row: dict[str, Any] = {"event_id": e.event_id, "class": e.event_class}
        for ck in M:
            g = trans[ck][in_window(trans[ck]["slot_j"], e)]  # E4: tagged by end slot
            s = T[ck][in_window(T[ck]["slot"], e)]
            row["states"] = len(s)
            row["max_abs_dPV_mw"] = float(g.abs_dPV_injected_mw.max()) if len(g) else np.nan
            row[f"{ck}_dP_err_mean_abs"] = float(g.dP_err_mean_abs.mean()) if len(g) else np.nan
            row[f"{ck}_dVm_err_mean_abs"] = float(g.dVm_err_mean_abs.mean()) if len(g) else np.nan
            row[f"{ck}_tracking_ratio_median"] = (
                float(g.dP_tracking_ratio.median()) if len(g) else np.nan
            )
            row[f"{ck}_PBE_mean"] = float(s.PBE_mean.mean()) if len(s) else np.nan
            row[f"{ck}_V_error"] = float(s.V_error.mean()) if len(s) else np.nan
        ev_rows.append(row)
    pd.DataFrame(ev_rows).to_csv(TABLES / "e5_transitions_by_event.csv", index=False)
    not_eval = hero_outputs(ev, T, TB, TBR)

    # ---- REF import diagnostic per population and checkpoint (append to the synthetic rows)
    imp = []
    for ck in M:
        for fam, m in M[ck].items():
            imp.append(
                {
                    "population": fam,
                    "run": "zero_shot" if ck == "zero_shot" else sel,
                    **ad.import_diagnostic(
                        m.set_index(m.index)[["ac_import_mw", "genco_import_mw"]]
                    ),
                }
            )
    syn = pd.read_csv(TABLES / "e5_import_diagnostic.csv")
    syn = syn[syn.population == "held-out synthetic test"]
    pd.concat([syn, pd.DataFrame(imp)], ignore_index=True).to_csv(
        TABLES / "e5_import_diagnostic.csv", index=False
    )

    # ---- normalizer sensitivity (reported only)
    ns = normalizer_sensitivity(sel)
    ns.to_csv(TABLES / "e5_normalizer_sensitivity.csv", index=False)
    # ---- representation cells (only if the merged representation was retained)
    rep = representation_cells(sel, reg)
    if rep is not None:
        rep.to_csv(TABLES / "e5_representation_cells.csv", index=False)

    # ---- runtime
    rt = []
    for ck in M:
        for fam, m in M[ck].items():
            rt.append(
                {
                    "checkpoint": ck,
                    "family": fam,
                    "genco_s_per_scenario_incl_startup": float(m["genco_runtime_s"].mean()),
                    "ac_powermodels_s": float(m["pm_runtime_s"].mean())
                    if "pm_runtime_s" in m
                    else np.nan,
                    "ac_pandapower_s": float(m["pp_runtime_s"].mean())
                    if "pp_runtime_s" in m
                    else np.nan,
                }
            )
    pd.DataFrame(rt).to_csv(TABLES / "e5_runtime.csv", index=False)
    family_figure(M)
    ramp_figure(RC)

    # ---- decision (pre-registered)
    prim = GP[
        (GP.checkpoint == "adapted")
        & (GP.metric == "PBE_mean")
        & GP.comparison.str.startswith("S1 − S2")
    ].iloc[0]
    zs_r = RC.set_index("ramp_bin")["zero_shot_tracking_ratio_median"]
    ad_r = RC.set_index("ramp_bin")["adapted_tracking_ratio_median"]
    improved = {b: bool(abs(1 - ad_r[b]) < abs(1 - zs_r[b])) for b in ("high", "extreme")}
    ramp_improved = all(improved.values())
    ramp_acceptable = bool(0.8 <= ad_r["extreme"] <= 1.25)
    gap = bool(prim["material"])
    if gap:
        outcome = "B_TOPOLOGY_ADAPTATION_EXPOSES_WEATHER_GAP"
    elif ramp_improved:
        outcome = "A_TOPOLOGY_ADAPTATION_SUFFICIENT_WEATHER_ROBUST"
    else:
        outcome = "D_OTHER"
    det = {}
    for ck in M:
        m = M[ck]["S1_WEATHER_ALIGNED"]
        a, p = m["overload_ac"].fillna(False), m["overload_pred"].fillna(False)
        va, vp = m["vlim_ac"].fillna(False), m["vlim_pred"].fillna(False)
        det[ck] = {
            "overload_tp": int((a & p).sum()),
            "overload_fn": int((a & ~p).sum()),
            "overload_fp": int((~a & p).sum()),
            "vlim_tp": int((va & vp).sum()),
            "vlim_fn": int((va & ~vp).sum()),
            "vlim_fp": int((~va & vp).sum()),
        }
    res = {
        "selected_checkpoint": sel,
        "primary_gap_S1_vs_S2_adapted": prim.to_dict(),
        "material_weather_gap": gap,
        "ramp_tracking_median": {"zero_shot": zs_r.to_dict(), "adapted": ad_r.to_dict()},
        "ramp_improved_high_extreme": improved,
        "ramp_acceptable_extreme": ramp_acceptable,
        "outcome": outcome,
        "detection_S1": det,
        "hero_not_evaluable": not_eval,
        "zero_shot_check_vs_E4": {
            "S1_PBE": float(
                FS[
                    (FS.checkpoint == "zero_shot") & (FS.family == "S1_WEATHER_ALIGNED")
                ].PBE_mean.iloc[0]
            ),
            "S1_minus_S2_PBE": float(
                GP[
                    (GP.checkpoint == "zero_shot")
                    & (GP.metric == "PBE_mean")
                    & GP.comparison.str.startswith("S1 − S2")
                ].iloc[0]["difference"]
            )
            if "difference" in GP
            else None,
        },
        "environment": runner.environment(),
    }
    (OUT / "weather_evaluation.json").write_text(json.dumps(res, indent=2, default=str))
    print(
        json.dumps(
            {k: res[k] for k in ("material_weather_gap", "ramp_tracking_median", "outcome")},
            indent=1,
            default=str,
        )
    )
    print(
        FS[
            [
                "checkpoint",
                "family",
                "n",
                "PBE_mean",
                "P_residual",
                "dc_P_residual",
                "V_error",
                "angle_error",
                "branch_P_error",
            ]
        ].to_string()
    )


def normalizer_sensitivity(sel: str) -> pd.DataFrame:
    man = ad.assert_synthetic_dataset(ad.ALLOWED_ROOT)
    test = ad.pool_ids(man, "test").tolist()
    b, br = read_raw(ad.ALLOWED_ROOT, test)
    dc_syn = gm.dc_baseline_frames(b, br)
    dc_s1 = gm.dc_baseline(E4W / "datasets/S1_WEATHER_ALIGNED" / NET / "raw")
    blocks = man.set_index("scenario")["load_block"]
    rows = []
    cases = [
        ("zero_shot", "E4 fixed S0 base", "synthetic_test", "synthetic_test", dc_syn),
        ("zero_shot", "E4 S1-own base", "synthetic_test", "synthetic_test__norm_e4_s1own", dc_syn),
        ("zero_shot", "E4 fixed S0 base", "S1_WEATHER_ALIGNED", "S1_WEATHER_ALIGNED", dc_s1),
        ("zero_shot", "E4 S1-own base", "S1_WEATHER_ALIGNED", "S1_WEATHER_ALIGNED_ownnorm", dc_s1),
        (sel, "own train-fitted (primary)", "synthetic_test", "synthetic_test", dc_syn),
        (sel, "E4 fixed S0 base", "synthetic_test", "synthetic_test__norm_e4_s0", dc_syn),
        (sel, "E4 S1-own base", "synthetic_test", "synthetic_test__norm_e4_s1own", dc_syn),
        (sel, "own train-fitted (primary)", "S1_WEATHER_ALIGNED", "S1_WEATHER_ALIGNED", dc_s1),
        (sel, "E4 fixed S0 base", "S1_WEATHER_ALIGNED", "S1_WEATHER_ALIGNED__norm_e4_s0", dc_s1),
        (sel, "E4 S1-own base", "S1_WEATHER_ALIGNED", "S1_WEATHER_ALIGNED__norm_e4_s1own", dc_s1),
    ]
    bases = {"E4 fixed S0 base": 116.0, "E4 S1-own base": None}
    for p in ("e4_s0", "e4_s1own"):
        fam = "S0_STANDARD_SYNTHETIC" if p == "e4_s0" else "S1_WEATHER_ALIGNED"
        j = REPO_ROOT / f"reports/experiments/e4/normalizer_{fam}.json"
        bases["E4 fixed S0 base" if p == "e4_s0" else "E4 S1-own base"] = json.loads(j.read_text())[
            "baseMVA"
        ]
    for run, norm, pop, target, dc in cases:
        d = pred_dir(run, target)
        if not (d / f"{NET}_predictions.parquet").exists():
            continue
        m, bus = score(run, target, dc, None)
        m["block"] = (
            blocks.reindex(m["scenario"]).to_numpy() if pop == "synthetic_test" else m["scenario"]
        )
        base = bases.get(norm)
        if norm.startswith("own"):
            base = json.loads((OUT / "runs" / f"{sel}.json").read_text())["normalizer"]["baseMVA"]
        rows.append(
            {
                "checkpoint": "zero_shot" if run == "zero_shot" else "adapted",
                "run": run,
                "normalizer": norm,
                "baseMVA": base,
                "population": pop,
                "n": len(m),
                **{
                    c: float(m[c].mean())
                    for c in ("PBE_mean", "P_residual", "V_error", "angle_error", "branch_P_error")
                },
                **ad.import_diagnostic(
                    m.set_index("scenario")[["ac_import_mw", "genco_import_mw"]]
                ),
            }
        )
    return pd.DataFrame(rows)


def representation_cells(sel: str, reg: dict) -> pd.DataFrame | None:
    rj = json.loads((OUT / "representation.json").read_text())
    if rj["verdict"] != "AC_EQUIVALENT":
        return None
    merged_run = reg.get("sensitivity", {}).get("adapted_merged_run")
    gates = OUT / "S1_WEATHER_ALIGNED_MERGED_gates.parquet"
    cells = [
        ("zero_shot", "original", "zero_shot", "S1_WEATHER_ALIGNED", E4W / "datasets", None),
        (
            "zero_shot",
            "merged",
            "zero_shot",
            "S1_WEATHER_ALIGNED_MERGED",
            ad.WORK / "datasets",
            gates,
        ),
        ("adapted", "original", sel, "S1_WEATHER_ALIGNED", E4W / "datasets", None),
        ("adapted", "merged", merged_run, "S1_WEATHER_ALIGNED_MERGED", ad.WORK / "datasets", gates),
    ]
    rows = []
    for ck, rep, run, fam, base, gp in cells:
        if run is None or not (pred_dir(run, fam) / f"{NET}_predictions.parquet").exists():
            continue
        m, _, _ = family_frame(fam, run, dataset_base=base, gates_path=gp)
        rows.append(
            {
                "checkpoint": ck,
                "representation": rep,
                "run": run,
                "population": fam,
                **summarise(m, None),
            }
        )
    return pd.DataFrame(rows)


def family_figure(M: dict) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    for ax, (c, unit) in zip(
        axes, [("PBE_mean", "MVA"), ("V_error", "pu"), ("branch_P_error", "MW")], strict=True
    ):
        data, labels = [], []
        for ck in ("zero_shot", "adapted"):
            for fam, lab in (
                ("S0_STANDARD_SYNTHETIC", "S0"),
                ("S1_WEATHER_ALIGNED", "S1"),
                ("S2_MATCHED_PV_CONTROL", "S2"),
            ):
                data.append(M[ck][fam][c].dropna())
                labels.append(f"{lab}\n{'ZS' if ck == 'zero_shot' else 'adapt'}")
        ax.boxplot(data, tick_labels=labels, showfliers=False)
        ax.set_yscale("log")
        ax.set_title(f"{c} ({unit})", fontsize=9)
    fig.suptitle("GENCO on Sundon by family: zero-shot (E4) vs topology-adapted (E5)", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIGS / "e5_family_distributions.png", dpi=120)
    plt.close(fig)


def ramp_figure(RC: pd.DataFrame) -> None:
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.8))
    x = np.arange(len(RC))
    ax[0].bar(
        x - 0.2, RC["zero_shot_tracking_ratio_median"], 0.4, color="tab:red", label="zero-shot"
    )
    ax[0].bar(x + 0.2, RC["adapted_tracking_ratio_median"], 0.4, color="tab:green", label="adapted")
    ax[0].axhline(1.0, color="k", ls=":")
    ax[0].set_xticks(x, RC["ramp_bin"])
    ax[0].set_ylabel("median Σ|ΔP_GENCO| / Σ|ΔP_AC|")
    ax[0].set_title("Branch-flow tracking of PV ramps (within half-hour)", fontsize=9)
    ax[0].legend(fontsize=7)
    ax[1].plot(x, RC["dP_ac_mean_abs"], "ko-", label="AC |ΔP| (true change)")
    ax[1].plot(
        x, RC["zero_shot_dP_err_mean_abs"], "x--", color="tab:red", label="zero-shot ΔP error"
    )
    ax[1].plot(x, RC["adapted_dP_err_mean_abs"], "^-", color="tab:green", label="adapted ΔP error")
    ax[1].set_yscale("log")
    ax[1].set_xticks(x, RC["ramp_bin"])
    ax[1].set_ylabel("MW per directed edge")
    ax[1].legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIGS / "e5_ramp_conditioned.png", dpi=120)
    plt.close(fig)


def load_donors() -> pd.DataFrame:
    """The E4 S2 donor mappings, reused unchanged (never regenerated in E5)."""
    return pd.read_parquet(E4FAM / "S2_donors.parquet")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["synthetic", "freeze", "weather"])
    a = ap.parse_args()
    TABLES.mkdir(exist_ok=True)
    FIGS.mkdir(exist_ok=True)
    if a.command == "synthetic":
        cmd_synthetic()
    elif a.command == "freeze":
        cmd_freeze()
    else:
        cmd_weather()
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    sys.exit(main())
