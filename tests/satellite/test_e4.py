import numpy as np
import pandapower as pp
import pandas as pd
import pytest

from cloud2grid.evaluation import genco_metrics as gm
from cloud2grid.evaluation import statistics as st
from cloud2grid.evaluation import transitions as tr
from cloud2grid.genco.opengridfm_export import _balance
from cloud2grid.scenarios.matched_control import assign_donors, derangement, stratum
from cloud2grid.scenarios.weather import PVForcing, WeatherStates

# --------------------------------------------------------------------------- tiny network


class _Builder:
    """Minimal stand-in for network.states.StateBuilder (same interface)."""

    def __init__(self) -> None:
        net = pp.create_empty_network()
        b0 = pp.create_bus(net, 33, name="SLACK")
        b1 = pp.create_bus(net, 33, name="HV1")
        b2 = pp.create_bus(net, 11, name="LOAD")
        pp.create_ext_grid(net, b0)
        pp.create_line_from_parameters(net, b0, b1, 1, 0.1, 0.3, 10, 0.5)
        pp.create_transformer_from_parameters(net, b1, b2, 20, 33, 11, 0.5, 10, 0, 0)
        self.net = net
        self.bus = {"SLACK": b0, "HV1": b1, "LOAD": b2}
        self.loads = {"LOAD": pp.create_load(net, b2, 0, 0, name="LOAD")}
        self.dp = pd.DataFrame(
            {"LOAD": [10.0, 12.0]}, index=pd.to_datetime(["2024-06-15T12:00Z", "2024-06-16T12:00Z"])
        )
        self.interpretation = "test"

    def apply(self, ts: pd.Timestamp) -> dict:
        self.net.load.loc[self.loads["LOAD"], ["p_mw", "q_mvar"]] = [self.dp.at[ts, "LOAD"], 1.0]
        return {"timestamp": ts, "lines_out": []}


def _forcing() -> PVForcing:
    slots = pd.to_datetime(["2024-06-15T12:00Z", "2024-06-15T12:15Z", "2024-06-16T12:00Z"])
    pv = pd.DataFrame(
        [
            (s, a, cap, p, "GOOD", 0.8, 600.0)
            for s, hv, emb in zip(slots, [4.0, 5.0, 1.0], [0.5, 0.6, 0.1], strict=True)
            for a, cap, p in [("hv", 6.0, hv), ("emb", 2.0, emb), ("future", 0.0, 0.0)]
        ],
        columns=[
            "slot",
            "asset_id",
            "active_capacity_mw",
            "estimated_pv_mw",
            "status",
            "clearsky_index",
            "ghi",
        ],
    )
    return PVForcing.from_series(
        pv, {"hv": ["HV1"], "emb": ["LOAD"], "future": ["HV1"]}, {"hv", "future"}
    )


def test_s1_injects_hv_only_and_never_double_counts_embedded():
    b, f = _Builder(), _forcing()
    ws = WeatherStates(b, f)
    info = ws.synchronous(pd.Timestamp("2024-06-15T12:15Z"))
    assert info["p_hv_injected_mw"] == 5.0 and info["emb_delta_mw"] == 0.0
    assert b.net.sgen.p_mw.sum() == pytest.approx(5.0)
    assert b.net.load.p_mw.sum() == pytest.approx(10.0)  # embedded PV stays inside observed load


def test_transplant_grosses_up_then_replaces_embedded():
    b, f = _Builder(), _forcing()
    ws = WeatherStates(b, f)
    info = ws.transplant(pd.Timestamp("2024-06-15T12:00Z"), pd.Timestamp("2024-06-16T12:00Z"))
    assert b.net.sgen.p_mw.sum() == pytest.approx(1.0)  # donor HV
    assert b.net.load.p_mw.sum() == pytest.approx(10.0 + 0.5 - 0.1)
    assert info["emb_delta_mw"] == pytest.approx(0.4)
    # applying the base again resets the load: no accumulation across states
    ws.synchronous(pd.Timestamp("2024-06-15T12:00Z"))
    assert b.net.load.p_mw.sum() == pytest.approx(10.0)


def test_no_historical_capacity_leakage_into_forcing():
    f = _forcing()
    assert f.fleet["active_capacity_mw"].unique().tolist() == [8.0]  # inactive asset excluded
    assert "future" not in f.emb.columns


