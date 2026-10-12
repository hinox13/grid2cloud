"""E5d tests: response-aware training. No real / weather leakage, paired-state isolation (one
input changes), AC-derived response targets, scale-normalised response loss, train / validation /
test base-state separation, synthetic-only λ / κ / σ, absolute + response gate logic,
freeze-before-real, identical real population, demo untouched. Integration tests skip when the
(gitignored) data are absent.
"""

import importlib.util
import inspect
import json

import numpy as np
import pandas as pd
import pytest
import torch
import yaml

from cloud2grid.genco import adaptation_e5d as ad
from cloud2grid.genco import response_loss as rl
from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.scenarios import response_pairs_e5d as rp

OUT = REPO_ROOT / "reports/experiments/e5d"
REGISTRY = REPO_ROOT / "metadata/e5d_checkpoint_registry.yaml"
FORBIDDEN = (
    "op_33kv",
    "measurements",
    "load_series",
    "pv_by_asset",
    "S1_WEATHER",
    "S2_MATCHED",
    "E4D_TIMELINE",
    "lsasaf",
    "e3_candidate",
    "nodal_demand",
    "StateBuilder",
    "hero",
)
HAVE_PAIRS = all((ad.PAIR_ROOT[s] / "pairs.parquet").exists() for s in ad.PAIR_SETS)


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ leakage
def test_pair_sampler_static_sources_only():
    rp.SOURCES_READ.clear()
    rp.response_pairs(rp.base_states(5, 1), 1, "unit")
    assert rp.SOURCES_READ <= rp.ALLOWED_SOURCES
    import cloud2grid.genco.response_loss as m1
    import cloud2grid.genco.response_task as m2

    for mod in (rp, m1, m2):
        src = inspect.getsource(mod)
        for tok in FORBIDDEN:
            assert tok not in src, (mod.__name__, tok)


def test_training_reads_only_synthetic_roots():
    tr = _script("train_e5d")
    src = inspect.getsource(tr.cmd_train) + inspect.getsource(tr.graphkit_config)
    for tok in ("S1_WEATHER", "REAL_TARGETS", "e4/datasets", "E4D", "S2_MATCHED"):
        assert tok not in src, tok
    with pytest.raises(ad.LeakageError):
        ad.assert_pair_set(REPO_ROOT / "data/interim/e4/datasets/S1_WEATHER_ALIGNED")


# ------------------------------------------------------------------ pairs
def test_pairs_change_exactly_one_input_and_x_matches():
    base = rp.base_states(60, 3)
    pairs = rp.response_pairs(base, 3, "unit")
    changed = rp.changed_elements(pairs)
    a = pairs[pairs.member == "A"].set_index("probe_id")
    b = pairs[pairs.member == "B"].set_index("probe_id").reindex(a.index)
    gen = [c for c in rp.injection_columns(pairs) if c.startswith("P:EPN:LBUZ3")]
    for pid, cols in changed.items():
        k = a.loc[pid, "probe_type"]
        if k == "pv":
            assert cols and set(cols) <= set(gen)
            x = b.loc[pid, gen].sum() - a.loc[pid, gen].sum()  # net withdrawal = +P column
        elif k == "battery":
            assert cols == ["P:EPN:CHAP31"]
            x = b.loc[pid, cols[0]] - a.loc[pid, cols[0]]
        else:
            nodes = {c[2:] for c in cols}
            assert len(nodes) == 1 and f"P:{a.loc[pid, 'node']}" in cols
            x = b.loc[pid, f"P:{a.loc[pid, 'node']}"] - a.loc[pid, f"P:{a.loc[pid, 'node']}"]
        assert a.loc[pid, "x_mw"] == pytest.approx(x, abs=1e-9)
        assert abs(x) > 0


