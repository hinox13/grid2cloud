"""E5 tests: isolation (no weather leakage), split integrity, deterministic subsets, normalizer
train-only fitting, checkpoint provenance, E4/E5 population identity, fixed donors / ramp bins /
heroes, and representation equivalence. Integration tests skip when the (gitignored) data are
absent.
"""

import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pandapower as pp
import pandas as pd
import pytest
import yaml

from cloud2grid.genco import adaptation as ad
from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.network import representation as rp

CFG = ad.CFG
E4_RA = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_ramp_analysis.yaml").read_text())
SYN = ad.ALLOWED_ROOT
RUNS = REPO_ROOT / "reports/experiments/e5/runs"
needs_synthetic = pytest.mark.skipif(
    not (SYN / "manifest.parquet").exists(), reason="E5 synthetic pools not generated"
)


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- isolation
def _fake_dataset(root: Path, man: pd.DataFrame, bus_cols: dict | None = None) -> Path:
    (root / ad.NETWORK / "raw").mkdir(parents=True)
    man.to_parquet(root / "manifest.parquet", index=False)
    pd.DataFrame(bus_cols or {"scenario": [0], "bus": [0]}).to_parquet(
        root / ad.NETWORK / "raw" / "bus_data.parquet"
    )
    return root


def _man(seeds=(6000,), pool="train", source="gridfm-datakit") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "scenario": range(len(seeds)),
            "pool": pool,
            "datakit_seed": list(seeds),
            "scenario_in": 0,
            "load_block": [f"b{i}" for i in range(len(seeds))],
            "source": source,
        }
    )


@pytest.mark.parametrize(
    "family",
    ["S1_WEATHER_ALIGNED", "S2_MATCHED_PV_CONTROL_s101", "E4D_TIMELINE", "S0_STANDARD_SYNTHETIC"],
)
def test_e4_and_weather_datasets_are_refused_for_training(family):
    with pytest.raises(ad.LeakageError):
        ad.assert_synthetic_dataset(REPO_ROOT / "data/interim/e4/datasets" / family)


def test_leakage_checks_fail_loudly(tmp_path, monkeypatch):
    monkeypatch.setattr(ad, "ALLOWED_ROOT", tmp_path / "synthetic")
    # non-datakit scenario
    _fake_dataset(tmp_path / "synthetic", _man(source="S1_WEATHER_ALIGNED"))
    with pytest.raises(ad.LeakageError, match="non-datakit"):
        ad.assert_synthetic_dataset(tmp_path / "synthetic")
    # E4 S0 seed (evaluation-only states)
    root = tmp_path / "x"
    monkeypatch.setattr(ad, "ALLOWED_ROOT", root / "synthetic")
    _fake_dataset(root / "synthetic", _man(seeds=(1,)))
    with pytest.raises(ad.LeakageError, match="E4 S0"):
        ad.assert_synthetic_dataset(root / "synthetic")
    # weather column in the raw tables
    root = tmp_path / "y"
    monkeypatch.setattr(ad, "ALLOWED_ROOT", root / "synthetic")
    _fake_dataset(root / "synthetic", _man(), {"scenario": [0], "slot": ["2024-06-15T12:00Z"]})
    with pytest.raises(ad.LeakageError, match="weather columns"):
        ad.assert_synthetic_dataset(root / "synthetic")
    # a path outside the allowed root
    with pytest.raises(ad.LeakageError):
        ad.assert_synthetic_dataset(tmp_path / "elsewhere")


def test_predict_on_weather_is_refused_until_frozen():
    ft = _script("finetune_genco_e5")
    for target in ("S1_WEATHER_ALIGNED", "S2_MATCHED_PV_CONTROL_s105", "E4D_TIMELINE"):
        with pytest.raises(ad.LeakageError, match="hidden"):
            ft.cmd_predict("ft_n100_s1_not_frozen", target)