def test_scenario_construction_is_reproducible():
    vals = []
    for _ in range(2):
        b, f = _Builder(), _forcing()
        ws = WeatherStates(b, f)
        ws.transplant(pd.Timestamp("2024-06-15T12:00Z"), pd.Timestamp("2024-06-16T12:00Z"))
        pp.runpp(b.net)
        vals.append(b.net.res_bus.vm_pu.to_numpy())
    np.testing.assert_array_equal(vals[0], vals[1])


# ------------------------------------------------------------------------ matched control


def _slots() -> pd.DatetimeIndex:
    days = pd.date_range("2024-06-01", "2024-07-10", freq="D", tz="UTC")
    return pd.DatetimeIndex([d + pd.Timedelta(hours=h) for d in days for h in (10, 12.5)])


def test_donors_preserve_marginal_and_stratum_and_change_day():
    s = _slots()
    d = assign_donors(s, seed=101)
    ok = d[d["excluded"].isna()]
    assert (ok["base_slot"].dt.date != ok["donor_slot"].dt.date).all()
    assert (
        stratum(pd.DatetimeIndex(ok["base_slot"])).to_numpy()
        == stratum(pd.DatetimeIndex(ok["donor_slot"])).to_numpy()
    ).all()
    for _, g in ok.groupby("stratum"):  # donors are a permutation of the stratum: marginal exact
        assert sorted(g["base_slot"]) == sorted(g["donor_slot"])


def test_donors_are_seed_deterministic_and_seeds_differ():
    s = _slots()
    a, b, c = assign_donors(s, 101), assign_donors(s, 101), assign_donors(s, 102)
    pd.testing.assert_frame_equal(a, b)
    assert not a["donor_slot"].equals(c["donor_slot"])


def test_singleton_strata_are_excluded_not_self_paired():
    s = pd.to_datetime(["2024-06-01T10:00Z", "2024-07-01T10:00Z"])  # different months
    d = assign_donors(pd.DatetimeIndex(s), 1)
    assert d["excluded"].eq("singleton stratum").all()
    assert derangement(1, np.random.default_rng(0)) is None
    p = derangement(5, np.random.default_rng(0))
    assert sorted(p) == list(range(5)) and not (p == np.arange(5)).any()


# ---------------------------------------------------------------------------- AC gates


def test_power_balance_gate_detects_mismatch():
    # 2-bus system: datakit array layout (bus: scenario, bus, Pd, Qd, Pg, Qg, Vm, Va°)
    y = np.array([[1 - 10j, -1 + 10j], [-1 + 10j, 1 - 10j]])
    v = np.array([1.0, 0.98 * np.exp(-1j * np.deg2rad(2.0))])
    s = v * np.conj(y @ v) * 100
    bus = np.array(
        [
            [0, 1, 0, 0, s[0].real, s[0].imag, 1.0, 0.0],
            [0, 2, -s[1].real, -s[1].imag, 0, 0, 0.98, -2.0],
        ]
    )
    ybus = np.array([[0, i, j, y[i, j].real, y[i, j].imag] for i in range(2) for j in range(2)])
    p, q = _balance(bus, ybus, 100.0)
    assert p < 1e-9 and q < 1e-9
    bus[1, 2] += 1.0  # inconsistent load → gate must catch it
    assert _balance(bus, ybus, 100.0)[0] == pytest.approx(1.0)


# ------------------------------------------------------------------------------ metrics


