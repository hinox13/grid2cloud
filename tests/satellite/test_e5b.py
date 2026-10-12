"""E5b tests: static-metadata-only envelope (no real-state leakage), bidirectional CHAP31 and
generation/export sampling, low-load coverage, real states hidden before freeze, synthetic-only
selection, deterministic subsets / normalizer provenance, E4/E5/E5b population identity, frozen
donors and ramp absolute-error metrics. Integration tests skip when (gitignored) data are absent.
"""

import importlib.util
import inspect
import json

import numpy as np
import pandas as pd
import pytest
import yaml

from cloud2grid.evaluation import transitions as tr
from cloud2grid.genco import adaptation_e5b as ad
from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.scenarios import envelope as ev

ENV = yaml.safe_load((REPO_ROOT / "configs/experiments/e5b_operating_envelope.yaml").read_text())
OUT = REPO_ROOT / "reports/experiments/e5b"
REGISTRY = REPO_ROOT / "metadata/e5b_checkpoint_registry.yaml"
FORBIDDEN_TOKENS = (
    "op_33kv",
    "measurements",
    "load_series",
    "satellite",
    "pv_by_asset",
    "S1_WEATHER",
    "S2_MATCHED",
    "E4D_TIMELINE",
    "lsasaf",
    "e3_candidate",
    "nodal_demand",
    "observed_import",
    "StateBuilder",
)


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def env():
    ev.SOURCES_READ.clear()
    return ev.build_envelope()


# --------------------------------------------------------------------- static-only envelope
def test_envelope_reads_static_sources_only(env):
    assert ev.SOURCES_READ <= ev.ALLOWED_SOURCES
    assert not any("ukpn/op_" in s or "measurement" in s for s in ev.SOURCES_READ)


def test_envelope_code_has_no_real_state_access():
    src = inspect.getsource(ev)
    for tok in FORBIDDEN_TOKENS:
        assert tok not in src, tok
    with pytest.raises(PermissionError):
        ev._read("data/raw/ukpn/op_33kv_monthly.parquet")


def test_bounds_come_from_ltds_and_ecr(env):
    s = env["sites"]
    assert s.loc["CHAU", "winter_md_mw"] == 31.3 and s.loc["LEWS", "winter_md_mw"] == 15.5
    assert s.loc["SUPR", "lambda_lo"] == pytest.approx(-0.098)  # LTDS publishes −9.8 % (T1&T2)
    assert (s.lambda_lo <= 0).all()  # every site reaches near-zero
    assert env["hv_capacity_mw"] == ENV["hv_generation"]["expected"]
    assert env["storage"]["registered_capacity_mw"] == ENV["storage"]["bound_mw"] == 49.5
    el = env["elements"]
    assert {"element", "node", "role", "min_mw", "max_mw", "sign", "source", "sampling"} <= set(el)
    assert el["source"].str.len().gt(10).all()


def test_bidirectional_chap31_and_generation_export(env):
    s = ev.EnvelopeLoadGenerator().sample(20000, 3)
    b = s[f"P:{ENV['storage']['node']}"]
    assert b.min() < -40 and b.max() > 40 and (b.abs() < 1).mean() > 0.15  # export, import, idle
    assert b.abs().max() <= 49.5
    pv = -s[[f"P:{n}" for n in ENV["hv_generation"]["nodes"]]].sum(axis=1)
    assert pv.min() >= 0 and pv.max() <= 7.5 + 1e-9 and pv.max() > 6.5


def test_low_load_coverage_and_node_variation(env):
    s = ev.EnvelopeLoadGenerator().sample(20000, 4)
    loads = [n for site in ENV["primary_sites"].values() for n in site["node_shares"]]
    tot = s[[f"P:{n}" for n in loads]].sum(axis=1)
    assert tot.min() < 5.0 and tot.max() > 90.0  # near-zero through planning peak
    r = s["P:EPN:CHAU51"] / s["P:EPN:LEWS51"].replace(0, np.nan)
    assert r.std() > 0.1  # not one global multiplier


def test_generator_is_deterministic_and_datakit_shaped(env):
    g = ev.EnvelopeLoadGenerator()
    pd.testing.assert_frame_equal(g.sample(50, 7), g.sample(50, 7))

    class _Net:
        Pd = np.zeros(37)

    arr = g(_Net(), 43, "/dev/null", 50, 7)
    assert arr.shape == (37, 43, 2)
    others = [k for k in range(37) if k not in ENV["datakit_bus_index"].values()]
    assert np.all(arr[others] == 0)


# --------------------------------------------------------------------- isolation / selection
def test_e5b_pools_never_reuse_e4_e5_seeds():
    seeds = {s for p in ad.POOLS for s in ad.pool_seeds(p)}
    assert not seeds & ad.forbidden_seeds()


def test_training_data_from_other_experiments_is_refused():
    for p in ("data/interim/e5/synthetic", "data/interim/e4/datasets/S1_WEATHER_ALIGNED"):
        with pytest.raises(ad.LeakageError):
            ad.assert_synthetic_dataset(REPO_ROOT / p)