def test_pair_magnitudes_classes_bounds_and_zero_transitions():
    pairs = rp.response_pairs(rp.base_states(600, 11), 11, "unit")
    a = pairs[pairs.member == "A"]
    mags = ad.CFG["response_pairs"]["magnitudes"]
    for k in ("pv", "battery"):
        for cls, spec in mags[k]["classes"].items():
            if "abs_delta_mw" not in spec:
                continue
            x = a[(a.probe_type == k) & (a.magnitude_class == cls)].x_mw.abs()
            lo, hi = spec["abs_delta_mw"]
            assert len(x) and (x <= hi + 1e-9).all()
            assert (x >= lo - 1e-9).mean() > 0.9  # only bound-clipped pairs fall below
    gen = [c for c in rp.injection_columns(pairs) if c.startswith("P:EPN:LBUZ3")]
    g = -pairs[pairs.probe_type == "pv"].groupby(["probe_id", "member"])[gen].sum().sum(axis=1)
    g = g.unstack()
    assert ((g >= -1e-9) & (g <= 7.5 + 1e-9)).all().all()
    assert ((g.A == 0) != (g.B == 0)).sum() > 10  # exact zero ↔ non-zero transitions
    for k in rp.TYPES:
        assert set(a[a.probe_type == k].magnitude_class) >= {"small", "moderate", "large"}
        d = np.sign(a[a.probe_type == k].x_mw)
        assert (d > 0).any() and (d < 0).any()


@pytest.mark.skipif(not HAVE_PAIRS, reason="E5d pair sets not built")
def test_response_targets_are_ac_solutions():
    """Pair members are separately AC-solved states; their raw REF import changes by ≈ x."""
    man = ad.assert_pair_set(ad.PAIR_ROOT["validation"])
    p = ad.complete_pairs(man)
    bus = pd.read_parquet(
        ad.PAIR_ROOT["validation"] / ad.NETWORK / "raw/bus_data.parquet",
        columns=["scenario", "bus", "Pg", "REF", "Vm"],
    )
    ref = bus[bus.REF == 1].set_index("scenario").Pg
    di = ref.reindex(p.scenario_b).to_numpy() - ref.reindex(p.scenario_a).to_numpy()
    s = (di * p.x_mw).sum() / (p.x_mw**2).sum()
    assert 0.9 < s < 1.2  # physical (losses), not assumed ±1
    vm = bus.pivot(index="scenario", columns="bus", values="Vm")
    assert (vm.loc[p.scenario_a].to_numpy() != vm.loc[p.scenario_b].to_numpy()).any(axis=1).all()


# ------------------------------------------------------------------ loss
def _toy(n: int = 30, seed: int = 0):
    g = torch.Generator().manual_seed(seed)
    types = [rl.TYPES[i % 3] for i in range(n)]
    x = (torch.rand(n, generator=g) + 0.05) * torch.tensor(
        [1.0 if t != "battery" else 10.0 for t in types]
    )
    sens = {"import": 1.0, "branch_P": 0.3, "branch_Q": 0.05, "Vm": 1e-3, "Va": 1e-2}
    d_ac = {
        o: x[:, None] * s * (1 + 0.1 * torch.randn(n, 4 if o != "import" else 1, generator=g))
        for o, s in sens.items()
    }
    return types, x.double(), {o: v.double() for o, v in d_ac.items()}


def test_response_loss_blind_model_has_unit_rms_and_perfect_is_zero():
    types, x, d_ac = _toy()
    acc: dict = {}
    rl.sigma_accumulate(acc, d_ac, x, types)
    sig = rl.sigma_finalise(acc)
    zero = {o: torch.zeros_like(v) for o, v in d_ac.items()}
    r = rl.residuals(zero, d_ac, x, types, sig)
    for k in rl.TYPES:
        sel = torch.tensor([t == k for t in types])
        for o in rl.FAMILIES:
            assert float((r[o][sel] ** 2).mean()) == pytest.approx(1.0, rel=1e-9)
    assert float(rl.response_loss(d_ac, d_ac, x, types, sig)) == 0.0
    assert float(rl.response_loss(zero, d_ac, x, types, sig)) > 0.5


