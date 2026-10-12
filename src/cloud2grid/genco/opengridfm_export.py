"""Export solved pandapower states to the OpenGridFM (gridfm-datakit) dataset format.

Uses datakit's own code end-to-end: `Network` (MATPOWER structure, continuous indexing),
`branch_vectors`/`makeYbus` (admittance conventions), `pf_post_processing` (column schema)
and `save_node_edge_data` (partitioned parquet). Only the solved voltages come from
pandapower; branch flows are recomputed from datakit's admittances so the exported tables
are internally consistent with datakit conventions.

No GENCO inference or training happens here.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandapower as pp
import pandas as pd

VMIN, VMAX = 0.9, 1.1  # ASSUMED operating band written to MATPOWER VMIN/VMAX (unused by PF)


def to_datakit_network(
    net: pp.pandapowerNet, slack_limits_mva: float | None = None
) -> tuple[Any, dict[str, Any]]:
    """Solved pandapower net → (datakit Network, solver-style result dict).

    `slack_limits_mva` (E4): pandapower's internal case carries Qmin = Qmax = 0 for the external
    grid, which makes any OPF infeasible (datakit S0 generation). When given, the slack's P and Q
    limits are set to ±slack_limits_mva (physical supply capacity); None keeps E1 behaviour."""
    from gridfm_datakit.network import Network, branch_vectors
    from gridfm_datakit.utils.idx_brch import BR_STATUS, F_BUS, T_BUS
    from gridfm_datakit.utils.idx_bus import (
        BUS_I,
        BUS_TYPE,
        REF,
    )
    from gridfm_datakit.utils.idx_bus import (
        VA as C_VA,
    )
    from gridfm_datakit.utils.idx_bus import (
        VM as C_VM,
    )
    from gridfm_datakit.utils.idx_bus import (
        VMAX as C_VMAX,
    )
    from gridfm_datakit.utils.idx_bus import (
        VMIN as C_VMIN,
    )

    if getattr(net, "_ppc", None) is None or "internal" not in net._ppc:
        pp.runpp(net, calculate_voltage_angles=True)  # e.g. after a JSON round-trip
    if not net.converged:
        raise ValueError("export requires a converged power flow")
    # The internal ppc is the system pandapower actually solved (fused coupler buses merged,
    # out-of-service elements removed); its arrays are indexed consistently with V.
    ppc = net._ppc["internal"]
    bus = np.array(ppc["bus"][:, :13].real, dtype=float)
    branch = np.array(ppc["branch"][:, :13].real, dtype=float)
    gen = np.array(ppc["gen"][:, :21].real, dtype=float)
    n_bus = bus.shape[0]
    # 1-based MATPOWER bus ids
    bus[:, BUS_I] = np.arange(1, n_bus + 1)
    branch[:, F_BUS] = branch[:, F_BUS] + 1
    branch[:, T_BUS] = branch[:, T_BUS] + 1
    gen[:, 0] = gen[:, 0] + 1
    bus[:, C_VMIN], bus[:, C_VMAX] = VMIN, VMAX
    # Flat start in the case file, so datakit's solver cannot start at pandapower's answer.
    bus[:, C_VM], bus[:, C_VA] = 1.0, 0.0
    if slack_limits_mva is not None:
        gen[:, 8], gen[:, 9] = slack_limits_mva, -slack_limits_mva  # PMAX, PMIN
        gen[:, 3], gen[:, 4] = slack_limits_mva, -slack_limits_mva  # QMAX, QMIN
    gencost = np.tile([2.0, 0.0, 0.0, 3.0, 0.0, 0.0, 0.0], (gen.shape[0], 1))  # zero cost
    mpc = {
        "version": "2",
        "baseMVA": float(ppc["baseMVA"]),
        "bus": bus,
        "gen": gen,
        "branch": branch,
        "gencost": gencost,
    }
    dk = Network(mpc)
    if np.sum(dk.buses[:, BUS_TYPE] == REF) != 1:
        raise ValueError("expected exactly one reference bus")

    v = np.asarray(ppc["V"])  # solved voltages, internal order == continuous datakit order
    if len(v) != dk.buses.shape[0]:
        raise ValueError("internal ppc and voltage vector sizes differ")
    ytt, yff, yft, ytf = branch_vectors(dk.branches, dk.branches.shape[0])
    f = dk.branches[:, F_BUS].astype(int)
    t = dk.branches[:, T_BUS].astype(int)
    on = dk.branches[:, BR_STATUS] > 0
    sf = v[f] * np.conj(yff * v[f] + yft * v[t]) * on
    st = v[t] * np.conj(ytf * v[f] + ytt * v[t]) * on
    base = dk.baseMVA
    gen_res = net.res_ext_grid
    res = {
        "solve_time": 0.0,
        "solution": {
            "pf": True,
            "branch": {
                str(i + 1): {"pf": sf[i].real, "qf": sf[i].imag, "pt": st[i].real, "qt": st[i].imag}
                for i in range(len(sf))
            },
            "gen": {
                str(i + 1): {
                    "pg": float(gen_res.p_mw.iat[i]) / base,
                    "qg": float(gen_res.q_mvar.iat[i]) / base,
                }
                for i in range(len(gen_res))
            },
            "bus": {
                str(dk.reverse_bus_index_mapping[i]): {
                    "vm": float(abs(v[i])),
                    "va": float(np.angle(v[i])),
                }
                for i in range(n_bus)
            },
        },
    }
    return dk, res


def export_states(
    nets: list[pp.pandapowerNet], network_name: str, out_root: Path
) -> tuple[Path, pd.DataFrame]:
    """Write solved states as a datakit dataset solved by datakit's OWN AC power flow.

    Per state: pandapower → MATPOWER .m (datakit `Network.to_mpc`) → `load_net_from_file`
    (PowerModels normalisation) → datakit `run_pf` (PowerModels AC PF) → `pf_post_processing`.
    The pandapower solution is used only as an independent cross-check (returned table).
    Requires Julia/PowerModels (see .env.example: PYTHON_JULIAPKG_EXE).
    """
    import tempfile

    from gridfm_datakit.network import load_net_from_file
    from gridfm_datakit.process.process_network import init_julia, pf_post_processing
    from gridfm_datakit.process.solvers import run_pf
    from gridfm_datakit.save import save_node_edge_data

    raw = Path(out_root) / network_name / "raw"
    if raw.parent.exists():
        shutil.rmtree(raw.parent)
    raw.mkdir(parents=True)
    jl = init_julia(max_iter=200)
    processed, compare, dk_last = [], [], None
    with tempfile.TemporaryDirectory() as tmp:
        for i, net in enumerate(nets):
            dk_mem, res_pp = to_datakit_network(net)
            case = Path(tmp) / f"{network_name}_{i}.m"
            dk_mem.to_mpc(str(case))
            dk = load_net_from_file(str(case))
            res = run_pf(dk, jl)
            arrays = pf_post_processing(i, dk, res, None, False)
            processed.append(
                (arrays["bus"], arrays["gen"], arrays["branch"], arrays["Y_bus"], arrays["runtime"])
            )
            vm_dk = arrays["bus"][:, 6]
            va_dk = arrays["bus"][:, 7]
            vm_pp = np.array(
                [
                    res_pp["solution"]["bus"][str(dk.reverse_bus_index_mapping[k])]["vm"]
                    for k in range(len(vm_dk))
                ]
            )
            va_pp = np.rad2deg(
                [
                    res_pp["solution"]["bus"][str(dk.reverse_bus_index_mapping[k])]["va"]
                    for k in range(len(vm_dk))
                ]
            )
            compare.append(
                {
                    "scenario": i,
                    "datakit_pf_converged": bool(np.isfinite(vm_dk).all()),
                    "max_abs_vm_diff_pu": float(np.abs(vm_dk - vm_pp).max()),
                    "max_abs_va_diff_deg": float(np.abs(va_dk - va_pp).max()),
                    "max_abs_pf_diff_mw": _matched_branch_flow_diff(net, arrays["branch"]),
                }
            )
            dk_last = dk
            if i == 0:
                shutil.copy(case, raw.parent / f"{network_name}.m")
    save_node_edge_data(
        dk_last,
        str(raw / "bus_data.parquet"),
        str(raw / "branch_data.parquet"),
        str(raw / "gen_data.parquet"),
        str(raw / "y_bus_data.parquet"),
        str(raw / "runtime_data.parquet"),
        processed,
    )
    return raw, pd.DataFrame(compare)


def _matched_branch_flow_diff(net: pp.pandapowerNet, dk_branch: np.ndarray) -> float:
    """Max |P| difference at the same physical branch end, matching branches by
    (unordered endpoints, r, x). PowerModels' case normalisation reorders branches and
    reorients some (from_bus < to_bus), so positional comparison would be meaningless."""
    br = np.asarray(net._ppc["internal"]["branch"])
    pp_df = pd.DataFrame(
        {
            "f": br[:, 0].real.astype(int),
            "t": br[:, 1].real.astype(int),
            "r": br[:, 2].real.round(9),
            "x": br[:, 3].real.round(9),
            "pf": br[:, 13].real,
            "pt": br[:, 15].real,
        }
    )
    dk_df = pd.DataFrame(
        {
            "f": dk_branch[:, 2].astype(int),
            "t": dk_branch[:, 3].astype(int),
            "r": dk_branch[:, 8].round(9),
            "x": dk_branch[:, 9].round(9),
            "pf_dk": dk_branch[:, 4],
        }
    )
    for d in (pp_df, dk_df):
        d["a"] = d[["f", "t"]].min(axis=1)
        d["b"] = d[["f", "t"]].max(axis=1)
        d["k"] = d.groupby(["a", "b", "r", "x"]).cumcount()
    m = pp_df.merge(
        dk_df, on=["a", "b", "r", "x", "k"], how="outer", indicator=True, suffixes=("_pp", "_dk")
    )
    if (m["_merge"] != "both").any():
        return math.inf  # branch sets differ: report as a failure, not a number
    same = m["f_pp"] == m["f_dk"]
    pp_at_dk_from = np.where(same, m["pf"], m["pt"])
    return float(np.abs(pp_at_dk_from - m["pf_dk"]).max())


def power_balance_check(raw: Path) -> pd.DataFrame:
    """Per scenario: max |S_inj(V, Y) − (Sg − Sd)| from the exported tables (MW / MVAr)."""
    bus = pd.read_parquet(raw / "bus_data.parquet")
    ybus = pd.read_parquet(raw / "y_bus_data.parquet")
    rows = []
    for sc, b in bus.groupby("scenario"):
        b = b.sort_values("bus")
        n = len(b)
        y = np.zeros((n, n), dtype=complex)
        yb = ybus[ybus["scenario"] == sc]
        y[yb["index1"].astype(int), yb["index2"].astype(int)] = yb["G"] + 1j * yb["B"]
        v = b["Vm"].to_numpy() * np.exp(1j * np.deg2rad(b["Va"].to_numpy()))
        s_calc = v * np.conj(y @ v) * 100.0  # datakit base MVA
        s_spec = (b["Pg"] - b["Pd"]).to_numpy() + 1j * (b["Qg"] - b["Qd"]).to_numpy()
        mis = s_calc - s_spec
        rows.append(
            {
                "scenario": int(sc),
                "max_p_mismatch_mw": float(np.abs(mis.real).max()),
                "max_q_mismatch_mvar": float(np.abs(mis.imag).max()),
                "n_bus": n,
            }
        )
    return pd.DataFrame(rows)


def graphkit_load_check(dataset_root: Path) -> dict[str, Any]:
    """Process and load the exported dataset with gridfm-graphkit's own Dataset class."""
    from gridfm_graphkit.datasets.normalizers import HeteroDataPerSampleMVANormalizer
    from gridfm_graphkit.datasets.powergrid_hetero_dataset import HeteroGridDatasetDisk

    processed = Path(dataset_root) / "processed"
    if processed.exists():
        shutil.rmtree(processed)
    norm = HeteroDataPerSampleMVANormalizer(SimpleNamespace(data=SimpleNamespace(baseMVA=100)))
    ds = HeteroGridDatasetDisk(root=str(dataset_root), data_normalizer=norm)
    scenario_ids = list(range(len(ds)))
    norm.fit(str(Path(dataset_root) / "raw"), scenario_ids)
    graphs = [ds.get(i) for i in scenario_ids]
    g0 = graphs[0]
    return {
        "n_scenarios": len(graphs),
        "node_types": list(g0.node_types),
        "edge_types": [list(e) for e in g0.edge_types],
        "n_bus_nodes": int(g0["bus"].num_nodes),
        "n_gen_nodes": int(g0["gen"].num_nodes),
        "n_bus_edges": int(g0["bus", "connects", "bus"].edge_index.shape[1]),
        "bus_feature_dim": int(g0["bus"].x.shape[1]),
        "all_finite": bool(all(bool(np.isfinite(g["bus"].x.numpy()).all()) for g in graphs)),
    }