def _pred(scen: int, vm_err: float, p_err: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    bus = pd.DataFrame(
        {
            "scenario": scen,
            "bus": [0, 1, 2],
            "PQ": [0, 1, 1],
            "PV": 0,
            "REF": [1, 0, 0],
            "Vm_target": [1.0, 0.99, 0.98],
            "Vm_pred": [1.0, 0.99 + vm_err, 0.98 - vm_err],
            "Va_target": [0.0, -0.01, -0.02],
            "Va_pred": [0.0, -0.01, -0.02],
            "active res. (MW)": [0.0, 1.0, 3.0],
            "reactive res. (MVar)": [0.0, 0.0, 4.0],
        }
    )
    bus["PBE"] = np.hypot(bus["active res. (MW)"], bus["reactive res. (MVar)"])
    br = pd.DataFrame(
        {
            "scenario": scen,
            "from_bus": [0, 1, 1, 2],
            "to_bus": [1, 0, 2, 1],
            "Pft": [10 + p_err, -10, 5, -5],
            "Qft": [0.0, 0, 0, 0],
            "Pft_target": [10.0, -10, 5, -5],
            "Qft_target": [0.0, 0, 0, 0],
        }
    )
    return bus, br


def test_genco_metric_definitions():
    bus, br = _pred(0, 0.01, 2.0)
    ratings = pd.DataFrame(
        {"scenario": [0, 0], "bus_a": [0, 1], "bus_b": [1, 2], "rating_mva": [20.0, 10.0]}
    )
    m = gm.scenario_metrics(bus, br, ratings).set_index("scenario").loc[0]
    assert m["PBE_mean"] == pytest.approx((0 + 1 + 5) / 3) and m["PBE_max"] == pytest.approx(5)
    assert m["P_residual"] == pytest.approx(4 / 3) and m["Q_residual"] == pytest.approx(4 / 3)
    assert m["V_error"] == pytest.approx(0.01)  # PQ buses only
    assert m["angle_error"] == pytest.approx(0.0)
    assert m["branch_P_error"] == pytest.approx(0.5)
    assert m["max_loading_error"] == pytest.approx(10.0)  # 2 MW on a 20 MVA group = 10 points
    assert m["max_loading_ac"] == pytest.approx(50.0) and not m["overload_ac"]


def test_transition_errors_isolate_tracking():
    b0, r0 = _pred(0, 0.0, 0.0)
    b1, r1 = _pred(1, 0.0, 0.0)
    b1[["Vm_target", "Vm_pred"]] -= 0.01  # both move by the same amount: perfect tracking
    r1[["Pft", "Pft_target"]] += 1.0
    r1.loc[0, "Pft"] += 0.5  # GENCO overshoots one edge by 0.5 MW
    t = tr.transition_metrics(
        pd.concat([b0, b1]),
        pd.concat([r0, r1]),
        pd.DataFrame({"scenario_i": [0], "scenario_j": [1]}),
    )
    assert t.loc[0, "dVm_err_mean_abs"] == pytest.approx(0.0)
    assert t.loc[0, "dVm_ac_mean_abs"] == pytest.approx(0.01)
    assert t.loc[0, "dP_err_mean_abs"] == pytest.approx(0.5 / 4)
    assert t.loc[0, "dP_tracking_ratio"] == pytest.approx(4.5 / 4)


def test_consecutive_pairs_and_ramp_bins():
    meta = pd.DataFrame(
        {
            "scenario": [0, 1, 2, 3],
            "slot": pd.to_datetime(
                ["2024-06-15T12:00Z", "2024-06-15T12:15Z", "2024-06-15T12:30Z", "2024-06-15T13:15Z"]
            ),
            "p_hv_injected_mw": [1.0, 3.0, 2.0, 2.0],
        }
    )
    p = tr.consecutive_pairs(meta)
    assert len(p) == 2 and p["within_halfhour"].tolist() == [True, False]
    assert p["abs_dPV_injected_mw"].tolist() == [2.0, 1.0]
    bins = tr.ramp_bins(
        pd.Series(np.arange(100.0)), [0, 0.5, 0.8, 0.95, 1.0], ["low", "medium", "high", "extreme"]
    )
    assert bins.value_counts().to_dict() == {"low": 50, "medium": 30, "high": 15, "extreme": 5}


# ---------------------------------------------------------------------------- bootstrap


def test_block_bootstrap_respects_blocks_and_is_deterministic():
    rng = np.random.default_rng(0)
    days = np.repeat(np.arange(20), 10)
    day_effect = rng.normal(0, 1, 20)[days]
    v = pd.Series(day_effect + rng.normal(0, 0.01, 200))
    blocks = pd.Series(days)
    a = st.block_mean_ci(v, blocks, 2000, 1)
    b = st.block_mean_ci(v, blocks, 2000, 1)
    assert a == b and a["blocks"] == 20
    naive = st.block_mean_ci(v, pd.Series(np.arange(200)), 2000, 1)  # pretends independence
    assert (a["ci_high"] - a["ci_low"]) > 2 * (naive["ci_high"] - naive["ci_low"])


def test_paired_gap_and_materiality_rule():
    df = pd.DataFrame(
        {
            "s1": np.r_[np.full(50, 1.2), np.full(50, 1.1)],
            "s2": 1.0,
            "day": np.repeat(np.arange(10), 10),
        }
    )
    g = st.gap_paired(df, "s1", "s2", "day", 1000, 3)
    assert g["relative"] == pytest.approx(0.15) and st.material(g, 0.10)
    same = df.assign(s1=1.0)
    assert not st.material(st.gap_paired(same, "s1", "s2", "day", 1000, 3), 0.10)
