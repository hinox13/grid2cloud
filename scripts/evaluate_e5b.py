"""E5b evaluation: synthetic learning curve + gate + selection → freeze → real transfer → coverage.

    uv run python scripts/evaluate_e5b.py synthetic   # E5b + E5 tests, val pool; gate; selection
    uv run python scripts/evaluate_e5b.py freeze         # metadata/e5b_checkpoint_registry.yaml
    uv run python scripts/evaluate_e5b.py coverage    # synthetic support (+ real after freeze)
    uv run --env-file .env python scripts/evaluate_e5b.py transfer   # only after freeze

Rules: configs/experiments/e5b_adaptation.yaml. `synthetic` and the pre-freeze part of `coverage`
read ONLY synthetic pools. `transfer` and the real-state part of `coverage` refuse to run until the
registry is frozen; nothing they compute can change the recipe, the checkpoint or the criteria.
The weather / ramp repeat runs only if REAL_TRANSFER_SUCCESS (scripts/evaluate_e5.py machinery).

Outputs: reports/tables/e5b_*.csv, reports/figures/e5b_*.png, reports/experiments/e5b/*.json
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
from cloud2grid.genco import adaptation as ad5  # noqa: E402
from cloud2grid.genco import adaptation_e5b as ad  # noqa: E402
from cloud2grid.genco import runner  # noqa: E402
from cloud2grid.licensing.registry import REPO_ROOT  # noqa: E402

CFG = ad.CFG
ENV = yaml.safe_load((REPO_ROOT / "configs/experiments/e5b_operating_envelope.yaml").read_text())
ZS = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_zero_shot.yaml").read_text())
BOOT = ZS["statistics"]["bootstrap"]
E4W = REPO_ROOT / "data/interim/e4"
E4FAM = REPO_ROOT / "reports/experiments/e4/families"
OUT = REPO_ROOT / "reports/experiments/e5b"
E5OUT = REPO_ROOT / "reports/experiments/e5"
TABLES = REPO_ROOT / "reports/tables"
FIGS = REPO_ROOT / "reports/figures"
REGISTRY = REPO_ROOT / "metadata/e5b_checkpoint_registry.yaml"
E5_REGISTRY = REPO_ROOT / "metadata/e5_checkpoint_registry.yaml"
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
LOAD_NODES = [n for s in ENV["primary_sites"].values() for n in s["node_shares"]]
IDX = ENV["datakit_bus_index"]
PV_NODES = ENV["hv_generation"]["nodes"]
BATT = ENV["storage"]["node"]


def e5_selected() -> str:
    return yaml.safe_load(E5_REGISTRY.read_text())["selected"]


def pred_dir(run: str, target: str) -> Path:
    """Where predictions live. E4 zero-shot on real families and E5 runs on E5/real targets are
    reused from their own (frozen) experiments; everything else is under data/interim/e5b."""
    if run == "zero_shot" and target in ad.REAL_FAMILIES:
        return E4W / "predictions" / target
    if run.startswith("ft_") and target == "e5_synthetic_test":
        return ad5.WORK / "predictions" / run / "synthetic_test"
    if run == e5_selected() and target in ("S1_WEATHER_ALIGNED", "S0_STANDARD_SYNTHETIC"):
        return ad5.WORK / "predictions" / run / target
    if run == "zero_shot" and target == "e5_synthetic_test":
        return ad5.WORK / "predictions" / "zero_shot" / "synthetic_test"
    return ad.WORK / "predictions" / run / target


def base_ratings(ids: Any) -> pd.DataFrame:
    r = pd.read_parquet(E4W / "datasets/S1_WEATHER_ALIGNED" / NET / "branch_ratings.parquet")
    base = r[r["scenario"] == 0].drop(columns="scenario")
    return base.merge(pd.DataFrame({"scenario": np.asarray(ids, dtype=int)}), how="cross")


def read_raw(
    root: Path, ids: list[int] | None = None, cols: list[str] | None = None, table: str = "bus_data"
) -> pd.DataFrame:
    f = [("scenario", "in", [int(i) for i in ids])] if ids is not None else None
    df = pd.read_parquet(root / NET / "raw" / f"{table}.parquet", filters=f, columns=cols)
    return df.drop(columns="scenario_partition", errors="ignore")


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
    row: dict[str, Any] = {"n": int(len(m))}
    for c in CORE:
        if c not in m or not m[c].notna().any():
            continue
        if c == "PBE_max":
            row[c] = float(m[c].max())
            continue
        ci = st.block_mean_ci(m[c], m[block], BOOT["resamples"], BOOT["seed"])
        row[c], row[f"{c}_ci"] = ci["mean"], [round(ci["ci_low"], 6), round(ci["ci_high"], 6)]
    for q in (0.5, 0.9, 0.95, 0.99):
        row[f"PBE_q{int(q * 100)}"] = float(m["PBE_mean"].quantile(q))
    row["genco_vs_dc_active_ratio"] = row["P_residual"] / row["dc_P_residual"]
    imp = m.set_index("scenario")[["ac_import_mw", "genco_import_mw"]]
    row.update(ad.import_diagnostic(imp))
    row["import_bias_mw"] = float((imp.genco_import_mw - imp.ac_import_mw).mean())
    row["import_sd_pred_mw"] = float(imp.genco_import_mw.std())
    row["import_sd_ac_mw"] = float(imp.ac_import_mw.std())
    if bus is not None:
        row["vm_tracking_median_r"] = ad.voltage_tracking(bus)
    return row


# ------------------------------------------------------------------ synthetic
def cmd_synthetic() -> dict:
    man = ad.assert_synthetic_dataset(ad.ALLOWED_ROOT)
    man5 = ad5.assert_synthetic_dataset(ad5.ALLOWED_ROOT)
    pools = {
        "synthetic_test": (
            ad.ALLOWED_ROOT,
            ad.pool_ids(man, "test").tolist(),
            man.set_index("scenario")["load_block"],
        ),
        "synthetic_val": (
            ad.ALLOWED_ROOT,
            ad.pool_ids(man, "val").tolist(),
            man.set_index("scenario")["load_block"],
        ),
        "e5_synthetic_test": (
            ad5.ALLOWED_ROOT,
            ad5.pool_ids(man5, "test").tolist(),
            man5.set_index("scenario")["load_block"],
        ),
    }
    dc = {
        k: gm.dc_baseline_frames(read_raw(r, i), read_raw(r, i, table="branch_data"))
        for k, (r, i, _) in pools.items()
    }
    runs = [
        {"run": "zero_shot", "n_train": 0, "seed": None, "init": "pretrained", "recipe": "E4"},
        {"run": e5_selected(), "n_train": 50000, "seed": 0, "init": "pretrained", "recipe": "E5"},
    ]
    runs += [
        {**json.loads(p.read_text()), "recipe": "E5b"}
        for p in sorted((OUT / "runs").glob("*.json"))
    ]
    rows, per = [], []
    for r in runs:
        for target, (_, ids, blocks) in pools.items():
            if target == "synthetic_val" and r["recipe"] != "E5b" and r["run"] != "zero_shot":
                continue
            d = pred_dir(r["run"], target)
            if not (d / f"{NET}_predictions.parquet").exists():
                continue
            m, bus = score(
                r["run"],
                target,
                dc[target],
                base_ratings(ids) if target != "synthetic_val" else None,
            )
            m["block"] = blocks.reindex(m["scenario"]).to_numpy()
            rec = {
                "run": r["run"],
                "recipe": r["recipe"],
                "n_train": r["n_train"],
                "seed": r["seed"],
                "init": r["init"],
                "target": target,
                **summarise(m, bus),
            }
            for k in ("wall_s", "best_epoch", "epochs_run", "best_validation_loss"):
                rec[k] = r.get(k)
            rec["gpu"] = (r.get("environment") or {}).get("gpu")
            rec["normalizer_baseMVA"] = (r.get("normalizer") or {}).get("baseMVA")
            rec["checkpoint_sha256"] = (r.get("checkpoint") or {}).get("sha256")
            rec["normalizer_sha256"] = (r.get("normalizer") or {}).get("sha256")
            rows.append(rec)
            if target == "synthetic_test":
                per.append(m.assign(run=r["run"]))
    S = pd.DataFrame(rows)
    test = S[S.target == "synthetic_test"].set_index("run")
    zs = test.loc["zero_shot"].to_dict()
    g_rows = []
    for run, rec in test.iterrows():
        g = ad.gate(rec.to_dict(), zs) if run.startswith("e5b_") else {"pass": False}
        g_rows.append({"run": run, **{f"gate_{k}": v for k, v in g.items()}})
    G = pd.DataFrame(g_rows)
    S = S.merge(G, on="run", how="left")
    val = S[S.target == "synthetic_val"].set_index("run")["PBE_mean"].rename("val_pool_PBE_mean")
    S = S.merge(val, left_on="run", right_index=True, how="left")
    S.to_csv(TABLES / "e5b_seed_results.csv", index=False)
    pd.concat(per, ignore_index=True).to_parquet(
        OUT / "synthetic_scenario_metrics.parquet", index=False
    )

    # learning curve: E5b (own test, E5 test) beside E5 (own test, from the frozen E5 table)
    lc = []
    e5lc = pd.read_csv(TABLES / "e5_seed_results.csv")
    e5lc = e5lc[e5lc.init == "pretrained"].assign(recipe="E5", target="e5_synthetic_test")
    allr = pd.concat([S[(S.recipe == "E5b") & (S.init == "pretrained")], e5lc], ignore_index=True)
    for (recipe, target, n), g in allr.groupby(["recipe", "target", "n_train"]):
        if target == "synthetic_val":
            continue
        row = {"recipe": recipe, "target": target, "n_train": int(n), "seeds": int(len(g))}
        for c in (
            "PBE_mean",
            "P_residual",
            "Q_residual",
            "branch_P_error",
            "V_error",
            "angle_error",
            "import_mae_mw",
            "import_corr",
            "vm_tracking_median_r",
            "wall_s",
        ):
            if c in g and g[c].notna().any():
                row[c], row[f"{c}_min"], row[f"{c}_max"] = (
                    float(g[c].mean()),
                    float(g[c].min()),
                    float(g[c].max()),
                )
        row["dc_P_residual"] = float(g["dc_P_residual"].mean())
        if "gate_pass" in g and recipe == "E5b" and target == "synthetic_test":
            row["all_seeds_pass_gate"] = bool(g["gate_pass"].fillna(False).astype(bool).all())
        lc.append(row)
    for target in ("synthetic_test", "e5_synthetic_test"):
        z = S[(S.run == "zero_shot") & (S.target == target)]
        if len(z):
            lc.append(
                {
                    "recipe": "E4 zero-shot",
                    "target": target,
                    "n_train": 0,
                    "seeds": 1,
                    **{
                        c: float(z[c].iloc[0])
                        for c in (
                            "PBE_mean",
                            "P_residual",
                            "branch_P_error",
                            "V_error",
                            "angle_error",
                            "dc_P_residual",
                        )
                    },
                }
            )
    LC = pd.DataFrame(lc).sort_values(["target", "recipe", "n_train"])
    LC.to_csv(TABLES / "e5b_learning_curve.csv", index=False)

    ft = test[test.index.str.startswith("e5b_ft_")].join(G.set_index("run"))
    ft = ft.join(val)
    sizes = sorted(ft.n_train.unique())
    first = next((int(n) for n in sizes if ft[ft.n_train == n].gate_pass.astype(bool).all()), None)
    sat = None
    if {1000, 10000} <= set(sizes):
        m1, m10 = (
            ft[ft.n_train == 1000].mean(numeric_only=True),
            ft[ft.n_train == 10000].mean(numeric_only=True),
        )
        imp = {c: float(1 - m10[c] / m1[c]) for c in ("PBE_mean", "P_residual")}
        sat = {"improvement_1k_to_10k": imp, "saturated": all(v < 0.05 for v in imp.values())}
    cand = ft[ft.gate_pass.astype(bool)]
    flagged = False
    if cand.empty:
        cand, flagged = ft, True
    selected = None
    if len(cand) and cand.val_pool_PBE_mean.notna().any():
        best = cand.val_pool_PBE_mean.min()
        tie = cand[cand.val_pool_PBE_mean <= best * 1.01].sort_values(
            ["n_train", "val_pool_PBE_mean"]
        )
        selected = tie.index[0]
    res = {
        "zero_shot_on_e5b_test": {k: zs[k] for k in ("PBE_mean", "P_residual", "dc_P_residual")},
        "runs_passing_synthetic_gate": cand.index.tolist() if not flagged else [],
        "first_size_all_seeds_pass": first,
        "saturation_rule": sat,
        "selection_rule": CFG["checkpoint_selection"]["criterion"],
        "selected": selected,
        "selected_without_gate_pass": flagged,
        **runner.git_commit(),
    }
    (OUT / "synthetic_evaluation.json").write_text(json.dumps(res, indent=2, default=str))
    learning_curve_figure(LC)
    cols = [
        "run",
        "target",
        "PBE_mean",
        "P_residual",
        "dc_P_residual",
        "import_sign_accuracy",
        "vm_tracking_median_r",
        "gate_pass",
        "val_pool_PBE_mean",
    ]
    print(S[S.target != "synthetic_val"][cols].round(4).to_string(index=False))
    print(
        json.dumps(
            {
                k: res[k]
                for k in (
                    "first_size_all_seeds_pass",
                    "saturation_rule",
                    "selected",
                    "selected_without_gate_pass",
                )
            },
            indent=1,
            default=str,
        )
    )
    return res


def learning_curve_figure(LC: pd.DataFrame, real: pd.DataFrame | None = None) -> None:
    panels = [
        ("synthetic_test", "E5b held-out synthetic test"),
        ("e5_synthetic_test", "E5 held-out synthetic test"),
    ]
    if real is not None:
        panels.append(("S1_WEATHER_ALIGNED", "REAL 2024 states (S1) — post-freeze diagnostic"))
    fig, axes = plt.subplots(2, len(panels), figsize=(5.2 * len(panels), 7.2), squeeze=False)
    styles = {
        "E5": ("o-", "tab:red", "E5 recipe (datakit agg profile)"),
        "E5b": ("s-", "tab:green", "E5b envelope recipe"),
    }
    for j, (target, title) in enumerate(panels):
        src = LC if target != "S1_WEATHER_ALIGNED" else real
        for i, c in enumerate(("PBE_mean", "P_residual")):
            ax = axes[i, j]
            for recipe, (fmt, col, lab) in styles.items():
                g = src[(src.recipe == recipe) & (src.target == target) & (src.n_train > 0)]
                if g.empty:
                    continue
                yerr = [g[c] - g[f"{c}_min"], g[f"{c}_max"] - g[c]] if f"{c}_min" in g else None
                ax.errorbar(g.n_train, g[c], yerr=yerr, fmt=fmt, color=col, capsize=3, label=lab)
            z = src[(src.recipe == "E4 zero-shot") & (src.target == target)]
            if len(z):
                ax.plot([30], [z[c].iloc[0]], "kx", ms=9, label="zero-shot (E4)")
                if c == "P_residual":
                    ax.axhline(z["dc_P_residual"].iloc[0], color="grey", ls=":", label="DC-PF")
            ax.set_xscale("log")
            ax.set_yscale("log")
            ax.set_title(f"{title}\n{c} ({'MVA' if c == 'PBE_mean' else 'MW'})", fontsize=8)
            ax.set_xlabel("Sundon synthetic training states")
            ax.legend(fontsize=6)
    fig.suptitle(
        "GENCO topology adaptation: E5 vs E5b synthetic recipes (mean over seeds; bars = range)",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(FIGS / "e5b_learning_curve.png", dpi=120)
    plt.close(fig)


# ------------------------------------------------------------------ freeze
def cmd_freeze() -> None:
    res = json.loads((OUT / "synthetic_evaluation.json").read_text())
    sel = res["selected"]
    if not sel:
        raise SystemExit("no E5b checkpoint to select")
    rec = json.loads((OUT / "runs" / f"{sel}.json").read_text())
    S = pd.read_csv(TABLES / "e5b_seed_results.csv")
    t = S[S.target == "synthetic_test"].set_index("run")
    curve = {}
    for p in sorted((OUT / "runs").glob("e5b_ft_*.json")):
        r = json.loads(p.read_text())
        curve[r["run"]] = {
            "checkpoint": r["checkpoint"],
            "normalizer": {k: r["normalizer"][k] for k in ("path", "sha256", "baseMVA")},
        }
    for p in sorted((E5OUT / "runs").glob("ft_*.json")):
        r = json.loads(p.read_text())
        curve[r["run"]] = {
            "checkpoint": r["checkpoint"],
            "normalizer": {k: r["normalizer"][k] for k in ("path", "sha256", "baseMVA")},
        }
    reg = {
        "schema": "cloud2grid E5b checkpoint registry v1",
        "frozen": True,
        "frozen_before_real_state_evaluation": True,
        "selection_basis": "synthetic only: synthetic gate on the E5b held-out test, then "
        + CFG["checkpoint_selection"]["criterion"],
        "selected": sel,
        "selected_without_gate_pass": res["selected_without_gate_pass"],
        "evaluable_on_real": [sel, *[r for r in curve if r != sel]],
        "checkpoints": {
            sel: {
                "n_train": rec["n_train"],
                "seed": rec["seed"],
                "init": rec["init"],
                "recipe": "E5b envelope (configs/experiments/e5b_operating_envelope.yaml)",
                "checkpoint": rec["checkpoint"],
                "normalizer": rec["normalizer"],
                "normalizer_fitted_on": rec["normalizer_fitted_on"],
                "training_split_sha256": rec["split_sha256"],
                "best_epoch": rec["best_epoch"],
                "epochs_run": rec["epochs_run"],
                "best_validation_loss": rec["best_validation_loss"],
                "val_pool_PBE_mean": float(t.at[sel, "val_pool_PBE_mean"]),
                "held_out_synthetic_test": {
                    k: float(t.at[sel, k]) for k in ("PBE_mean", "P_residual", "dc_P_residual")
                },
                "graphkit_config": rec["graphkit_config"],
                "mlflow_run": rec["mlflow_run"],
            }
        },
        "post_freeze_curve_runs": curve,
        "post_freeze_curve_note": "every E5/E5b fine-tuned ladder checkpoint, scored on S1 AFTER "
        "this "
        "freeze for the combined learning-curve figure only",
        **runner.git_commit(),
    }
    REGISTRY.write_text(yaml.safe_dump(reg, sort_keys=False, allow_unicode=True))
    print(yaml.safe_dump(reg["checkpoints"], sort_keys=False))


def frozen() -> dict:
    if not REGISTRY.exists() or not yaml.safe_load(REGISTRY.read_text()).get("frozen"):
        raise SystemExit("E5b registry not frozen: real states stay hidden")
    reg = yaml.safe_load(REGISTRY.read_text())
    c = reg["checkpoints"][reg["selected"]]
    for k in ("checkpoint", "normalizer"):
        if ad.sha256_file(REPO_ROOT / c[k]["path"]) != c[k]["sha256"]:
            raise SystemExit(f"{k} changed after freezing")
    return reg


# ------------------------------------------------------------------ coverage
def state_features(root: Path, ids: list[int] | None = None) -> pd.DataFrame:
    """Per state: total net load, slack import, envelope injections, Vm range, max branch |P|."""
    bus = read_raw(root, ids, ["scenario", "bus", "Pd", "Pg", "Vm", "REF"])
    br = read_raw(root, ids, ["scenario", "pf", "br_status"], table="branch_data")
    p = bus.pivot(index="scenario", columns="bus", values="Pd")
    f = pd.DataFrame(index=p.index)
    f["total_net_load_mw"] = p.sum(axis=1)
    f["slack_import_mw"] = bus[bus.REF == 1].set_index("scenario")["Pg"]
    for node in LOAD_NODES + PV_NODES + [BATT]:
        f[f"Pd {node}"] = p[IDX[node]]
    f["pv_injection_mw"] = -p[[IDX[n] for n in PV_NODES]].sum(axis=1)
    g = bus.groupby("scenario")["Vm"]
    f["vm_min_pu"], f["vm_max_pu"] = g.min(), g.max()
    f["branch_abs_P_max_mw"] = (
        br[br.br_status > 0].assign(a=lambda d: d.pf.abs()).groupby("scenario")["a"].max()
    )
    return f


def cmd_coverage() -> None:
    man = ad.assert_synthetic_dataset(ad.ALLOWED_ROOT)
    man5 = ad5.assert_synthetic_dataset(ad5.ALLOWED_ROOT)
    F = {
        "E5 train pool": state_features(ad5.ALLOWED_ROOT, ad5.pool_ids(man5, "train").tolist()),
        "E5b train pool": state_features(ad.ALLOWED_ROOT, ad.pool_ids(man, "train").tolist()),
    }
    real = None
    try:
        frozen()
        real = state_features(E4W / "datasets/S1_WEATHER_ALIGNED")
        F["S1 real 2024 (held out)"] = real
    except SystemExit as e:
        print(f"real-state coverage skipped: {e}")
    rows = []
    for var in F["E5b train pool"].columns:
        r: dict[str, Any] = {"variable": var}
        for name, f in F.items():
            x = f[var].dropna()
            (
                r[f"{name} min"],
                r[f"{name} p5"],
                r[f"{name} p50"],
                r[f"{name} p95"],
                r[f"{name} max"],
            ) = (x.min(), x.quantile(0.05), x.median(), x.quantile(0.95), x.max())
        if real is not None:
            for name in ("E5 train pool", "E5b train pool"):
                lo, hi = F[name][var].min(), F[name][var].max()
                x = real[var].dropna()
                r[f"S1 share inside {name}"] = float(((x >= lo - 1e-6) & (x <= hi + 1e-6)).mean())
        rows.append(r)
    C = pd.DataFrame(rows)
    C.to_csv(TABLES / "e5b_coverage_comparison.csv", index=False)
    out = {"variables": len(C)}
    if real is not None:
        out["coverage_achieved_e5b"] = bool((C["S1 share inside E5b train pool"] >= 0.95).all())
        out["coverage_achieved_e5"] = bool((C["S1 share inside E5 train pool"] >= 0.95).all())
        out["min_share_inside_e5b"] = float(C["S1 share inside E5b train pool"].min())
        out["joint_nn"] = joint_nn(F)
    (OUT / "coverage.json").write_text(json.dumps(out, indent=2, default=str))
    coverage_figure(F)
    print(C.round(3).to_string(index=False))
    print(json.dumps(out, indent=1, default=str))


def joint_nn(F: dict[str, pd.DataFrame]) -> dict[str, float]:
    """Nearest-neighbour distance in standardised envelope injections (+ total load)."""
    cols = ["total_net_load_mw"] + [f"Pd {n}" for n in LOAD_NODES + PV_NODES + [BATT]]
    rng = np.random.default_rng(0)
    out = {}
    for pool in ("E5 train pool", "E5b train pool"):
        tr = F[pool][cols].dropna().to_numpy()
        tr = tr[rng.choice(len(tr), min(20000, len(tr)), replace=False)]
        mu, sd = tr.mean(0), tr.std(0) + 1e-9
        z = (tr - mu) / sd

        def nn(
            x: np.ndarray, z: np.ndarray = z, mu: np.ndarray = mu, sd: np.ndarray = sd
        ) -> np.ndarray:
            q = (x - mu) / sd
            return np.array([np.sqrt(((z - v) ** 2).sum(1)).min() for v in q])

        own = nn(tr[rng.choice(len(tr), 500, replace=False)] + 0)  # includes self → ~0
        held = F[pool][cols].dropna().to_numpy()
        held = held[rng.choice(len(held), 500, replace=False)]
        real = F["S1 real 2024 (held out)"][cols].dropna().to_numpy()
        real = real[rng.choice(len(real), min(500, len(real)), replace=False)]
        out[f"{pool}: median NN distance, pool sample → pool"] = float(np.median(nn(held)))
        out[f"{pool}: median NN distance, S1 → pool"] = float(np.median(nn(real)))
        del own
    return out


def coverage_figure(F: dict[str, pd.DataFrame]) -> None:
    vars_ = [
        "total_net_load_mw",
        "slack_import_mw",
        f"Pd {BATT}",
        "pv_injection_mw",
        "Pd EPN:CHAU51",
        "Pd EPN:LBUZ51",
        "Pd EPN:SUPR52",
        "vm_min_pu",
    ]
    fig, axes = plt.subplots(2, 4, figsize=(16, 6.5))
    cols = {
        "E5 train pool": "tab:red",
        "E5b train pool": "tab:green",
        "S1 real 2024 (held out)": "k",
    }
    for ax, v in zip(axes.flat, vars_, strict=True):
        for name, f in F.items():
            x = f[v].dropna()
            ax.hist(
                x,
                bins=60,
                density=True,
                histtype="step" if "S1" in name else "stepfilled",
                alpha=1 if "S1" in name else 0.35,
                color=cols[name],
                label=name,
                lw=1.4,
            )
        ax.set_title(v, fontsize=8)
    axes.flat[0].legend(fontsize=7)
    fig.suptitle(
        "Operating-state support: E5 vs E5b synthetic training pools"
        + (" vs real 2024 states (after freeze)" if len(F) > 2 else ""),
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(FIGS / "e5b_coverage.png", dpi=120)
    plt.close(fig)


# ------------------------------------------------------------------ real transfer
def real_frame(run: str, fam: str = "S1_WEATHER_ALIGNED") -> tuple[pd.DataFrame, pd.DataFrame]:
    gates = pd.read_parquet(E4FAM / f"{fam}_gates.parquet")
    d = pred_dir(run, fam)
    bus = pd.read_parquet(d / f"{NET}_predictions.parquet")
    branch = pd.read_parquet(d / f"{NET}_branch_predictions.parquet")
    ratings = pd.read_parquet(E4W / "datasets" / fam / NET / "branch_ratings.parquet")
    m = gm.scenario_metrics(bus, branch, ratings)
    m = m.merge(gm.dc_baseline(E4W / "datasets" / fam / NET / "raw").reset_index(), on="scenario")
    m = m.merge(ad.ref_import(bus).reset_index(), on="scenario", how="left")
    acc = gates[gates["rejected"].isna()].copy()
    acc["scenario"] = acc["scenario"].astype(int)
    m = m.merge(acc, on="scenario", how="left")
    m["block"] = pd.to_datetime(m["slot"], utc=True).dt.strftime("%Y-%m-%d")
    m["scenario_id"] = fam + ":" + m["scenario"].astype(str)
    return m, bus


def import_sensitivity(m: pd.DataFrame, feats: pd.DataFrame) -> dict[str, float]:
    """OLS slopes of import on (primary load, CHAP31, PV injection): GENCO vs AC."""
    x = feats.reindex(m["scenario"].to_numpy())
    load = x[[f"Pd {n}" for n in LOAD_NODES]].sum(axis=1).to_numpy()
    X = np.column_stack(
        [np.ones(len(x)), load, x[f"Pd {BATT}"].to_numpy(), x["pv_injection_mw"].to_numpy()]
    )
    out = {}
    for lab, y in (
        ("ac", m["ac_import_mw"].to_numpy()),
        ("genco", m["genco_import_mw"].to_numpy()),
    ):
        b = np.linalg.lstsq(X, y, rcond=None)[0]
        out.update(
            {f"{lab}_slope_load": b[1], f"{lab}_slope_chap31": b[2], f"{lab}_slope_pv": b[3]}
        )
    return {k: float(v) for k, v in out.items()}


def cmd_transfer() -> None:
    reg = frozen()
    sel = reg["selected"]
    feats = state_features(E4W / "datasets/S1_WEATHER_ALIGNED")
    models = {"zero-shot (E4)": "zero_shot", "E5 adapted": e5_selected(), "E5b adapted": sel}
    rows, frames = [], {}
    for lab, run in models.items():
        m, bus = real_frame(run)
        frames[lab] = m
        r = {"model": lab, "run": run, **summarise(m, bus), **import_sensitivity(m, feats)}
        rows.append(r)
    T = pd.DataFrame(rows)
    T.to_csv(TABLES / "e5b_real_transfer.csv", index=False)
    e5 = T.set_index("model").loc["E5 adapted"]
    b = T.set_index("model").loc["E5b adapted"]
    crit = {
        "R1_active": b.P_residual <= 0.10 * e5.P_residual,
        "R2_pbe": (b.PBE_mean <= 0.10 * e5.PBE_mean) and (b.PBE_q95 <= 10.0),
        "R3_import": (b.import_sign_accuracy >= 0.99)
        and (b.import_mae_mw <= 5.0)
        and (b.import_corr >= 0.9)
        and (0.75 <= b.import_sd_pred_mw / b.import_sd_ac_mw <= 1.33),
        "R4_voltage": (b.vm_tracking_median_r >= 0.8) and (b.V_error <= 0.01),
    }
    partial = {
        "P1": b.P_residual <= 0.5 * e5.P_residual,
        "P2": b.PBE_mean <= 0.5 * e5.PBE_mean,
        "P3": b.import_corr >= 0.5,
    }
    success = all(bool(v) for v in crit.values())
    part = (not success) and all(bool(v) for v in partial.values())
    synth = json.loads((OUT / "synthetic_evaluation.json").read_text())
    if success:
        verdict = "E5B-A_SYNTHETIC_COVERAGE_FIXES_REAL_TRANSFER"
    elif part or synth["selected_without_gate_pass"]:
        verdict = "E5B-C_PARTIAL_OR_INCONCLUSIVE"
    else:
        verdict = "E5B-B_BROADER_SYNTHETIC_COVERAGE_STILL_DOES_NOT_TRANSFER"
    cov = (
        json.loads((OUT / "coverage.json").read_text()) if (OUT / "coverage.json").exists() else {}
    )
    achieved = cov.get("coverage_achieved_e5b")
    if verdict.startswith("E5B-A"):
        hyp = "SUPPORTED"
    elif verdict.startswith("E5B-B") and achieved:
        hyp = "NOT_SUPPORTED"
    else:
        hyp = "INCONCLUSIVE"
    # paired block-bootstrap of the E5b − E5 difference on the same states (reported)
    a, c = frames["E5b adapted"].set_index("scenario"), frames["E5 adapted"].set_index("scenario")
    paired = a[["PBE_mean", "P_residual", "block"]].join(
        c[["PBE_mean", "P_residual"]], rsuffix="_e5"
    )
    gaps = {
        k: st.gap_paired(
            paired.reset_index(), k, f"{k}_e5", "block", BOOT["resamples"], BOOT["seed"]
        )
        for k in ("PBE_mean", "P_residual")
    }
    res = {
        "selected": sel,
        "criteria": {k: bool(v) for k, v in crit.items()},
        "partial": {k: bool(v) for k, v in partial.items()},
        "REAL_TRANSFER_SUCCESS": success,
        "PARTIAL_TRANSFER": part,
        "verdict": verdict,
        "coverage_hypothesis": hyp,
        "coverage_achieved_e5b": achieved,
        "e5b_minus_e5_on_S1": gaps,
        "environment": runner.environment(),
    }
    (OUT / "real_transfer.json").write_text(json.dumps(res, indent=2, default=str))
    imp = T[
        [
            "model",
            "run",
            "import_sign_accuracy",
            "import_mae_mw",
            "import_bias_mw",
            "import_corr",
            "import_sd_pred_mw",
            "import_sd_ac_mw",
            "import_dynamic_range",
            "ac_slope_load",
            "genco_slope_load",
            "ac_slope_chap31",
            "genco_slope_chap31",
            "ac_slope_pv",
            "genco_slope_pv",
        ]
    ]
    imp.to_csv(TABLES / "e5b_import_diagnostic.csv", index=False)
    real_curve()
    cols = [
        "model",
        "PBE_mean",
        "PBE_q50",
        "PBE_q95",
        "P_residual",
        "Q_residual",
        "V_error",
        "angle_error",
        "branch_P_error",
        "import_mae_mw",
        "import_corr",
        "vm_tracking_median_r",
    ]
    print(T[cols].round(4).to_string(index=False))
    print(
        json.dumps(
            {k: res[k] for k in ("criteria", "partial", "verdict", "coverage_hypothesis")},
            indent=1,
            default=str,
        )
    )


def real_curve() -> None:
    """Post-freeze diagnostic: every E5 / E5b fine-tuned ladder checkpoint on S1 (no selection)."""
    rows = []
    for rec_dir, recipe in ((E5OUT / "runs", "E5"), (OUT / "runs", "E5b")):
        for p in sorted(rec_dir.glob("*ft_*.json")):
            r = json.loads(p.read_text())
            d = pred_dir(r["run"], "S1_WEATHER_ALIGNED")
            if not (d / f"{NET}_predictions.parquet").exists():
                continue
            m, _ = real_frame(r["run"])
            rows.append(
                {
                    "recipe": recipe,
                    "run": r["run"],
                    "n_train": r["n_train"],
                    "seed": r["seed"],
                    "PBE_mean": float(m.PBE_mean.mean()),
                    "P_residual": float(m.P_residual.mean()),
                }
            )
    if not rows:
        return
    R = pd.DataFrame(rows)
    z, _ = real_frame("zero_shot")
    agg = (
        R.groupby(["recipe", "n_train"])
        .agg(
            PBE_mean=("PBE_mean", "mean"),
            PBE_mean_min=("PBE_mean", "min"),
            PBE_mean_max=("PBE_mean", "max"),
            P_residual=("P_residual", "mean"),
            P_residual_min=("P_residual", "min"),
            P_residual_max=("P_residual", "max"),
            seeds=("run", "count"),
        )
        .reset_index()
    )
    agg["target"] = "S1_WEATHER_ALIGNED"
    agg = pd.concat(
        [
            agg,
            pd.DataFrame(
                [
                    {
                        "recipe": "E4 zero-shot",
                        "target": "S1_WEATHER_ALIGNED",
                        "n_train": 0,
                        "PBE_mean": float(z.PBE_mean.mean()),
                        "P_residual": float(z.P_residual.mean()),
                        "dc_P_residual": float(z.dc_P_residual.mean()),
                    }
                ]
            ),
        ]
    )
    agg.to_csv(TABLES / "e5b_real_learning_curve.csv", index=False)
    learning_curve_figure(pd.read_csv(TABLES / "e5b_learning_curve.csv"), agg)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["synthetic", "freeze", "coverage", "transfer"])
    a = ap.parse_args()
    TABLES.mkdir(exist_ok=True)
    FIGS.mkdir(exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    {
        "synthetic": cmd_synthetic,
        "freeze": cmd_freeze,
        "coverage": cmd_coverage,
        "transfer": cmd_transfer,
    }[a.command]()
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    sys.exit(main())
