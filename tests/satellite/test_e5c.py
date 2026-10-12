"""E5c tests: explicit generator representation, exact-zero generation, static metadata only, no
real-data leakage, paired probes (one input changes, AC targets), sensitivity metrics, near-zero
import-sign handling, robustness-aware selection, normalizer provenance, freeze-before-real and
real-population identity. Integration tests skip when (gitignored) data are absent.
"""

import importlib.util
import inspect
import json

import numpy as np
import pandas as pd
import pytest
import yaml

from cloud2grid.genco import adaptation_e5c as ad
from cloud2grid.genco.generator_aware import reencode
from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.scenarios import envelope_e5c as ev

OUT = REPO_ROOT / "reports/experiments/e5c"
REGISTRY = REPO_ROOT / "metadata/e5c_checkpoint_registry.yaml"
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
)


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tables():
    bus = pd.DataFrame(
        {
            "scenario": [0] * 3,
            "load_scenario_idx": 0,
            "bus": [0, 8, 22],
            "Pd": [5.0, -1.2, 0.0],
            "Qd": [1.0, 0.0, 0.0],
            "Pg": [0, 0, 3.8],
            "Qg": [0, 0, 1.0],
            "Pg_dc": [0, 0, 3.8],
        }
    )
    gen = pd.DataFrame(
        {
            "scenario": [0],
            "load_scenario_idx": 0,
            "idx": [0],
            "bus": [22],
            "p_mw": [3.8],
            "q_mvar": [1.0],
            "min_p_mw": -270,
            "max_p_mw": 270,
            "min_q_mvar": -270,
            "max_q_mvar": 270,
            "cp0_eur": 0,
            "cp1_eur_per_mw": 0,
            "cp2_eur_per_mw2": 0,
            "in_service": 1,
            "is_slack_gen": 1,
            "p_mw_dc": 3.8,
        }
    )
    return bus, gen


# ------------------------------------------------------------------ representation
def test_reencode_makes_explicit_generator_and_preserves_physics():
    bus, gen = _tables()
    b, g = reencode(bus, gen, [8], {8: 2.5})
    assert len(g) == 2 and g.iloc[1].bus == 8 and g.iloc[1].p_mw == pytest.approx(1.2)
    assert g.iloc[1].is_slack_gen == 0 and g.iloc[1].in_service == 1
    row = b[b.bus == 8].iloc[0]
    assert row.Pd == 0 and row.Pg == pytest.approx(1.2)
    np.testing.assert_allclose((b.Pg - b.Pd).to_numpy(), (bus.Pg - bus.Pd).to_numpy())


def test_reencode_refuses_load_at_generation_bus():
    bus, gen = _tables()
    bus.loc[bus.bus == 8, "Pd"] = 0.4
    with pytest.raises(ValueError, match="positive demand"):
        reencode(bus, gen, [8], {8: 2.5})


def test_zero_output_generator_still_explicit():
    bus, gen = _tables()
    bus.loc[bus.bus == 8, "Pd"] = 0.0
    _, g = reencode(bus, gen, [8], {8: 2.5})
    assert (g.bus == 8).sum() == 1 and g[g.bus == 8].p_mw.iat[0] == 0.0


# ------------------------------------------------------------------ sampling / static only
def test_exact_zero_and_full_generation_mass():
    s = ev.E5cLoadGenerator().sample(40000, 11)
    zero, full = (s.generation_mw == 0).mean(), (s.generation_mw == 7.5).mean()
    assert zero == pytest.approx(0.25**2, abs=0.01)
    assert full == pytest.approx(0.15**2, abs=0.005)
    assert s.generation_mw.between(0, 7.5).all()
    assert (s.solar_level == 0).mean() == pytest.approx(0.25, abs=0.01)


def test_sampler_static_sources_only():
    ev.SOURCES_READ.clear()
    ev.E5cLoadGenerator().sample(10, 1)
    assert ev.SOURCES_READ <= ev.ALLOWED_SOURCES
    for mod in (ev, ev.e5b):
        src = inspect.getsource(mod)
        for tok in FORBIDDEN:
            assert tok not in src, (mod.__name__, tok)


def test_bidirectional_battery_and_broad_load_retained():
    s = ev.E5cLoadGenerator().sample(20000, 5)
    b = s["P:EPN:CHAP31"]
    assert b.min() < -40 and b.max() > 40 and (b.abs() < 1).mean() > 0.15
    tot = s[[c for c in s if c.startswith("P:EPN:") and "LBUZ3" not in c and "CHAP" not in c]].sum(
        1
    )
    assert tot.min() < 5 and tot.max() > 90