def test_pools_use_registered_disjoint_seeds():
    seeds = {p: set(ad.pool_seeds(p)) for p in ad.POOLS}
    assert not (seeds["test"] & seeds["val"]) and not (seeds["test"] & seeds["train"])
    assert not (seeds["val"] & seeds["train"])
    e4 = set(
        yaml.safe_load((REPO_ROOT / "configs/experiments/e4_zero_shot.yaml").read_text())[
            "s0_standard_synthetic"
        ]["seeds"]
    )
    assert not (set().union(*seeds.values()) & e4)


# --------------------------------------------------------------------------- splits / subsets
def test_split_integrity_checks():
    man = pd.DataFrame(
        {
            "scenario": range(6),
            "pool": ["test", "val", "val", "train", "train", "train"],
            "load_block": ["t0", "v0", "v1", "a", "a", "b"],
        }
    )
    ad.assert_split_ids(man, [3, 4, 5], [1, 2], [0])
    with pytest.raises(ad.LeakageError):
        ad.assert_split_ids(man, [3, 4, 1], [2], [0])  # val id in train
    with pytest.raises(ad.LeakageError):
        ad.assert_split_ids(man, [3, 4, 5], [1, 2], [0, 5])  # train id in test
    bad = man.assign(load_block=["t0", "a", "v1", "a", "a", "b"])  # block crosses train/val
    with pytest.raises(ad.LeakageError, match="crosses"):
        ad.assert_split_ids(bad, [3, 4, 5], [1, 2], [0])


def test_training_subsets_deterministic_nested_and_seed_specific():
    ids = np.arange(1000, 61000)
    a = ad.training_subset(ids, 1000, 0)
    assert a == ad.training_subset(ids, 1000, 0)
    assert set(ad.training_subset(ids, 100, 0)) <= set(a) <= set(ad.training_subset(ids, 10000, 0))
    assert set(a) != set(ad.training_subset(ids, 1000, 1))
    with pytest.raises(ValueError):
        ad.training_subset(ids[:50], 100, 0)


def test_validation_subset_ratio_and_seed_independence():
    ids = np.arange(7000)
    for n in (100, 1000, 10000, 50000):
        v = ad.validation_subset(ids, n)
        assert len(v) == math.ceil(n / 8)
    assert set(ad.validation_subset(ids, 100)) <= set(ad.validation_subset(ids, 1000))


@needs_synthetic
def test_real_pools_pass_isolation_and_test_set_is_fixed():
    man = ad.assert_synthetic_dataset(SYN)
    assert (man.groupby("pool").scenario.count() > 0).all()
    assert int((man.pool == "train").sum()) >= 50000
    splits = json.loads((REPO_ROOT / "reports/experiments/e5/splits.json").read_text())
    assert splits["test_ids_sha256"] == ad.sha256_ids(ad.pool_ids(man, "test").tolist())
    for rec in map(lambda p: json.loads(p.read_text()), RUNS.glob("*.json")):
        assert rec["split_sha256"]["test"] == splits["test_ids_sha256"]
        assert rec["n_val"] == math.ceil(rec["n_train"] / 8)


# ----------------------------------------------------------------- normalizer / provenance
@pytest.mark.skipif(not any(RUNS.glob("ft_n100_s0.json")), reason="no E5 run yet")
def test_normalizer_is_fitted_on_training_split_only():
    from types import SimpleNamespace

    from gridfm_graphkit.datasets.normalizers import HeteroDataMVANormalizer

    rec = json.loads((RUNS / "ft_n100_s0.json").read_text())
    train = ad.training_subset(
        ad.pool_ids(pd.read_parquet(SYN / "manifest.parquet"), "train"), rec["n_train"], rec["seed"]
    )
    norm = HeteroDataMVANormalizer(SimpleNamespace(data=SimpleNamespace(baseMVA=100)))
    stats = norm.fit(str(SYN / ad.NETWORK / "raw"), train)
    assert float(stats["baseMVA"]) == pytest.approx(rec["normalizer"]["baseMVA"], rel=1e-6)


