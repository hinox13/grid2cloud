"""E6 feasibility diagnostic: why does GENCO learn the response but not the absolute import?

Read-only with respect to every frozen artefact. Synthetic populations only for the diagnosis:
  - E5c held-out synthetic test (2,804 states, generator-aware encoding): E5c (frozen n10000 s2),
    the E5d λ = 0 control and every E5d run (λ = 1 s0 is the frozen selection);
  - E5b held-out synthetic test (2,818 states): E5b (frozen n10000 s2, original encoding) and the
    same states re-encoded generator-aware for E5c / E5d.
The E5c training split (n10000 s0, the absolute data of every E5d run) is read for coverage only.

One section (`exploratory_real`) summarises the EXISTING frozen E5d S1 predictions. It is labelled
exploratory, feeds no conclusion about cause and must not be used to design, tune or select E6.

`trace` runs the frozen E5d model forward on CPU through graphkit's own datamodule (no training,
no gradient, nothing written under data/). It checks that the frozen predictions are reproduced
and records the in-model quantities the parquet exports do not contain.

  PYTHONPATH=src uv run python scripts/diagnose_e6_feasibility.py all

Outputs: reports/tables/e6_*.csv, reports/figures/e6_*.png,
         reports/experiments/e6_feasibility/diagnostic.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import types
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from cloud2grid.licensing.registry import REPO_ROOT  # noqa: E402

if REPO_ROOT.resolve() != Path(__file__).resolve().parents[1]:
    # an editable install from another checkout would silently read that checkout's data
    raise SystemExit(
        f"cloud2grid resolves to {REPO_ROOT}, not this checkout: run with PYTHONPATH=src"
    )

I = REPO_ROOT / "data/interim"  # noqa: E741
TAB = REPO_ROOT / "reports/tables"
FIG = REPO_ROOT / "reports/figures"
OUT = REPO_ROOT / "reports/experiments/e6_feasibility"

REF_BUS, BATTERY_BUS, GEN_BUSES = 22, 0, (8, 9, 10)
SIGN_MW = 5.0

E5C_TEST = {  # label -> prediction dir (E5c held-out synthetic test, generator-aware)
    "E5c (frozen)": I / "e5c/predictions/e5c_ft_n10000_s2/synthetic_test",
    "E5d λ0 control": I / "e5d/predictions/e5d_l0_s0/synthetic_test",
    "E5d λ0.3": I / "e5d/predictions/e5d_l0.3_s0/synthetic_test",
    "E5d λ1 s0 (frozen)": I / "e5d/predictions/e5d_l1_s0/synthetic_test",
    "E5d λ1 s1": I / "e5d/predictions/e5d_l1_s1/synthetic_test",
    "E5d λ1 s2": I / "e5d/predictions/e5d_l1_s2/synthetic_test",
    "E5d λ3": I / "e5d/predictions/e5d_l3_s0/synthetic_test",
}
E5B_TEST = {  # same 2,818 states; E5b in its own (negative-load) encoding
    "E5b (frozen)": I / "e5b/predictions/e5b_ft_n10000_s2/synthetic_test",
    "E5c (frozen)": I / "e5c/predictions/e5c_ft_n10000_s2/e5b_test_ga",
    "E5d λ1 s0 (frozen)": I / "e5d/predictions/e5d_l1_s0/e5b_test_ga",
}
SELECTED = "E5d λ1 s0 (frozen)"

INK, INK_2, MUTED, GRID = "#0f172a", "#3b4659", "#5f6b84", "#e7ecf3"
COL = {
    "E5b (frozen)": "#1baf7a",
    "E5c (frozen)": "#2a78d6",
    SELECTED: "#751e5f",
    "E5d λ0 control": "#8a94a8",
}


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ----------------------------------------------------------------- per-state table
def states(pred_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per scenario: AC / predicted import and every quantity used below; per (scenario, bus):
    signed nodal active-power mismatch of the predicted state (evaluation convention: known
    generator output and demand clamped to their inputs, as graphkit's predict_step does)."""
    b = pd.read_parquet(pred_dir / "sundon_33kv_predictions.parquet")
    br = pd.read_parquet(pred_dir / "sundon_33kv_branch_predictions.parquet")
    pin = br.groupby(["scenario", "from_bus"])[["Pft", "Pft_target"]].sum()
    b = b.join(pin.rename_axis(["scenario", "bus"]), on=["scenario", "bus"]).fillna(
        {"Pft": 0.0, "Pft_target": 0.0}
    )
    nonref = b.REF == 0
    b["res"] = np.where(nonref, b.Pg_target - b.Pd - b.Pft, 0.0)
    b["res_true"] = np.where(nonref, b.Pg_target - b.Pd - b.Pft_target, 0.0)
    b["dVa"] = b.Va_pred - b.Va_target  # radians: graphkit keeps Va in radians on export
    b["dVm"] = b.Vm_pred - b.Vm_target
    g = b.groupby("scenario")
    ref = b[b.REF == 1].set_index("scenario")
    gen_rows = b[b.bus.isin(GEN_BUSES)]
    # generation at LBUZ: explicit generator (E5c/E5d) or negative demand (E5b): Pg - Pd covers both
    gen = (gen_rows.Pg_target - gen_rows.Pd).groupby(gen_rows.scenario).sum()
    load_rows = b[(~b.bus.isin((*GEN_BUSES, BATTERY_BUS))) & nonref]
    S = pd.DataFrame(
        {
            "ac_import": ref.Pg_target,
            "pred_import": ref.Pg_pred,
            "load": load_rows.groupby("scenario").Pd.sum(),
            "battery": b[b.bus == BATTERY_BUS].set_index("scenario").Pd,  # + = charging
            "gen": gen,
            "loss_ac": g.Pft_target.sum(),
            "loss_pred": g.Pft.sum(),
            "sum_res": b[nonref].groupby("scenario").res.sum(),
            "sum_abs_res": b[nonref].groupby("scenario").res.apply(lambda x: x.abs().sum()),
            "max_true_res": b[nonref].groupby("scenario").res_true.apply(lambda x: x.abs().max()),
            "vm_ref": ref.Vm_target,
            "cm_dVa_deg": np.degrees(b[nonref].groupby("scenario").dVa.mean()),
            "pbe_mean": g.PBE.mean(),
            "vm_mae": b[nonref].groupby("scenario").dVm.apply(lambda x: x.abs().mean()),
            "va_mae_deg": np.degrees(
                b[nonref].groupby("scenario").dVa.apply(lambda x: x.abs().mean())
            ),
            "branch_p_mae": (br.Pft - br.Pft_target).abs().groupby(br.scenario).mean(),
        }
    )
    S["err"] = S.pred_import - S.ac_import
    S["net_demand"] = S.load + S.battery - S.gen  # Σ demand − Σ local generation (MW)
    S["d_loss"] = S.loss_pred - S.loss_ac
    return S, b[["scenario", "bus", "res", "Pd", "Pg_target", "Pft"]]