# ------------------------------------------------------------------ probes
def test_probe_pairs_change_exactly_one_input():
    base = ev.E5cLoadGenerator().sample(40, 9500)
    p = ev.probe_pairs(base, 9500)
    cols = [c for c in p if c.startswith(("P:", "Q:"))]
    gen_nodes = [f"P:{n}" for n in ad.CFG["representation"]["gen_buses"].values()]
    for _pid, g in p.groupby("probe_id"):
        a, b = g[g.member == "A"].iloc[0], g[g.member == "B"].iloc[0]
        changed = {c for c in cols if abs(a[c] - b[c]) > 1e-12}
        kind = a.probe_type
        if kind == "pv":
            assert changed <= set(gen_nodes) and changed
            assert a.x_mw == pytest.approx(sum(b[c] - a[c] for c in gen_nodes))
        elif kind == "battery":
            assert changed == {"P:EPN:CHAP31"}
            assert abs(a.x_mw) >= 5 - 1e-9
        else:
            node = a.node
            assert changed <= {f"P:{node}", f"Q:{node}"} and f"P:{node}" in changed
        assert 0 <= -sum(b[c] for c in gen_nodes) <= 7.5 + 1e-9


def test_probe_metrics_use_ac_targets_not_unit_slopes(tmp_path, monkeypatch):
    evc = _script("evaluate_e5c")
    man = pd.DataFrame(
        {
            "scenario": [0, 1],
            "probe_id": "pv_0",
            "probe_type": "pv",
            "member": ["A", "B"],
            "x_mw": -2.0,
            "complete": True,
        }
    )
    root = tmp_path / "probes"
    root.mkdir()
    man.to_parquet(root / "probes.parquet")
    pred = tmp_path / "pred"
    pred.mkdir()
    bus = pd.DataFrame(
        {
            "scenario": [0, 0, 1, 1],
            "bus": [0, 1, 0, 1],
            "PQ": [0, 1, 0, 1],
            "REF": [1, 0, 1, 0],
            "Vm_pred": 1.0,
            "Vm_target": 1.0,
            "Va_pred": 0.0,
            "Va_target": 0.0,
            "Pg_target": [10.0, 0, 8.04, 0],
            "Pg_pred": [10.0, 0, 10.0, 0],
        }
    )
    br = pd.DataFrame(
        {
            "scenario": [0, 1],
            "from_bus": 0,
            "to_bus": 1,
            "Pft": [1.0, 1.0],
            "Pft_target": [1.0, 3.0],
            "Qft": 0.0,
            "Qft_target": 0.0,
        }
    )
    bus.to_parquet(pred / "sundon_33kv_predictions.parquet")
    br.to_parquet(pred / "sundon_33kv_branch_predictions.parquet")
    monkeypatch.setitem(evc.TARGET_ROOT, "probes_x", root)
    monkeypatch.setattr(evc, "pdir", lambda run, target: pred)
    m = evc.probe_metrics("r", "probes_x")
    assert m["pv_slope_ac"] == pytest.approx(0.98)  # AC: ΔI = −1.96 for x = −2 (losses)
    assert m["pv_slope_genco"] == pytest.approx(0.0)  # a model that ignores PV
    assert m["pv_response_rel_mae"] == pytest.approx(1.0)


# ------------------------------------------------------------------ gates / selection
def _rec(**kw):
    base = {
        "PBE_mean": 0.4,
        "P_residual": 0.3,
        "dc_P_residual": 0.12,
        "import_sign_accuracy_big": 1.0,
        "import_mae_mw": 2.0,
        "V_error": 0.01,
        "e5_test_ga_PBE_mean": 1.0,
        "e5b_test_ga_PBE_mean": 0.5,
    }
    for k in ("pv", "battery", "load"):
        base[f"val_{k}_slope_ratio"], base[f"val_{k}_response_rel_mae"] = 1.0, 0.1
    base.update(kw)
    return base


def test_low_pbe_but_no_generator_response_cannot_pass():
    evc = _script("evaluate_e5c")
    g = evc.gates_for(
        _rec(val_pv_slope_ratio=0.06, val_pv_response_rel_mae=0.95), {"PBE_mean": 48.0}
    )
    assert g["static_pass"] and not g["response_pass"] and not g["eligible"]
    assert evc.gates_for(_rec(), {"PBE_mean": 48.0})["eligible"]


def test_near_zero_import_sign_is_judged_by_error():
    evc = _script("evaluate_e5c")
    assert evc.SIGN_MW == 5.0
    src = inspect.getsource(evc.static_metrics)
    assert "abs() >= SIGN_MW" in src and "import_sign_accuracy_big" in src
    assert "ST4_import_mae" in inspect.getsource(evc.gates_for)