def test_response_loss_is_per_mw_and_scale_free():
    """Small perturbations are not numerically ignored: a model that misses the same fraction of
    a 0.05 MW and of a 5 MW response pays the same loss."""
    types, x, d_ac = _toy()
    acc: dict = {}
    rl.sigma_accumulate(acc, d_ac, x, types)
    sig = rl.sigma_finalise(acc)
    half = {o: 0.5 * v for o, v in d_ac.items()}
    base = float(rl.response_loss(half, d_ac, x, types, sig))
    for c in (0.01, 100.0):
        sc = {o: c * v for o, v in d_ac.items()}
        sh = {o: c * v for o, v in half.items()}
        assert float(rl.response_loss(sh, sc, c * x, types, sig)) == pytest.approx(base, rel=1e-9)


def test_response_loss_balances_types_and_families():
    """Duplicating pv pairs does not change pv's weight; every family counts equally."""
    types, x, d_ac = _toy(30)
    acc: dict = {}
    rl.sigma_accumulate(acc, d_ac, x, types)
    sig = rl.sigma_finalise(acc)
    pred = {o: 0.7 * v for o, v in d_ac.items()}
    l1 = float(rl.response_loss(pred, d_ac, x, types, sig))
    pv = torch.tensor([t == "pv" for t in types])
    t2 = types + [t for t in types if t == "pv"]
    x2 = torch.cat([x, x[pv]])
    d2 = {o: torch.cat([v, v[pv]]) for o, v in d_ac.items()}
    p2 = {o: torch.cat([v, v[pv]]) for o, v in pred.items()}
    assert float(rl.response_loss(p2, d2, x2, t2, sig)) == pytest.approx(l1, rel=1e-9)
    assert float(rl.huber(torch.tensor(1.0), 0.1)) == pytest.approx(0.95)
    assert float(rl.huber(torch.tensor(0.05), 0.1)) == pytest.approx(0.0125)


def test_kappa_and_lambda_are_preregistered_synthetic_quantities():
    k = ad.CFG["response_loss"]["kappa"]
    runs = [
        json.loads(
            (REPO_ROOT / f"reports/experiments/e5c/runs/e5c_ft_n10000_s{s}.json").read_text()
        )
        for s in range(3)
    ]
    l_orig = float(np.mean([r["best_validation_loss"] for r in runs]))  # synthetic validation
    assert l_orig == pytest.approx(k["L_orig_E5c"], rel=1e-12)
    assert pytest.approx(l_orig / float(rl.huber(torch.tensor(0.25), 0.1)), rel=1e-6) == ad.KAPPA
    assert sorted(lam for lam, _, _ in ad.runs_spec()) == [0.0, 0.3, 1.0, 1.0, 1.0, 3.0]
    tr = _script("train_e5d")
    c = yaml.safe_load(tr.graphkit_config(1.0, 0, "unit_test_cfg", ad.e5c_split_dir(0)).read_text())
    (ad.WORK / "configs/unit_test_cfg.yaml").unlink()
    assert c["response"]["train_pairs"].endswith("pairs/train")  # σ from TRAINING pairs only
    assert c["response"]["val_pairs"].endswith("pairs/validation")
    assert "test" not in json.dumps(c["response"])
    assert c["callbacks"]["checkpoint_monitor"] == "Validation total loss"
    task_src = inspect.getsource(_task_module().PowerFlowResponseTask.on_fit_start)
    assert "self.train_root" in task_src and "sigma_accumulate" in task_src


def _task_module():
    import cloud2grid.genco.response_task as rt

    return rt


# ------------------------------------------------------------------ separation
@pytest.mark.skipif(not (OUT / "splits.json").exists(), reason="prepare not run")
def test_train_validation_test_base_states_disjoint():
    s = json.loads((OUT / "splits.json").read_text())
    assert s["base_overlap"] and not any(s["base_overlap"].values())
    assert s["n_base"]["train"] == 3000 and s["n_base"]["validation"] == 500
    assert any(k.startswith("e5c_probes") for k in s["n_base"])


def test_absolute_splits_are_e5c_n10000():
    for seed in (0, 1, 2):
        if not ad.e5c_split_dir(seed).exists():
            pytest.skip("E5c split files absent")
        ad.assert_e5c_splits(seed)