# ------------------------------------------------------------------- E4: streaming export


GATES = {
    "max_power_mismatch_mva": 1e-3,  # AC balance recomputed from the exported tables
    "vm_sanity_pu": (0.8, 1.2),  # physical sanity band (not an operating limit)
    "max_solver_disagreement_vm_pu": 1e-3,  # pandapower vs PowerModels
}


def _balance(bus: np.ndarray, ybus: np.ndarray, base_mva: float) -> tuple[float, float]:
    """Max |S_calc − S_spec| (MW, MVAr) from post-processed arrays (datakit column order)."""
    n = bus.shape[0]
    y = np.zeros((n, n), dtype=complex)
    # datakit Y_bus rows: [scenario, i, j, G, B]
    y[ybus[:, 1].astype(int), ybus[:, 2].astype(int)] = ybus[:, 3] + 1j * ybus[:, 4]
    v = bus[:, 6] * np.exp(1j * np.deg2rad(bus[:, 7]))
    s_calc = v * np.conj(y @ v) * base_mva
    s_spec = (bus[:, 4] - bus[:, 2]) + 1j * (bus[:, 5] - bus[:, 3])
    mis = s_calc - s_spec
    return float(np.abs(mis.real).max()), float(np.abs(mis.imag).max())


def bus_pair_ratings(net: pp.pandapowerNet, dk: Any) -> pd.DataFrame:
    """LTDS ratings (MVA) of in-service lines/transformers, summed per unordered pair of DATAKIT
    bus indices (parallel circuits grouped). GENCO's graph carries only the case's uniform
    RATE_A, so loading metrics use these ratings instead."""
    # pandapower bus → full ppc row (lookup) → internal row: rank among buses whose type is not
    # NONE (isolated / fused buses are type 4 and absent from the internal case, which is what
    # datakit receives). Verified by exact voltage identity below; any mismatch raises.
    ppc_type = net._ppc["bus"][:, 1].real.astype(int)
    to_int = np.full(len(ppc_type), -1)
    keep = ppc_type != 4
    to_int[keep] = np.arange(int(keep.sum()))
    look = net._pd2ppc_lookups["bus"]
    v_int = np.abs(np.asarray(net._ppc["internal"]["V"]))
    pd_int = {}
    for bus in net.bus.index[net.bus.in_service]:
        k = int(to_int[int(look[bus])])
        if k < 0 or not np.isfinite(net.res_bus.vm_pu.at[bus]):
            continue
        if abs(v_int[k] - net.res_bus.vm_pu.at[bus]) > 1e-9:
            raise ValueError(f"bus mapping mismatch at pandapower bus {bus}")
        pd_int[bus] = k
    inv = {int(dk.reverse_bus_index_mapping[k]) - 1: k for k in range(dk.buses.shape[0])}
    rows = []
    ln = net.line[
        net.line.in_service & net.line.from_bus.isin(pd_int) & net.line.to_bus.isin(pd_int)
    ]
    for _i, r in ln.iterrows():
        a, c = inv[pd_int[r.from_bus]], inv[pd_int[r.to_bus]]
        mva = np.sqrt(3) * net.bus.vn_kv.at[r.from_bus] * r.max_i_ka * r.parallel
        rows.append((min(a, c), max(a, c), float(mva), f"line:{r['name']}"))
    tr = net.trafo[
        net.trafo.in_service & net.trafo.hv_bus.isin(pd_int) & net.trafo.lv_bus.isin(pd_int)
    ]
    for i, r in tr.iterrows():
        a, c = inv[pd_int[r.hv_bus]], inv[pd_int[r.lv_bus]]
        rows.append((min(a, c), max(a, c), float(r.sn_mva * r.parallel), f"trafo:{i}"))
    df = pd.DataFrame(rows, columns=["bus_a", "bus_b", "rating_mva", "element"])
    return (
        df.groupby(["bus_a", "bus_b"])
        .agg(rating_mva=("rating_mva", "sum"), elements=("element", lambda s: ";".join(s)))
        .reset_index()
    )