@pytest.mark.skipif(not any(RUNS.glob("*.json")), reason="no E5 run yet")
def test_checkpoint_provenance_recorded_and_hashes_match():
    for p in RUNS.glob("*.json"):
        rec = json.loads(p.read_text())
        for k in (
            "checkpoint",
            "normalizer",
            "split_sha256",
            "best_epoch",
            "wall_s",
            "environment",
        ):
            assert k in rec, (p.name, k)
        ck = REPO_ROOT / rec["checkpoint"]["path"]
        if ck.exists():
            assert ad.sha256_file(ck) == rec["checkpoint"]["sha256"]
    reg = REPO_ROOT / "metadata/e5_checkpoint_registry.yaml"
    if reg.exists():
        r = yaml.safe_load(reg.read_text())
        for name in r.get("evaluable_on_weather", []):
            c = r["checkpoints"][name]
            assert ad.sha256_file(REPO_ROOT / c["checkpoint"]["path"]) == c["checkpoint"]["sha256"]
            assert ad.sha256_file(REPO_ROOT / c["normalizer"]["path"]) == c["normalizer"]["sha256"]


# --------------------------------------------------------------------------- E4/E5 identity
E5_METRICS = REPO_ROOT / "reports/tables/e5_scenario_metrics.parquet"


@pytest.mark.skipif(not E5_METRICS.exists(), reason="E5 weather evaluation not run")
def test_e4_and_e5_population_ids_are_identical():
    e4 = pd.read_parquet(REPO_ROOT / "reports/tables/e4_scenario_metrics.parquet")
    e5 = pd.read_parquet(E5_METRICS)
    e5 = e5[e5["checkpoint"] == "adapted"]
    for fam in (
        "S0_STANDARD_SYNTHETIC",
        "S1_WEATHER_ALIGNED",
        "S2_MATCHED_PV_CONTROL",
        "E4D_TIMELINE",
    ):
        a = e4[e4.scenario_family == fam][["scenario_id", "timestamp", "control_seed"]]
        b = e5[e5.scenario_family == fam][["scenario_id", "timestamp", "control_seed"]]
        key = ["scenario_id", "control_seed"]
        pd.testing.assert_frame_equal(
            a.sort_values(key).reset_index(drop=True), b.sort_values(key).reset_index(drop=True)
        )


def test_matched_control_donors_are_the_e4_donors():
    p = REPO_ROOT / "reports/experiments/e4/families/S2_donors.parquet"
    d = pd.read_parquet(p)
    assert sorted(d["seed"].unique()) == list(range(101, 111))
    ev = _script("evaluate_e5")
    pd.testing.assert_frame_equal(ev.load_donors().reset_index(drop=True), d.reset_index(drop=True))


def test_ramp_bins_frozen_to_e4_edges():
    from cloud2grid.evaluation import transitions as tr

    g = pd.read_parquet(REPO_ROOT / "reports/experiments/e4/families/E4D_TIMELINE_gates.parquet")
    g = g[g.rejected.isna()].assign(scenario=lambda x: x.scenario.astype(int))
    pairs = tr.consecutive_pairs(g[["scenario", "slot", "p_hv_injected_mw"]])
    x = pairs.loc[pairs.within_halfhour, "abs_dPV_injected_mw"]
    edges = CFG["repeat_e4"]["ramp_bins_frozen"]["edges"]
    assert np.quantile(x, E4_RA["ramp_bins"]["quantiles"]).tolist() == pytest.approx(edges, abs=0)
    assert CFG["repeat_e4"]["ramp_bins_frozen"]["labels"] == E4_RA["ramp_bins"]["labels"]


def test_hero_events_are_the_e4_heroes():
    heroes = CFG["repeat_e4"]["heroes"]
    assert set(heroes) <= set(E4_RA["events"]["hero"])
    ev = json.loads((REPO_ROOT / "reports/experiments/e4/evaluation.json").read_text())
    assert set(E4_RA["events"]["hero"]) - set(heroes) == set(ev["hero_not_evaluable"])