def test_sampler_seeds_disjoint_from_e5c():
    from cloud2grid.genco import adaptation_e5c as e5c

    seeds = {int(v["sampler_seed"]) for v in ad.CFG["response_pairs"]["sets"].values()}
    assert len(seeds) == 3
    assert not seeds & set(e5c.CFG["physics_probes"]["seeds"].values())
    assert not seeds & {s for p in e5c.POOLS for s in e5c.pool_seeds(p, 100 if p == "train" else 0)}


# ------------------------------------------------------------------ gates / selection
def _rec(**kw):
    r = {
        "PBE_mean": 0.6,
        "P_residual": 0.5,
        "dc_P_residual": 0.13,
        "import_sign_accuracy_big": 0.995,
        "import_mae_mw": 3.0,
        "V_error": 0.01,
        "e5_test_ga_PBE_mean": 1.2,
        "e5b_test_ga_PBE_mean": 0.6,
    }
    for k in rl.TYPES:
        r |= {
            f"val_{k}_slope_ratio": 1.0,
            f"val_{k}_import_rel_mae": 0.1,
            f"val_{k}_branch_P_rel_err": 0.2,
            f"val_{k}_Vm_rel_err": 0.3,
            f"val_{k}_Va_rel_err": 0.2,
        }
    return r | kw


def test_gate_requires_absolute_and_response_accuracy():
    ev = _script("evaluate_e5d")
    zs = {"PBE_mean": 49.0}
    good = ev.gates_for(_rec(), zs)
    assert good["eligible"] and good["n_criteria_passed"] == 23
    blind = ev.gates_for(_rec(val_pv_slope_ratio=0.01, val_pv_import_rel_mae=0.99), zs)
    assert blind["static_pass"] and not blind["pv_response_pass"] and not blind["eligible"]
    sloppy = ev.gates_for(_rec(PBE_mean=2.0, import_mae_mw=13.0), zs)
    assert sloppy["response_pass"] and not sloppy["static_pass"] and not sloppy["eligible"]
    flows = ev.gates_for(_rec(val_load_branch_P_rel_err=3.0), zs)
    assert not flows["battery_load_response_pass"] and not flows["eligible"]


def test_selection_rule_and_fallback():
    ev = _script("evaluate_e5d")
    S = pd.DataFrame(
        {
            "run": ["e5d_l1_s0", "e5d_l1_s1", "e5d_l1_s2", "e5d_l0.3_s0", "e5d_l3_s0", "e5d_l0_s0"],
            "lambda": [1.0, 1.0, 1.0, 0.3, 3.0, 0.0],
            "synthetic_val_PBE_mean": [0.62, 0.63, 0.64, 0.58, 0.9, 0.5],
            "eligible": [True, True, True, True, False, True],
            "static_pass": True,
            "pv_response_pass": [True, True, True, True, False, False],
            "battery_load_response_pass": True,
            "retention_pass": True,
            "n_criteria_passed": [23, 23, 23, 23, 18, 15],
        }
    )
    sel, flagged, _ = ev.select(S)
    assert sel == "e5d_l1_s0" and not flagged  # λ=0.3 best but single-seed; λ=1 within 10 %
    S["eligible"] = False
    sel, flagged, why = ev.select(S)
    assert flagged and sel == "e5d_l0.3_s0" and "e5d_l0_s0" not in why["fallback_rank"]


def test_verdict_logic():
    ev = _script("evaluate_e5d")
    ok = dict.fromkeys(
        [
            "R1_active",
            "R2_pbe",
            "R3_import",
            "R4_voltage",
            "R5_pv_response",
            "R6_battery_no_regression",
            "R7_load_no_regression",
        ],
        True,
    )
    assert ev.verdict(ok, False, True).startswith("E5D-A")
    assert ev.verdict(ok, True, True).startswith("E5D-D")
    assert ev.verdict(ok | {"R5_pv_response": False}, False, True).startswith("E5D-B")
    assert ev.verdict(ok | {"R5_pv_response": False}, False, False).startswith("E5D-C")
    assert ev.verdict(ok | {"R3_import": False}, False, True).startswith("E5D-D")