def test_real_states_refused_before_freeze():
    ft = _script("finetune_genco_e5b")
    for target in ("S1_WEATHER_ALIGNED", "S2_MATCHED_PV_CONTROL_s101", "E4D_TIMELINE"):
        with pytest.raises(ad.LeakageError, match="hidden"):
            ft.cmd_predict("e5b_ft_n100_s9_not_registered", target)


def test_transfer_refuses_without_frozen_registry(monkeypatch, tmp_path):
    ev5b = _script("evaluate_e5b")
    monkeypatch.setattr(ev5b, "REGISTRY", tmp_path / "missing.yaml")
    with pytest.raises(SystemExit, match="not frozen"):
        ev5b.frozen()


def test_selection_rule_is_synthetic_only():
    src = inspect.getsource(_script("evaluate_e5b").cmd_synthetic)
    for tok in ("S1_", "S2_", "E4D", "real_frame", "slot"):
        assert tok not in src, tok
    assert "val_pool_PBE_mean" in src


def test_subsets_deterministic_and_nested():
    ids = np.arange(70000, 140000)
    a = ad.training_subset(ids, 1000, 0)
    assert a == ad.training_subset(ids, 1000, 0)
    assert set(ad.training_subset(ids, 100, 0)) <= set(a)


@pytest.mark.skipif(not any((OUT / "runs").glob("e5b_ft_n100_s0.json")), reason="no E5b run yet")
def test_normalizer_fitted_on_e5b_training_split_only():
    from types import SimpleNamespace

    from gridfm_graphkit.datasets.normalizers import HeteroDataMVANormalizer

    rec = json.loads((OUT / "runs/e5b_ft_n100_s0.json").read_text())
    man = pd.read_parquet(ad.ALLOWED_ROOT / "manifest.parquet")
    train = ad.training_subset(ad.pool_ids(man, "train"), rec["n_train"], rec["seed"])
    norm = HeteroDataMVANormalizer(SimpleNamespace(data=SimpleNamespace(baseMVA=100)))
    stats = norm.fit(str(ad.ALLOWED_ROOT / ad.NETWORK / "raw"), train)
    assert float(stats["baseMVA"]) == pytest.approx(rec["normalizer"]["baseMVA"], rel=1e-6)
    ck = REPO_ROOT / rec["checkpoint"]["path"]
    if ck.exists():
        assert ad.sha256_file(ck) == rec["checkpoint"]["sha256"]


@pytest.mark.skipif(not REGISTRY.exists(), reason="E5b not frozen yet")
def test_registry_frozen_with_matching_hashes():
    reg = yaml.safe_load(REGISTRY.read_text())
    assert reg["frozen"] and reg["frozen_before_real_state_evaluation"]
    c = reg["checkpoints"][reg["selected"]]
    for k in ("checkpoint", "normalizer"):
        assert ad.sha256_file(REPO_ROOT / c[k]["path"]) == c[k]["sha256"]


# --------------------------------------------------------------------- populations / controls
@pytest.mark.skipif(not (OUT / "real_transfer.json").exists(), reason="transfer not evaluated")
def test_real_population_identical_to_e4_e5():
    ev5b = _script("evaluate_e5b")
    e4 = pd.read_parquet(REPO_ROOT / "reports/tables/e4_scenario_metrics.parquet")
    a = e4[e4.scenario_family == "S1_WEATHER_ALIGNED"].scenario_id.sort_values().tolist()
    for run in ("zero_shot", ev5b.e5_selected(), yaml.safe_load(REGISTRY.read_text())["selected"]):
        m, _ = ev5b.real_frame(run)
        assert sorted(m.scenario_id) == a


def test_matched_control_donors_frozen():
    d = pd.read_parquet(REPO_ROOT / "reports/experiments/e4/families/S2_donors.parquet")
    assert sorted(d.seed.unique()) == list(range(101, 111))
    assert ad.CFG["weather_and_ramps"]["gap"].startswith("S1 − S2 paired")


def test_ramp_absolute_error_is_reported_with_ratio():
    bus = pd.DataFrame(
        {
            "scenario": [0, 0, 1, 1],
            "bus": [0, 1, 0, 1],
            "PQ": [0, 1, 0, 1],
            "REF": [1, 0, 1, 0],
            "Vm_pred": [1, 1, 1, 1.0],
            "Vm_target": [1, 1, 1, 1.0],
            "Va_pred": [0, 0, 0, 0.0],
            "Va_target": [0, 0, 0, 0.0],
        }
    )
    br = pd.DataFrame(
        {
            "scenario": [0, 1],
            "from_bus": [0, 0],
            "to_bus": [1, 1],
            "Pft": [0.0, 2.0],
            "Pft_target": [0.0, 1.0],
            "Qft": [0, 0.0],
            "Qft_target": [0, 0.0],
        }
    )
    t = tr.transition_metrics(bus, br, pd.DataFrame({"scenario_i": [0], "scenario_j": [1]}))
    assert t.dP_tracking_ratio.iat[0] == pytest.approx(2.0)  # overshoot
    assert t.dP_err_mean_abs.iat[0] == pytest.approx(1.0)  # absolute error kept alongside
    assert "absolute ΔP error" in ad.CFG["weather_and_ramps"]["ramp_report"]
    assert "ratio alone never counts" in ad.CFG["weather_and_ramps"]["ramp_physically_improved"]