def ols(x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    A = np.c_[np.ones_like(x), x]
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    yhat = A @ coef
    ss = ((y - y.mean()) ** 2).sum()
    return {
        "intercept": float(coef[0]),
        "slope": float(coef[1]),
        "r2": float(1 - ((y - yhat) ** 2).sum() / ss) if ss > 0 else float("nan"),
    }


def regime(ac: pd.Series) -> pd.Series:
    return pd.cut(
        ac,
        [-np.inf, -SIGN_MW, SIGN_MW, 30.0, np.inf],
        labels=["export (< −5 MW)", "near zero (±5 MW)", "import 5–30 MW", "import > 30 MW"],
    )


def summary(S: pd.DataFrame) -> dict[str, float]:
    a, p, e = S.ac_import, S.pred_import, S.err
    big = a.abs() >= SIGN_MW
    fit = ols(a.to_numpy(), p.to_numpy())
    exp, imp = a < -SIGN_MW, a > SIGN_MW
    recon = S.d_loss + S.sum_res
    return {
        "n": int(len(S)),
        "import_bias_mw": float(e.mean()),
        "import_mae_mw": float(e.abs().mean()),
        "import_rmse_mw": float(np.sqrt((e**2).mean())),
        "import_r": float(np.corrcoef(a, p)[0, 1]),
        "pred_vs_ac_intercept_mw": fit["intercept"],
        "pred_vs_ac_slope": fit["slope"],
        "spread_ratio": float(p.std() / a.std()),
        "sign_acc_abs_ge5": float((np.sign(a[big]) == np.sign(p[big])).mean()),
        "n_export_states": int(exp.sum()),
        "export_recall": float((p[exp] < 0).mean()) if exp.any() else float("nan"),
        "mae_export_mw": float(e[exp].abs().mean()) if exp.any() else float("nan"),
        "bias_export_mw": float(e[exp].mean()) if exp.any() else float("nan"),
        "mae_import_mw": float(e[imp].abs().mean()),
        "bias_import_mw": float(e[imp].mean()),
        "identity_r2": float(1 - ((e - recon) ** 2).sum() / ((e - e.mean()) ** 2).sum()),
        "identity_max_abs_dev_mw": float((e - recon).abs().max()),
        "mean_d_loss_mw": float(S.d_loss.mean()),
        "mean_abs_d_loss_mw": float(S.d_loss.abs().mean()),
        "mean_sum_res_mw": float(S.sum_res.mean()),
        "mean_sum_abs_res_mw": float(S.sum_abs_res.mean()),
        "coherence_sum_res_over_sum_abs": float(S.sum_res.abs().mean() / S.sum_abs_res.mean()),
        "pbe_mean": float(S.pbe_mean.mean()),
        "branch_p_mae_mw": float(S.branch_p_mae.mean()),
        "vm_mae_pu": float(S.vm_mae.mean()),
        "va_mae_deg": float(S.va_mae_deg.mean()),
        "corr_err_common_mode_dVa": float(np.corrcoef(e, S.cm_dVa_deg)[0, 1]),
    }


# ----------------------------------------------------------------- sections
def drivers(S: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for x in (
        "ac_import",
        "net_demand",
        "load",
        "gen",
        "battery",
        "loss_ac",
        "vm_ref",
        "cm_dVa_deg",
        "sum_res",
        "d_loss",
    ):
        rows.append({"driver": x, **ols(S[x].to_numpy(), S.err.to_numpy())})
    X = S[["load", "battery", "gen", "vm_ref"]].to_numpy()
    A = np.c_[np.ones(len(S)), X]
    coef, *_ = np.linalg.lstsq(A, S.err.to_numpy(), rcond=None)
    r2 = 1 - ((S.err - A @ coef) ** 2).sum() / ((S.err - S.err.mean()) ** 2).sum()
    rows.append(
        {
            "driver": "multi: load + battery + gen + vm_ref",
            "intercept": float(coef[0]),
            "slope": float("nan"),
            "r2": float(r2),
            "coef_load": float(coef[1]),
            "coef_battery": float(coef[2]),
            "coef_gen": float(coef[3]),
            "coef_vm_ref": float(coef[4]),
        }
    )
    return pd.DataFrame(rows)


def strata(S: pd.DataFrame, bias: float) -> pd.DataFrame:
    gen_bin = pd.cut(
        S.gen, [-1e-9, 1e-6, 2.5, 7.6], labels=["gen 0", "gen 0–2.5 MW", "gen 2.5–7.5 MW"]
    )
    T = S.assign(gen_bin=gen_bin, regime=regime(S.ac_import))
    T["pct_err"] = T.err.abs() / np.maximum(T.ac_import.abs(), SIGN_MW)  # safe near zero
    T["bias_corr_abs"] = (T.err - bias).abs()  # diagnostic only
    agg = T.groupby(["gen_bin", "regime"], observed=True).agg(
        n=("err", "size"),
        mean_err_mw=("err", "mean"),
        mae_mw=("err", lambda x: x.abs().mean()),
        median_pct_err=("pct_err", "median"),
        bias_corrected_mae_mw=("bias_corr_abs", "mean"),
        branch_p_mae_mw=("branch_p_mae", "mean"),
        vm_mae_pu=("vm_mae", "mean"),
    )
    return agg.reset_index()


def physical_baselines(S: pd.DataFrame, train_loss_mean: float) -> pd.DataFrame:
    a = S.ac_import
    lossless = S.net_demand  # Σ demand − Σ local generation: the DC / lossless balance
    cands = {
        "A  AC reference (pandapower/PowerModels)": a,
        "B  GENCO (frozen E5d) slack Pg": S.pred_import,
        "C  injections + AC losses (accounting check)": lossless + S.loss_ac,
        "D  injections + GENCO-predicted losses": lossless + S.loss_pred,
        "E1 injections, lossless (DC-type balance)": lossless,
        "E2 injections + constant mean training loss": lossless + train_loss_mean,
    }
    rows = []
    big = a.abs() >= SIGN_MW
    for k, v in cands.items():
        e = v - a
        rows.append(
            {
                "estimate": k,
                "bias_mw": float(e.mean()),
                "mae_mw": float(e.abs().mean()),
                "rmse_mw": float(np.sqrt((e**2).mean())),
                "max_abs_mw": float(e.abs().max()),
                "sign_acc_abs_ge5": float((np.sign(a[big]) == np.sign(v[big])).mean()),
                "needs": {
                    "A": "full AC solve",
                    "B": "GENCO forward pass",
                    "C": "AC losses (i.e. the AC solve)",
                    "D": "GENCO forward pass + sum",
                    "E": "sum of known injections only",
                }[k[0]],
            }
        )
    return pd.DataFrame(rows)


def train_coverage() -> dict:
    """AC import distribution of the absolute training data of every E5d run (E5c n10000 s0)."""
    import torch

    from cloud2grid.genco import adaptation_e5d as ad

    ids = torch.load(I / "e5c/splits/e5c_ft_n10000_s0/train.pt").tolist()
    raw = Path(ad.ABS_ROOT) / "sundon_33kv/raw/bus_data.parquet"
    b = pd.read_parquet(raw, columns=["scenario", "bus", "Pg", "Pd", "REF"])
    b = b[b.scenario.isin(ids)]
    imp = b[b.REF == 1].set_index("scenario").Pg
    loss = b.groupby("scenario").apply(lambda d: d.Pg.sum() - d.Pd.sum(), include_groups=False)
    return {
        "n_train": int(len(imp)),
        "share_export_lt_minus5": float((imp < -SIGN_MW).mean()),
        "share_negative": float((imp < 0).mean()),
        "share_near_zero_abs_lt5": float((imp.abs() < SIGN_MW).mean()),
        "import_mean_mw": float(imp.mean()),
        "import_p5_p50_p95_mw": [float(x) for x in np.percentile(imp, [5, 50, 95])],
        "train_loss_mean_mw": float(loss.mean()),
    }


def per_bus(R: pd.DataFrame, err: pd.Series) -> pd.DataFrame:
    c = R[R.bus != REF_BUS].pivot(index="scenario", columns="bus", values="res").reindex(err.index)
    out = pd.DataFrame(
        {
            "mean_res_mw": c.mean(),
            "sd_res_mw": c.std(),
            "share_of_err_variance": c.apply(lambda s: np.cov(s, err)[0, 1]) / err.var(),
        }
    )
    return out.sort_values("share_of_err_variance", ascending=False).reset_index()


def lbuz_injection(R: pd.DataFrame, S: pd.DataFrame) -> dict[str, float]:
    """Signed evaluation mismatch at the three LBUZ generation buses vs their generation:
    slope α > 0 means the predicted state exports less from LBUZ than the generation given."""
    r = R[R.bus.isin(GEN_BUSES)].groupby("scenario").res.sum().reindex(S.index)
    f = ols(S.gen.to_numpy(), r.to_numpy())
    return {
        "slope_res_on_gen": f["slope"],
        "intercept_mw": f["intercept"],
        "r2": f["r2"],
        "mean_res_mw": float(r.mean()),
    }


def ref_branch_sensitivity(pred_dir: Path) -> pd.DataFrame:
    br = pd.read_parquet(pred_dir / "sundon_33kv_branch_predictions.parquet")
    r = br[br.from_bus == REF_BUS]
    rows = []
    for tb, d in r.groupby("to_bus"):
        b_pu = float(np.abs(d.Yff_i).median())  # on graphkit's 100 MVA base
        e_mw = d.Pft - d.Pft_target
        rows.append(
            {
                "branch": f"{REF_BUS}→{tb}",
                "abs_B_pu_100MVA": b_pu,
                "mw_per_microrad": b_pu * 100.0 * 1e-6,
                "microrad_per_mw": 1.0 / (b_pu * 100.0 * 1e-6),
                "flow_err_mae_mw": float(e_mw.abs().mean()),
                "flow_err_bias_mw": float(e_mw.mean()),
            }
        )
    return pd.DataFrame(rows)


# ----------------------------------------------------------------- trace (CPU forward)
def trace(S_sel: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Frozen E5d forward pass on CPU via graphkit's datamodule. Returns per-example trace rows
    and full-test-set in-model checks (reproduction, decoder exactness, LBUZ in-model residual)."""
    import torch
    from gridfm_graphkit import cli
    from gridfm_graphkit.datasets.globals import PD_H, PG_OUT, VA_H, VM_H
    from gridfm_graphkit.datasets.hetero_powergrid_datamodule import LitGridHeteroDataModule
    from gridfm_graphkit.io.param_handler import get_task
    from gridfm_graphkit.models.utils import ComputeBranchFlow, ComputeNodeInjection
    from torch_geometric.loader import DataLoader

    from cloud2grid.genco import adaptation_e5d as ad

    torch.manual_seed(0)
    work = OUT / "trace_tmp"
    work.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load((I / "e5d/configs/predict_e5d_l1_s0__synthetic_test.yaml").read_text())
    cfg["data"]["split_from_existing_files"] = str(I / "e5d/splits/predict_synthetic_test")
    cfg["data"]["workers"] = 0
    (work / "cfg.yaml").write_text(yaml.safe_dump(cfg))
    ns = types.SimpleNamespace(
        config=str(work / "cfg.yaml"),
        config_conversion="auto_inline",
        converted_config_path=str(work / "cfg_conv.yaml"),
    )
    c = cli._load_config(ns)
    ck = I / "e5d/checkpoints/e5d_l1_s0"
    dm = LitGridHeteroDataModule(
        c, str(ad.ABS_ROOT), normalizer_stats_path=str(ck / "normalizer_stats.pt")
    )
    dm.setup("test")
    norm = dm.data_normalizers[0]
    task = get_task(c, dm.data_normalizers)
    task.load_state_dict(
        cli._normalize_loaded_state_dict_keys(
            torch.load(ck / "best_model_state_dict.pt", map_location="cpu")
        )
    )
    task.eval()
    model = task.model
    flow, inj = ComputeBranchFlow(), ComputeNodeInjection()
    base = float(norm.baseMVA)

    ds = dm.test_datasets[0]
    loader = DataLoader(ds, batch_size=64, shuffle=False)
    imp_model, imp_true_dec, lbuz_inmodel, lbuz_eval, n = [], [], [], [], 0
    import time

    t0 = time.perf_counter()
    with torch.no_grad():
        for batch in loader:
            model(batch)
    fwd_s = time.perf_counter() - t0
    with torch.no_grad():
        for batch in loader:
            out = model(batch)
            ob = out["bus"]
            ei = batch.edge_index_dict[("bus", "connects", "bus")]
            ea = batch.edge_attr_dict[("bus", "connects", "bus")]
            nb = batch.x_dict["bus"].size(0)
            isref = batch.mask_dict["REF"]
            # model REF Pg (normalised units) -> MW
            imp_model.append((ob[isref, PG_OUT] * base).numpy())
            # decoder fed the TRUE state: Vm, Va from targets (y), same admittances
            true_state = ob.clone()
            true_state[:, 0] = batch.y_dict["bus"][:, VM_H]
            true_state[:, 1] = batch.y_dict["bus"][:, VA_H]
            Pt, _ = inj(*flow(true_state, ei, ea), ei, nb)
            imp_true_dec.append(((Pt + batch.x_dict["bus"][:, PD_H])[isref] * base).numpy())
            # in-model residual at LBUZ (decoder puts Pg = 0 at PQ buses) vs evaluation residual
            P_in, _ = inj(*flow(ob, ei, ea), ei, nb)
            _, g2b = batch.edge_index_dict[("gen", "connected_to", "bus")]
            agg = torch.zeros(nb).index_add_(0, g2b, batch.x_dict["gen"][:, 0])
            Pd = batch.x_dict["bus"][:, PD_H]
            local = torch.arange(nb) - batch["bus"].ptr[batch["bus"].batch]
            lb = torch.isin(local, torch.tensor(GEN_BUSES))
            r_in = (ob[:, PG_OUT] - Pd - P_in)[lb].view(-1, 3).sum(1) * base
            r_ev = (agg - Pd - P_in)[lb].view(-1, 3).sum(1) * base
            lbuz_inmodel.append(r_in.numpy())
            lbuz_eval.append(r_ev.numpy())
            n += int(isref.sum())
    imp_model = np.concatenate(imp_model)
    imp_true_dec = np.concatenate(imp_true_dec)
    lbuz_in, lbuz_ev = np.concatenate(lbuz_inmodel), np.concatenate(lbuz_eval)
    S = S_sel.sort_index()
    checks = {
        "n_states": n,
        "cpu_forward_ms_per_state_batch64": 1e3 * fwd_s / n,
        "baseMVA_fitted": base,
        "max_abs_dev_model_vs_frozen_import_mw": float(
            np.abs(imp_model - S.pred_import.to_numpy()).max()
        ),
        "max_abs_dev_true_state_decoder_vs_ac_import_mw": float(
            np.abs(imp_true_dec - S.ac_import.to_numpy()).max()
        ),
        "lbuz_inmodel_residual_mean_mw": float(lbuz_in.mean()),
        "lbuz_eval_residual_mean_mw": float(lbuz_ev.mean()),
        "lbuz_inmodel_minus_eval_vs_gen_max_abs_mw": float(
            np.abs((lbuz_ev - lbuz_in) - S.gen.to_numpy()).max()
        ),
    }

    # representative examples, chosen by rule (no randomness)
    picks = {
        "deepest export": S.ac_import.idxmin(),
        "closest to zero import": S.ac_import.abs().idxmin(),
        "largest import": S.ac_import.idxmax(),
        "max generation, min net demand": S[S.gen >= S.gen.quantile(0.9)].net_demand.idxmin(),
        "median import": (S.ac_import - S.ac_import.median()).abs().idxmin(),
    }
    raw = pd.read_parquet(
        Path(ad.ABS_ROOT) / "sundon_33kv/raw/bus_data.parquet",
        filters=[("scenario", "in", [int(v) for v in picks.values()])],
    )
    rows = []
    pos = {s: i for i, s in enumerate(S.index)}
    for why, s in picks.items():
        item = ds[pos[s]]
        x = item.x_dict["bus"]
        rref = raw[(raw.scenario == s) & (raw.bus == REF_BUS)].iloc[0]
        with torch.no_grad():
            from torch_geometric.data import Batch

            o = model(Batch.from_data_list([item]))["bus"]
        rows.append(
            {
                "example": why,
                "scenario": int(s),
                "raw_sum_Pd_mw": float(raw[raw.scenario == s].Pd.sum()),
                "raw_gen_lbuz_mw": float(S.loc[s, "gen"]),
                "raw_battery_mw": float(S.loc[s, "battery"]),
                "raw_slack_vm_pu": float(rref.Vm),
                "ac_import_mw": float(S.loc[s, "ac_import"]),
                "norm_battery_Pd": float(x[BATTERY_BUS, PD_H]),
                "norm_battery_Pd_x_baseMVA_mw": float(x[BATTERY_BUS, PD_H] * base),
                "norm_ref_Vm_input": float(x[REF_BUS, VM_H]),
                "model_ref_Pg_norm": float(o[REF_BUS, PG_OUT]),
                "model_import_mw": float(o[REF_BUS, PG_OUT] * base),
                "frozen_reported_import_mw": float(S.loc[s, "pred_import"]),
                "true_state_decoder_import_mw": float(imp_true_dec[pos[s]]),
                "sum_nodal_mismatch_mw": float(S.loc[s, "sum_res"]),
                "d_loss_mw": float(S.loc[s, "d_loss"]),
                "common_mode_dVa_deg": float(S.loc[s, "cm_dVa_deg"]),
            }
        )
    for p in work.glob("*"):
        p.unlink()
    work.rmdir()
    return pd.DataFrame(rows), checks


# ----------------------------------------------------------------- normalizer audit
def normalizer_audit() -> dict:
    import torch

    regs = {
        r: (REPO_ROOT / f"metadata/{r}_checkpoint_registry.yaml").read_text()
        for r in ("e5c", "e5d")
    }
    out = {}
    for run, d in {
        "e5d_l1_s0": I / "e5d/checkpoints/e5d_l1_s0",
        "e5c_ft_n10000_s2": I / "e5c/checkpoints/e5c_ft_n10000_s2",
    }.items():
        w, n = sha(d / "best_model_state_dict.pt"), sha(d / "normalizer_stats.pt")
        st = torch.load(d / "normalizer_stats.pt", map_location="cpu")
        flat = st if "baseMVA" in st else next(iter(st.values()))
        out[run] = {
            "weights_sha256": w,
            "normalizer_sha256": n,
            "weights_in_own_registry": w in regs[run[:3]],
            "normalizer_in_own_registry": n in regs[run[:3]],
            "baseMVA": float(flat["baseMVA"]),
            "baseMVA_orig": float(flat["baseMVA_orig"]),
        }
    return out


def exploratory_real() -> pd.DataFrame:
    """EXPLORATORY ONLY (already-examined 2024 S1 population). Not used for any conclusion
    about cause, nor to design, tune or select anything."""
    S, _ = states(I / "e5d/predictions/e5d_l1_s0/S1_WEATHER_ALIGNED_GENAWARE")
    pv = pd.qcut(
        S.gen.rank(method="first"),
        3,
        labels=["PV low tercile", "PV mid tercile", "PV high tercile"],
    )
    T = S.assign(pv=pv, regime=regime(S.ac_import))
    rows = []
    for key in ("pv", "regime"):
        for k, d in T.groupby(key, observed=True):
            rows.append(
                {
                    "stratum": f"{key}: {k}",
                    "n": len(d),
                    "mean_err_mw": d.err.mean(),
                    "mae_mw": d.err.abs().mean(),
                    "sd_err_mw": d.err.std(),
                    "mean_ac_import_mw": d.ac_import.mean(),
                    "mean_gen_mw": d.gen.mean(),
                    "mean_sum_res_mw": d.sum_res.mean(),
                    "mean_d_loss_mw": d.d_loss.mean(),
                }
            )
    rows.append(
        {
            "stratum": "all",
            "n": len(S),
            "mean_err_mw": S.err.mean(),
            "mae_mw": S.err.abs().mean(),
            "sd_err_mw": S.err.std(),
            "mean_ac_import_mw": S.ac_import.mean(),
            "mean_gen_mw": S.gen.mean(),
            "mean_sum_res_mw": S.sum_res.mean(),
            "mean_d_loss_mw": S.d_loss.mean(),
            "identity_r2": summary(S)["identity_r2"],
            "slack_vm_mean_pu": S.vm_ref.mean(),
            "slack_vm_min_pu": S.vm_ref.min(),
            "slack_vm_max_pu": S.vm_ref.max(),
        }
    )
    return pd.DataFrame(rows)


# ----------------------------------------------------------------- figures
def _style(ax: plt.Axes, title: str, xl: str, yl: str) -> None:
    ax.set_title(title, loc="left", fontsize=10.5, color=INK, fontweight="bold")
    ax.set_xlabel(xl, fontsize=9, color=INK_2)
    ax.set_ylabel(yl, fontsize=9, color=INK_2)
    ax.tick_params(colors=MUTED, labelsize=8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.grid(color=GRID, lw=0.6)
    ax.set_axisbelow(True)


def fig_residuals(Sd: pd.DataFrame, Sc: pd.DataFrame) -> None:
    fig, axs = plt.subplots(2, 3, figsize=(14, 8.2), dpi=150)
    pts = dict(s=5, alpha=0.35, lw=0)
    ax = axs[0, 0]
    lim = [min(Sd.ac_import.min(), Sd.pred_import.min()) - 5, Sd.ac_import.max() + 5]
    ax.plot(lim, lim, color=INK, lw=1, ls="--")
    ax.scatter(Sc.ac_import, Sc.pred_import, color=COL["E5c (frozen)"], label="E5c (frozen)", **pts)
    ax.scatter(Sd.ac_import, Sd.pred_import, color=COL[SELECTED], label="E5d (frozen)", **pts)
    ax.legend(frameon=False, fontsize=8, markerscale=3, loc="upper left")
    _style(ax, "Predicted vs AC import", "AC import (MW)", "GENCO import (MW)")
    panels = [
        (axs[0, 1], "ac_import", "Residual vs AC import", "AC import (MW)"),
        (axs[0, 2], "net_demand", "Residual vs net demand", "Σ demand − Σ local generation (MW)"),
        (axs[1, 0], "load", "Residual vs total load", "Σ load excl. battery (MW)"),
        (axs[1, 1], "battery", "Residual vs battery", "CHAP31 demand (MW, + = charging)"),
        (axs[1, 2], "loss_ac", "Residual vs AC losses", "AC active losses (MW)"),
    ]
    for ax, x, t, xl in panels:
        ax.axhline(0, color=INK, lw=0.8)
        ax.scatter(Sd[x], Sd.err, color=COL[SELECTED], **pts)
        f = ols(Sd[x].to_numpy(), Sd.err.to_numpy())
        xx = np.linspace(Sd[x].min(), Sd[x].max(), 2)
        ax.plot(xx, f["intercept"] + f["slope"] * xx, color=INK, lw=1.2)
        ax.text(
            0.98,
            0.04,
            f"slope {f['slope']:+.3f}   R² {f['r2']:.2f}",
            transform=ax.transAxes,
            ha="right",
            fontsize=8.5,
            color=INK_2,
        )
        _style(ax, t, xl, "E5d import error (MW)")
    fig.suptitle(
        "E5d import residual on the held-out synthetic test (2,804 states)",
        x=0.01,
        ha="left",
        fontsize=13,
        fontweight="bold",
        color=INK,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(FIG / "e6_import_residuals.png", facecolor="white")
    plt.close(fig)


def fig_identity(Sd: pd.DataFrame, PB: pd.DataFrame) -> None:
    fig, axs = plt.subplots(
        1, 3, figsize=(14, 4.4), dpi=150, gridspec_kw={"width_ratios": [1, 1, 1.15]}
    )
    pts = dict(s=5, alpha=0.35, lw=0, color=COL[SELECTED])
    ax = axs[0]
    lim = [Sd.err.min() - 3, Sd.err.max() + 3]
    ax.plot(lim, lim, color=INK, lw=1, ls="--")
    ax.scatter(Sd.d_loss + Sd.sum_res, Sd.err, **pts)
    _style(
        ax,
        "Import error = Σ nodal mismatch + Δlosses",
        "Σ signed mismatch at 36 buses + Δlosses (MW)",
        "E5d import error (MW)",
    )
    ax = axs[1]
    ax.axhline(0, color=INK, lw=0.8)
    ax.scatter(Sd.cm_dVa_deg, Sd.err, **pts)
    _style(
        ax,
        "Error vs common-mode angle error",
        "mean Va error, non-slack buses (degrees)",
        "E5d import error (MW)",
    )
    ax = axs[2]
    top = PB.head(10)
    ax.barh(
        [f"bus {int(b)}" for b in top.bus][::-1],
        top.share_of_err_variance[::-1],
        color=COL[SELECTED],
        height=0.6,
    )
    for y, v in enumerate(top.share_of_err_variance[::-1]):
        ax.text(v + 0.005, y, f"{v:.0%}", va="center", fontsize=8, color=INK_2)
    _style(ax, "Where the mismatch sits (top 10 buses)", "share of import-error variance", "")
    fig.tight_layout()
    fig.savefig(FIG / "e6_mismatch_identity.png", facecolor="white")
    plt.close(fig)


def fig_regimes(pops: dict[str, pd.DataFrame]) -> None:
    labs = ["export (< −5 MW)", "near zero (±5 MW)", "import 5–30 MW", "import > 30 MW"]
    models = list(pops)
    fig, axs = plt.subplots(1, 2, figsize=(14, 4.6), dpi=150)
    ax = axs[0]
    w = 0.8 / len(models)
    for i, m in enumerate(models):
        S = pops[m]
        g = S.groupby(regime(S.ac_import), observed=False).err
        mae = [g.get_group(k).abs().mean() if k in g.groups else np.nan for k in labs]
        bias = [g.get_group(k).mean() if k in g.groups else np.nan for k in labs]
        x = np.arange(len(labs)) + (i - (len(models) - 1) / 2) * w
        ax.bar(x, mae, width=w * 0.92, color=COL[m], label=m)
        axs[1].bar(x, bias, width=w * 0.92, color=COL[m], label=m)
    for ax, t, yl in (
        (axs[0], "Import MAE by operating regime", "MAE (MW)"),
        (axs[1], "Import bias by operating regime", "mean error (MW)"),
    ):
        ax.set_xticks(np.arange(len(labs)), labs, fontsize=8.5)
        _style(ax, t, "AC operating regime (E5b held-out synthetic test, same 2,818 states)", yl)
    axs[1].axhline(0, color=INK, lw=0.8)
    axs[0].legend(frameon=False, fontsize=8.5)
    fig.tight_layout()
    fig.savefig(FIG / "e6_regimes.png", facecolor="white")
    plt.close(fig)


# ----------------------------------------------------------------- pairs and reach
PAIR_RUNS = {
    "E5c (frozen)": "e5c_ft_n10000_s2",
    SELECTED: "e5d_l1_s0",
    "E5d λ0 control": "e5d_l0_s0",
}


def pair_cancellation() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Held-out E5d TEST pairs: is the absolute import error shared by members A and B?"""
    m = pd.read_parquet(
        I / "e5d/pairs/test/pairs.parquet",
        columns=["probe_id", "probe_type", "member", "scenario", "complete"],
    )
    m = m[m.complete]
    rows, keep = [], []
    for lab, run in PAIR_RUNS.items():
        b = pd.read_parquet(
            I / f"e5d/predictions/{run}/pairs_test/sundon_33kv_predictions.parquet",
            columns=["scenario", "REF", "Pg_target", "Pg_pred"],
        )
        r = b[b.REF == 1].set_index("scenario")
        mm = m.assign(ac=m.scenario.map(r.Pg_target), pr=m.scenario.map(r.Pg_pred))
        w = mm.pivot_table(
            index=["probe_id", "probe_type"], columns="member", values=["ac", "pr"]
        ).dropna()
        for t, g in w.groupby(level="probe_type"):
            eA, eB = g["pr"]["A"] - g["ac"]["A"], g["pr"]["B"] - g["ac"]["B"]
            dac, dpr = g["ac"]["B"] - g["ac"]["A"], g["pr"]["B"] - g["pr"]["A"]
            rows.append(
                {
                    "model": lab,
                    "probe_type": t,
                    "n_pairs": len(g),
                    "level_mae_member_A_mw": float(eA.abs().mean()),
                    "corr_err_A_err_B": float(np.corrcoef(eA, eB)[0, 1]),
                    "delta_err_mae_mw": float((dpr - dac).abs().mean()),
                    "mean_abs_delta_ac_mw": float(dac.abs().mean()),
                }
            )
            if lab == SELECTED:
                keep.append(
                    pd.DataFrame(
                        {
                            "probe_id": g.index.get_level_values("probe_id"),
                            "probe_type": t,
                            "err_A": eA.to_numpy(),
                            "err_B": eB.to_numpy(),
                            "delta_ac": dac.to_numpy(),
                            "delta_pred": dpr.to_numpy(),
                        }
                    )
                )
    return pd.DataFrame(rows), pd.concat(keep, ignore_index=True)


def graph_reach() -> dict:
    br = pd.read_parquet(
        E5C_TEST[SELECTED] / "sundon_33kv_branch_predictions.parquet",
        columns=["scenario", "from_bus", "to_bus"],
    )
    br = br[br.scenario == br.scenario.min()]
    adj: dict[int, set[int]] = {}
    for f, t in zip(br.from_bus, br.to_bus, strict=True):
        adj.setdefault(int(f), set()).add(int(t))
        adj.setdefault(int(t), set()).add(int(f))

    def bfs(s: int) -> dict[int, int]:
        d, q = {s: 0}, [s]
        for u in q:
            for v in adj[u]:
                if v not in d:
                    d[v] = d[u] + 1
                    q.append(v)
        return d

    d = bfs(REF_BUS)
    return {
        "n_bus": len(adj),
        "n_branches": int(len(br) // 2),
        "max_hops_from_ref": max(d.values()),
        "graph_diameter_hops": max(max(bfs(s).values()) for s in adj),
        "message_passing_layers": 12,
        "hops_ref_to_lbuz": [d[k] for k in GEN_BUSES],
        "hops_ref_to_battery": d[BATTERY_BUS],
    }


def fig_pairs(P: pd.DataFrame, T: pd.DataFrame) -> None:
    fig, axs = plt.subplots(
        1, 2, figsize=(12.5, 4.6), dpi=150, gridspec_kw={"width_ratios": [1, 1.25]}
    )
    ax = axs[0]
    lim = [min(P.err_A.min(), P.err_B.min()) - 3, max(P.err_A.max(), P.err_B.max()) + 3]
    ax.plot(lim, lim, color=INK, lw=1, ls="--")
    ax.scatter(P.err_A, P.err_B, s=6, alpha=0.4, lw=0, color=COL[SELECTED])
    _style(
        ax,
        "E5d: the level error is shared within a pair",
        "import error, member A (MW)",
        "import error, member B (MW)",
    )
    ax = axs[1]
    types_ = ["pv", "battery", "load"]
    models = [m for m in PAIR_RUNS if m in COL]
    w = 0.8 / (2 * len(models))
    for i, m in enumerate(models):
        d = T[T.model == m].set_index("probe_type").reindex(types_)
        x = np.arange(3)
        ax.bar(
            x + (2 * i - len(models) + 0.5) * w,
            d.level_mae_member_A_mw,
            width=w * 0.9,
            color=COL[m],
            alpha=0.35,
            label=f"{m}: absolute error",
        )
        ax.bar(
            x + (2 * i - len(models) + 1.5) * w,
            d.delta_err_mae_mw,
            width=w * 0.9,
            color=COL[m],
            label=f"{m}: error of the change",
        )
    ax.set_yscale("log")
    ax.set_xticks(np.arange(3), types_)
    ax.set_ylim(0.02, 2000)
    ax.legend(frameon=False, fontsize=7.5, ncol=2, loc="upper center")
    _style(
        ax,
        "Absolute error vs error of the change (held-out test pairs)",
        "perturbed element",
        "MAE (MW, log)",
    )
    fig.tight_layout()
    fig.savefig(FIG / "e6_pair_cancellation.png", facecolor="white")
    plt.close(fig)


def slack_vm(S: pd.DataFrame) -> dict:
    """Slack Vm is masked by graphkit's PF mask (an output, not an input). How well is it
    inferred, how is it tied to load in the synthetic envelope, and what does it add to the
    explanation of the import error beyond the AC import level?"""
    b = pd.read_parquet(
        E5C_TEST[SELECTED] / "sundon_33kv_predictions.parquet",
        columns=["scenario", "REF", "Vm_pred", "Vm_target"],
    )
    r = b[b.REF == 1].set_index("scenario").reindex(S.index)

    def r2(cols: list[str]) -> float:
        A = np.c_[np.ones(len(S)), S[cols].to_numpy()]
        c, *_ = np.linalg.lstsq(A, S.err.to_numpy(), rcond=None)
        return float(1 - ((S.err - A @ c) ** 2).sum() / ((S.err - S.err.mean()) ** 2).sum())

    return {
        "masked_in_graphkit_pf_mask": True,
        "corr_pred_true": float(np.corrcoef(r.Vm_pred, r.Vm_target)[0, 1]),
        "mae_pu": float((r.Vm_pred - r.Vm_target).abs().mean()),
        "sd_pred_pu": float(r.Vm_pred.std()),
        "sd_true_pu": float(r.Vm_target.std()),
        "corr_vm_ref_load": float(np.corrcoef(S.vm_ref, S.load)[0, 1]),
        "r2_err_on_ac_import": r2(["ac_import"]),
        "r2_err_on_ac_import_and_vm_ref": r2(["ac_import", "vm_ref"]),
    }


def solver_runtime() -> dict:
    m = pd.read_parquet(
        I / "e5d/pairs/test/pairs.parquet", columns=["pp_runtime_s", "pm_runtime_s"]
    )
    return {
        "pandapower_ac_median_s": float(m.pp_runtime_s.median()),
        "powermodels_ac_median_s": float(m.pm_runtime_s.median()),
    }


# ----------------------------------------------------------------- main
def run_all(skip_trace: bool = False) -> dict:
    for d in (TAB, FIG, OUT):
        d.mkdir(parents=True, exist_ok=True)
    res: dict = {"populations": {}, "inputs": {}}
    C = {k: states(v) for k, v in E5C_TEST.items()}
    B = {k: states(v) for k, v in E5B_TEST.items()}
    for k, v in {**E5C_TEST, **{f"[E5b test] {k}": v for k, v in E5B_TEST.items()}}.items():
        res["inputs"][k] = {
            f: sha(v / f)
            for f in ("sundon_33kv_predictions.parquet", "sundon_33kv_branch_predictions.parquet")
        }
    # same populations within each comparison
    for name, P in (("e5c_test", C), ("e5b_test", B)):
        ref = next(iter(P.values()))[0].ac_import
        for k, (S, _) in P.items():
            assert np.allclose(S.ac_import.reindex(ref.index), ref, atol=1e-3), (name, k)
    rows = []
    for name, P in (("E5c held-out synthetic test", C), ("E5b held-out synthetic test", B)):
        for k, (S, _) in P.items():
            rows.append({"population": name, "model": k, **summary(S)})
    comp = pd.DataFrame(rows)
    comp.to_csv(TAB / "e6_model_comparison.csv", index=False)

    Sd, Rd = C[SELECTED]
    dr = drivers(Sd)
    dr.to_csv(TAB / "e6_import_residual_drivers.csv", index=False)
    st = strata(Sd, float(Sd.err.mean()))
    st.to_csv(TAB / "e6_import_by_stratum.csv", index=False)
    pb = per_bus(Rd, Sd.err)
    pb.to_csv(TAB / "e6_residual_by_bus.csv", index=False)
    cov = train_coverage()
    phys = physical_baselines(Sd, cov["train_loss_mean_mw"])
    phys.to_csv(TAB / "e6_physical_baselines.csv", index=False)
    sens = ref_branch_sensitivity(E5C_TEST[SELECTED])
    sens.to_csv(TAB / "e6_ref_branch_sensitivity.csv", index=False)
    lb = {k: lbuz_injection(R, S) for k, (S, R) in B.items()}
    lb.update({f"[E5c test] {k}": lbuz_injection(R, S) for k, (S, R) in C.items() if k in COL})
    test_cov = {
        "share_export_lt_minus5": float((Sd.ac_import < -SIGN_MW).mean()),
        "share_near_zero_abs_lt5": float((Sd.ac_import.abs() < SIGN_MW).mean()),
    }
    res.update(
        selected=SELECTED,
        train_coverage=cov,
        test_coverage=test_cov,
        lbuz_mismatch_vs_generation=lb,
        normalizer=normalizer_audit(),
        slack_vm_range_test=[float(Sd.vm_ref.min()), float(Sd.vm_ref.max())],
    )
    if not skip_trace:
        tr, checks = trace(Sd)
        tr.to_csv(TAB / "e6_trace_examples.csv", index=False)
        res["trace_checks"] = checks
    pc, pts = pair_cancellation()
    pc.to_csv(TAB / "e6_pair_level_cancellation.csv", index=False)
    fig_pairs(pts, pc)
    # small public extracts (synthetic only) so the submission figure rebuilds from published files
    pts[pts.probe_type == "pv"].round(6).to_csv(TAB / "e6_pv_pairs_e5d.csv", index=False)
    Sd[["ac_import", "pred_import", "err", "net_demand", "gen"]].round(6).rename_axis(
        "scenario"
    ).to_csv(TAB / "e6_import_states_e5d.csv")
    res["graph_reach"] = graph_reach()
    res["slack_vm"] = slack_vm(Sd)
    res["solver_runtime"] = solver_runtime()
    ex = exploratory_real()
    ex.to_csv(TAB / "e6_exploratory_real_s1.csv", index=False)
    fig_residuals(Sd, C["E5c (frozen)"][0])
    fig_identity(Sd, pb)
    fig_regimes({k: S for k, (S, _) in B.items()})
    res["integrity"] = {
        "note": "frozen artefacts read only; synthetic populations; S1 exploratory only"
    }
    (OUT / "diagnostic.json").write_text(json.dumps(res, indent=2, default=float))
    print(
        json.dumps(
            {
                k: res[k]
                for k in ("train_coverage", "test_coverage", "trace_checks", "normalizer")
                if k in res
            },
            indent=1,
            default=float,
        )
    )
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["all"])
    ap.add_argument("--skip-trace", action="store_true")
    a = ap.parse_args()
    run_all(a.skip_trace)
    return 0


if __name__ == "__main__":
    sys.exit(main())