def test_selection_and_gates_never_read_real_states():
    ev = _script("evaluate_e5d")
    for fn in (ev.cmd_synthetic, ev.select, ev.gates_for, ev.response_table, ev.pair_elements):
        src = inspect.getsource(fn)
        for tok in ("S1_WEATHER", "S2_MATCHED", "E4D", "real_frame", "slot"):
            assert tok not in src, (fn.__name__, tok)


# ------------------------------------------------------------------ freeze / real
def test_real_states_refused_before_freeze(monkeypatch, tmp_path):
    tr = _script("train_e5d")
    monkeypatch.setattr(tr, "REGISTRY", tmp_path / "none.yaml")
    with pytest.raises(ad.LeakageError, match="hidden"):
        tr.cmd_predict("e5d_l1_s0", "S1_WEATHER_ALIGNED_GENAWARE")
    ev = _script("evaluate_e5d")
    monkeypatch.setattr(ev, "REGISTRY", tmp_path / "none.yaml")
    with pytest.raises(SystemExit, match="not frozen"):
        ev.frozen()


@pytest.mark.skipif(not REGISTRY.exists(), reason="E5d not frozen")
def test_registry_hashes():
    reg = yaml.safe_load(REGISTRY.read_text())
    assert reg["frozen"] and reg["frozen_before_real_state_evaluation"]
    c = reg["checkpoints"][reg["selected"]]
    for k in ("checkpoint", "normalizer"):
        assert ad.sha256_file(REPO_ROOT / c[k]["path"]) == c[k]["sha256"]


@pytest.mark.skipif(not (OUT / "real_transfer.json").exists(), reason="transfer not evaluated")
def test_real_population_identical_to_e4_e5c():
    e4 = pd.read_parquet(REPO_ROOT / "reports/tables/e4_scenario_metrics.parquet")
    a = sorted(e4[e4.scenario_family == "S1_WEATHER_ALIGNED"].scenario_id)
    ev = _script("evaluate_e5d")
    reg = yaml.safe_load(REGISTRY.read_text())
    m, _, _ = ev.ev5c.real_frame(
        ad.WORK / "predictions" / reg["selected"] / "S1_WEATHER_ALIGNED_GENAWARE",
        ad.E5C_WORK / "datasets/S1_WEATHER_ALIGNED_GENAWARE",
    )
    assert sorted(m.scenario_id) == a and len(a) == 2829


# ------------------------------------------------------------------ demo
def test_demo_e5d_entry_is_frozen_partial_and_needs_no_new_inference():
    """E5d entered the Explorer only after its verdict, as an optional model (submission cycle):
    it must be the frozen checkpoint replayed from its frozen real-transfer predictions, be
    labelled partial, and no E5d weather / ramp / timeline prediction may exist (STOP rule)."""
    models = {m["id"]: m for m in json.loads((REPO_ROOT / "data/demo/models.json").read_text())}
    if "E5d" not in models:
        return  # the demo works without E5d (generic model list)
    rt = json.loads((OUT / "real_transfer.json").read_text())
    reg = yaml.safe_load(REGISTRY.read_text())
    m = models["E5d"]
    assert m["selected_run"] == reg["selected"] == rt["selected"]
    assert m["checkpoint_sha256"] == reg["checkpoints"][reg["selected"]]["checkpoint"]["sha256"]
    assert m["predictions"].endswith(f"{reg['selected']}/S1_WEATHER_ALIGNED_GENAWARE")
    assert m["selection_flagged"] and "E5D-D" in m["finding"] and "partial" in m["finding"]
    assert rt["verdict"].startswith("E5D-D")
    preds = ad.WORK / "predictions"
    if preds.exists():
        for t in preds.glob("e5d_*/*"):
            assert not any(
                k in t.name for k in ("S2_MATCHED", "E4D_TIMELINE", "S1_WEATHER_ALIGNED_BASE")
            ), t