# --------------------------------------------------------------------------- representation
def _toy() -> pp.pandapowerNet:
    net = pp.create_empty_network()
    b = [pp.create_bus(net, 33, name=f"B{i}") for i in range(4)]
    pp.create_ext_grid(net, b[0])
    pp.create_line_from_parameters(net, b[0], b[1], 2.0, 0.1, 0.3, 300, 0.5, name="long")
    pp.create_line_from_parameters(net, b[1], b[2], 0.02, 0.0871, 0.0871, 0.0, 0.5, name="jumper")
    pp.create_line_from_parameters(net, b[2], b[3], 0.3, 0.06, 0.15, 1600, 0.5, name="tail")
    pp.create_load(net, b[2], 8.0, 2.0)
    pp.create_load(net, b[3], 4.0, 1.0)
    return net


def test_merge_rule_selects_only_quantisation_floor_branches():
    net = _toy()
    t = rp.line_table(net).set_index("name")
    assert t.at["jumper", "abs_z_pu"] < 5e-4 < t.at["tail", "abs_z_pu"]
    assert net.line.name.loc[rp.near_zero_z_lines(net, 5e-4)].tolist() == ["jumper"]


def test_merge_preserves_ac_solution_and_charging():
    net = _toy()
    m = rp.merge_lines(net, rp.near_zero_z_lines(net, 5e-4))
    assert "jumper" not in set(m.line.name) and len(m.switch) == 1
    pp.runpp(net, calculate_voltage_angles=True)
    pp.runpp(m, calculate_voltage_angles=True)
    d = rp.ac_difference(net, m)
    assert d["n_bus_internal_merged"] == d["n_bus_internal_orig"] - 1
    assert d["max_abs_dVm_pu"] < 1e-4 and d["max_abs_dP_branch_mw"] < 1e-2
    assert d["merged_power_balance_mva"] < 1e-6
    # charging moved, not lost: a long line with charging, merged, keeps reactive balance
    m2 = rp.merge_lines(net, [int(net.line.index[net.line.name == "tail"][0])])
    assert len(m2.shunt) == 1 and m2.shunt.q_mvar.iat[0] < 0


def test_outage_of_a_merged_branch_opens_its_switch():
    net = _toy()
    pp.create_line_from_parameters(net, 1, 2, 0.02, 0.0871, 0.0871, 900.0, 0.5, name="jumper2")
    m = rp.merge_lines(net, rp.near_zero_z_lines(net, 5e-4))
    net.load.loc[0, "p_mw"] = 9.5
    rp.transfer_state(net, m)
    assert m.load.p_mw.iat[0] == 9.5 and m.switch.closed.all() and m.shunt.in_service.all()
    net.line.loc[net.line.name == "jumper2", "in_service"] = False
    rp.transfer_state(net, m)
    j2 = int(net.line.index[net.line.name == "jumper2"][0])
    assert not m.switch.loc[m.switch.merged_line == j2, "closed"].any()
    assert not m.shunt.loc[m.shunt.merged_line == j2, "in_service"].any()
    pp.runpp(net, calculate_voltage_angles=True)
    pp.runpp(m, calculate_voltage_angles=True)
    assert rp.ac_difference(net, m)["max_abs_dVm_pu"] < 1e-4


REP_JSON = REPO_ROOT / "reports/experiments/e5/representation.json"


@pytest.mark.skipif(not REP_JSON.exists(), reason="representation analysis not run")
def test_representation_verdict_follows_preregistered_tolerances():
    res = json.loads(REP_JSON.read_text())
    tol = yaml.safe_load(
        (REPO_ROOT / "configs/experiments/e5_representation_sensitivity.yaml").read_text()
    )["equivalence_test"]["tolerances"]
    ok = all(res["worst_case"][k] <= tol[k] for k in tol)
    assert res["verdict"] == ("AC_EQUIVALENT" if ok else "REJECTED")
    assert sorted(b["name"] for b in res["merged_branches"]) == sorted(
        ["SU33_SU11_4", "SUG1_SUG1_1", "SUG1_SUG1_2", "SUG1_SUG1_3"]
    )