def load_net_in_session(jl: Any, case: Path) -> Any:
    """datakit `load_net_from_file` with its `correct_network` step (PowerModels.parse_file +
    export_matpower) run in the EXISTING Julia session instead of a new Julia process per call.
    Same PowerModels calls and version; avoids ~10 s of Julia start-up per state."""
    from gridfm_datakit.network import Network
    from matpowercaseframes import CaseFrames

    corrected = case.with_name(case.stem + "_corrected.m")
    jl.seval("PowerModels.silence()")
    jl.seval(
        f'let d = PowerModels.parse_file("{case}"); '
        f'PowerModels.export_matpower("{corrected}", d) end'
    )
    frames = CaseFrames(str(corrected))
    mpc = {
        k: getattr(frames, k).values
        if isinstance(getattr(frames, k), pd.DataFrame)
        else getattr(frames, k)
        for k in frames._attributes
    }
    return Network(mpc)


def export_stream(
    states: Any,
    network_name: str,
    out_root: Path,
    include_dc: bool = True,
    gates: dict[str, Any] | None = None,
    slack_limits_mva: float | None = None,
) -> tuple[Path | None, pd.DataFrame]:
    """Solve and export states one at a time (no nets kept in memory).

    `states` yields (meta: dict, net: pandapowerNet) with the net already set to the state (the
    same object may be mutated between yields). Per state: pandapower AC PF → datakit MATPOWER →
    PowerModels AC PF (the reference) [+ DC PF baseline] → quality gates. Passing states get
    consecutive scenario ids; every state (passing or not) gets a row in the returned gate table.
    """
    import tempfile
    import time

    from gridfm_datakit.process.process_network import init_julia, pf_post_processing
    from gridfm_datakit.process.solvers import run_dcpf, run_pf
    from gridfm_datakit.save import save_node_edge_data

    g = {**GATES, **(gates or {})}
    raw = Path(out_root) / network_name / "raw"
    if raw.parent.exists():
        shutil.rmtree(raw.parent)
    raw.mkdir(parents=True)
    jl = init_julia(max_iter=200)
    processed, rows, dk_last, sid = [], [], None, 0
    ratings: list[pd.DataFrame] = []
    with tempfile.TemporaryDirectory() as tmp:
        for meta, net in states:
            row = {**meta, "ac_converged": False, "rejected": None}
            t0 = time.perf_counter()
            try:
                pp.runpp(net, calculate_voltage_angles=True)
            except pp.LoadflowNotConverged:
                row["rejected"] = "pandapower_not_converged"
                rows.append(row)
                continue
            row["pp_runtime_s"] = time.perf_counter() - t0
            row["ac_max_line_loading_pct"] = float(net.res_line.loading_percent.max())
            row["ac_max_trafo_loading_pct"] = float(net.res_trafo.loading_percent.max())
            try:
                dk_mem, res_pp = to_datakit_network(net, slack_limits_mva)
                # unique file per state: PowerModels must never re-read a previous case
                case = Path(tmp) / f"{network_name}_{len(rows)}.m"
                dk_mem.to_mpc(str(case))
                dk = load_net_in_session(jl, case)
                t1 = time.perf_counter()
                res = run_pf(dk, jl)
                row["pm_runtime_s"] = time.perf_counter() - t1
                res_dc = run_dcpf(dk, jl) if include_dc else None
                arrays = pf_post_processing(sid, dk, res, res_dc, include_dc)
            except Exception as e:  # noqa: BLE001 — recorded as a rejection reason
                row["rejected"] = f"powermodels_failed: {type(e).__name__}"
                rows.append(row)
                continue
            bus = arrays["bus"]
            vm = bus[:, 6]
            vm_pp = np.array(
                [
                    res_pp["solution"]["bus"][str(dk.reverse_bus_index_mapping[k])]["vm"]
                    for k in range(len(vm))
                ]
            )
            p_mis, q_mis = _balance(bus, arrays["Y_bus"], dk.baseMVA)
            row.update(
                ac_converged=bool(np.isfinite(vm).all()),
                max_p_mismatch_mw=p_mis,
                max_q_mismatch_mvar=q_mis,
                vm_min=float(np.nanmin(vm)),
                vm_max=float(np.nanmax(vm)),
                solver_disagreement_vm_pu=float(np.nanmax(np.abs(vm - vm_pp))),
                n_bus=int(len(vm)),
            )
            lo, hi = g["vm_sanity_pu"]
            if not row["ac_converged"]:
                row["rejected"] = "powermodels_not_converged"
            elif max(p_mis, q_mis) > g["max_power_mismatch_mva"]:
                row["rejected"] = "power_balance"
            elif row["vm_min"] < lo or row["vm_max"] > hi:
                row["rejected"] = "voltage_sanity"
            elif row["solver_disagreement_vm_pu"] > g["max_solver_disagreement_vm_pu"]:
                row["rejected"] = "solver_disagreement"
            if row["rejected"] is None:
                row["scenario"] = sid
                ratings.append(bus_pair_ratings(net, dk).assign(scenario=sid))
                processed.append(
                    (
                        arrays["bus"],
                        arrays["gen"],
                        arrays["branch"],
                        arrays["Y_bus"],
                        arrays["runtime"],
                    )
                )
                dk_last = dk
                if sid == 0:
                    shutil.copy(case, raw.parent / f"{network_name}.m")
                sid += 1
            rows.append(row)
    if not processed:
        return None, pd.DataFrame(rows)
    save_node_edge_data(
        dk_last,
        str(raw / "bus_data.parquet"),
        str(raw / "branch_data.parquet"),
        str(raw / "gen_data.parquet"),
        str(raw / "y_bus_data.parquet"),
        str(raw / "runtime_data.parquet"),
        processed,
        include_dc_res=include_dc,
    )
    pd.concat(ratings, ignore_index=True).to_parquet(
        raw.parent / "branch_ratings.parquet", index=False
    )
    return raw, pd.DataFrame(rows)