def test_robustness_selection_prefers_stable_size_within_tie():
    evc = _script("evaluate_e5c")
    S = pd.DataFrame(
        {
            "run": [
                "e5c_ft_n10000_s0",
                "e5c_ft_n10000_s1",
                "e5c_ft_n10000_s2",
                "e5c_ft_n50000_s0",
                "e5c_ft_n1000_s0",
            ],
            "n_train": [10000, 10000, 10000, 50000, 1000],
            "synthetic_val_PBE_mean": [0.52, 0.53, 0.54, 0.50, 0.9],
            "eligible": [True, True, True, True, False],
            "n_criteria_passed": [13, 13, 13, 13, 9],
        }
    )
    sel, flagged, _ = evc.select(S)
    assert sel == "e5c_ft_n10000_s0" and not flagged  # 50k best but single-seed; 10k within 10 %
    S["eligible"] = False
    sel, flagged, _ = evc.select(S)
    assert flagged


def test_selection_and_gates_never_read_real_states():
    evc = _script("evaluate_e5c")
    for fn in (evc.cmd_synthetic, evc.select, evc.gates_for, evc.probe_metrics, evc.static_metrics):
        src = inspect.getsource(fn)
        for tok in ("S1_WEATHER", "S2_MATCHED", "E4D", "real_frame", "slot"):
            assert tok not in src, (fn.__name__, tok)


# ------------------------------------------------------------------ isolation / freeze
def test_e5c_seeds_disjoint_from_earlier_experiments():
    seeds = {s for p in ad.POOLS for s in ad.pool_seeds(p)}
    assert not seeds & ad.forbidden_seeds()
    probes = set(ad.CFG["physics_probes"]["seeds"].values())
    assert not probes & seeds


def test_real_states_refused_before_freeze():
    ft = _script("finetune_genco_e5c")
    with pytest.raises(ad.LeakageError, match="hidden"):
        ft.cmd_predict("e5c_ft_n100_s9_unregistered", "S1_WEATHER_ALIGNED_GENAWARE")
    if not REGISTRY.exists():
        b = _script("build_e5c_training_data")
        with pytest.raises(ad.LeakageError, match="hidden"):
            b.cmd_real()


def test_transfer_refuses_without_freeze(monkeypatch, tmp_path):
    evc = _script("evaluate_e5c")
    monkeypatch.setattr(evc, "REGISTRY", tmp_path / "none.yaml")
    with pytest.raises(SystemExit, match="not frozen"):
        evc.frozen()


@pytest.mark.skipif(not (OUT / "runs/e5c_ft_n100_s0.json").exists(), reason="no E5c run yet")
def test_normalizer_provenance():
    from types import SimpleNamespace

    from gridfm_graphkit.datasets.normalizers import HeteroDataMVANormalizer

    rec = json.loads((OUT / "runs/e5c_ft_n100_s0.json").read_text())
    man = pd.read_parquet(ad.ALLOWED_ROOT / "manifest.parquet")
    train = ad.training_subset(ad.pool_ids(man, "train"), rec["n_train"], rec["seed"])
    norm = HeteroDataMVANormalizer(SimpleNamespace(data=SimpleNamespace(baseMVA=100)))
    stats = norm.fit(str(ad.ALLOWED_ROOT / ad.NETWORK / "raw"), train)
    assert float(stats["baseMVA"]) == pytest.approx(rec["normalizer"]["baseMVA"], rel=1e-6)


@pytest.mark.skipif(not REGISTRY.exists(), reason="E5c not frozen")
def test_registry_hashes():
    reg = yaml.safe_load(REGISTRY.read_text())
    c = reg["checkpoints"][reg["selected"]]
    for k in ("checkpoint", "normalizer"):
        assert ad.sha256_file(REPO_ROOT / c[k]["path"]) == c[k]["sha256"]


@pytest.mark.skipif(not (OUT / "real_transfer.json").exists(), reason="transfer not evaluated")
def test_real_population_identical_e4_e5_e5b_e5c():
    e4 = pd.read_parquet(REPO_ROOT / "reports/tables/e4_scenario_metrics.parquet")
    a = sorted(e4[e4.scenario_family == "S1_WEATHER_ALIGNED"].scenario_id)
    evc = _script("evaluate_e5c")
    reg = yaml.safe_load(REGISTRY.read_text())
    m, _, _ = evc.real_frame(
        evc.pdir(reg["selected"], "S1_WEATHER_ALIGNED_GENAWARE"),
        ad.WORK / "datasets/S1_WEATHER_ALIGNED_GENAWARE",
    )
    assert sorted(m.scenario_id) == a
    src = pd.read_parquet(
        ad.WORK / "datasets/S1_WEATHER_ALIGNED_GENAWARE" / ad.NETWORK / "scenario_map.parquet"
    )
    assert (src.scenario == src.source_scenario).all()
