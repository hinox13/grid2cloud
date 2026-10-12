"""E5 — representation sensitivity of the near-zero-impedance area (before any fine-tuning).

    uv run --env-file .env python scripts/e5_representation_sensitivity.py analyse
    uv run --env-file .env python scripts/e5_representation_sensitivity.py export-merged
    (export-merged only if the merged representation is AC-equivalent)

`analyse` (pre-registered in configs/experiments/e5_representation_sensitivity.yaml):
  1. branch table of the Sundon network (impedance, LTDS quanta, |Y|, dP/dθ, equipment names);
  2. the merge rule → merged branch list (asserted equal to the pre-registered list);
  3. AC equivalence, merged vs original, on all 2,829 S1 states and on the E1 planning case
     scaled ×1.0…2.0 (pandapower AC PF, same states);
  4. float32 conditioning of the PBE metric on the exact AC solution;
  5. verdict AC_EQUIVALENT / REJECTED against the pre-registered tolerances.
`export-merged` writes the merged datakit case (planning peak + A1 slack limits) and re-exports
S1 in the merged representation (same states, same gates) for the zero-shot/adapted sensitivity.
No GENCO output is read here.

Outputs
    reports/tables/e5_near_zero_z_branches.csv, e5_representation_equivalence.csv
    reports/experiments/e5/representation.json
    data/interim/e5/network_merged/sundon_33kv.m
    data/interim/e5/datasets/S1_WEATHER_ALIGNED_MERGED/
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pandapower as pp
import pandas as pd
import yaml

from cloud2grid.genco import opengridfm_export as ox
from cloud2grid.genco import runner
from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.network import representation as rp
from cloud2grid.network.states import StateBuilder
from cloud2grid.scenarios.weather import WeatherStates, load_forcing, populations

RS = yaml.safe_load(
    (REPO_ROOT / "configs/experiments/e5_representation_sensitivity.yaml").read_text()
)
MC = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_matched_control.yaml").read_text())
ZS = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_zero_shot.yaml").read_text())
PVM = yaml.safe_load((REPO_ROOT / MC["forcing"]["pv_model"]).read_text())
OUT = REPO_ROOT / "reports/experiments/e5"
TABLES = REPO_ROOT / "reports/tables"
WORK = REPO_ROOT / "data/interim/e5"
NETWORK = "sundon_33kv"
MERGED = RS["representations"]["SUNDON_MERGED_NEAR_ZERO_Z"]
TOL = RS["equivalence_test"]["tolerances"]
MAX_Z = 5.0e-4


def planning_case() -> pp.pandapowerNet:
    """The E1 planning-peak net exactly as scripts/build_network.py builds it for export."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import build_network as bn  # noqa: PLC0415

    cfg = yaml.safe_load(bn.DEFAULT_CONFIG.read_text())
    inp = bn.load_inputs(cfg)
    net, _ = bn.build(cfg, inp)
    loads = bn.add_load_elements(net, cfg)
    bn.set_loads(net, loads, bn.planning_peak_values(cfg, inp, net)["values"])
    pp.runpp(net, calculate_voltage_angles=True)
    return net


def merged_lines(net: pp.pandapowerNet) -> list[int]:
    lines = rp.near_zero_z_lines(net, MAX_Z)
    names = sorted(net.line.name.loc[lines])
    if names != sorted(MERGED["merge_rule"]["expected_branches"]):
        raise SystemExit(
            f"merge rule selects {names}, pre-registered "
            f"{MERGED['merge_rule']['expected_branches']}"
        )
    return lines


def check(d: dict[str, float]) -> bool:
    return all(d[k] <= TOL[k] for k in TOL)


def cmd_analyse() -> None:
    t0 = time.perf_counter()
    plan = planning_case()
    tab = rp.line_table(plan).sort_values("abs_z_pu")
    lines = merged_lines(plan)
    tab["merged_by_rule"] = tab["line"].isin(lines)
    TABLES.mkdir(exist_ok=True)
    tab.to_csv(TABLES / "e5_near_zero_z_branches.csv", index=False)

    rows = []
    # (a) planning case, intact, loads scaled (covers the S0 regime)
    for k in (1.0, 1.25, 1.5, 1.75, 2.0):
        a = copy.deepcopy(plan)
        a.load[["p_mw", "q_mvar"]] *= k
        b = rp.merge_lines(a, lines)
        pp.runpp(a, calculate_voltage_angles=True)
        pp.runpp(b, calculate_voltage_angles=True)
        rows.append(
            {
                "population": "E1 planning peak",
                "state": f"load x{k}",
                "load_mw": float(a.load.p_mw.sum()),
                **rp.ac_difference(a, b),
            }
        )
    # (b) every S1 state: built once on the original (E2 outage detection), copied to the merged net
    forcing = load_forcing(PVM, REPO_ROOT / MC["forcing"]["pv_series"])
    bo = StateBuilder(REPO_ROOT / MC["network"]["interpretation"])
    wo = WeatherStates(bo, forcing)
    mnet = rp.merge_lines(bo.net, lines)
    slots = populations(bo, forcing, MC["primary_population"]["period"])["primary"]
    for s in slots:
        wo.synchronous(s)
        rp.transfer_state(bo.net, mnet)
        pp.runpp(bo.net, calculate_voltage_angles=True)
        pp.runpp(mnet, calculate_voltage_angles=True)
        rows.append(
            {
                "population": "S1_WEATHER_ALIGNED",
                "state": str(s),
                "load_mw": float(bo.net.load.p_mw.sum()),
                **rp.ac_difference(bo.net, mnet),
            }
        )
    eq = pd.DataFrame(rows)
    eq["within_tolerance"] = [check(r) for r in eq.to_dict("records")]
    eq.to_csv(TABLES / "e5_representation_equivalence.csv", index=False)
    worst = {k: float(eq[k].max()) for k in TOL}
    verdict = "AC_EQUIVALENT" if bool(eq["within_tolerance"].all()) else "REJECTED"

    # float32 conditioning of the PBE metric on the exact AC solution (original, E4 S1 export)
    cond = float32_floor(
        REPO_ROOT / "data/interim/e4/datasets/S1_WEATHER_ALIGNED" / NETWORK / "raw"
    )
    res = {
        "merge_rule": f"non-transformer line, same nominal voltage, |z| <= {MAX_Z} pu (100 MVA)",
        "merged_branches": tab.loc[
            tab.merged_by_rule,
            ["name", "from_node", "to_node", "length_m", "r_pu", "x_pu", "abs_z_pu", "b_pu"],
        ].to_dict(orient="records"),
        "states_tested": {p: int((eq.population == p).sum()) for p in eq.population.unique()},
        "worst_case": worst,
        "tolerances": TOL,
        "verdict": verdict,
        "float32_pbe_floor_on_exact_ac": cond,
        "wall_s": time.perf_counter() - t0,
        **runner.git_commit(),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "representation.json").write_text(json.dumps(res, indent=2, default=str))
    print(
        json.dumps(
            {
                k: res[k]
                for k in ("states_tested", "worst_case", "verdict", "float32_pbe_floor_on_exact_ac")
            },
            indent=1,
        )
    )


def float32_floor(raw: Path, n: int = 500) -> dict[str, float]:
    """PBE (graphkit definition) of the EXACT AC solution, float64 vs float32 arithmetic."""
    bus = pd.read_parquet(raw / "bus_data.parquet")
    br = pd.read_parquet(raw / "branch_data.parquet")
    out: dict[str, list] = {"float64": [], "float32": []}
    for s in sorted(bus.scenario.unique())[:n]:
        b = bus[bus.scenario == s].sort_values("bus")
        e = br[(br.scenario == s) & (br.br_status > 0)]
        for name, dt, ct in (
            ("float64", np.float64, np.complex128),
            ("float32", np.float32, np.complex64),
        ):
            v = b.Vm.to_numpy().astype(dt) * np.exp(1j * np.deg2rad(b.Va.to_numpy()).astype(dt))
            v = v.astype(ct)
            f, t = e.from_bus.to_numpy(), e.to_bus.to_numpy()

            def c(a: str, bb: str, e: pd.DataFrame = e, ct: type = ct) -> np.ndarray:
                return (e[a].to_numpy() + 1j * e[bb].to_numpy()).astype(ct)

            i_f = c("Yff_r", "Yff_i") * v[f] + c("Yft_r", "Yft_i") * v[t]
            i_t = c("Ytf_r", "Ytf_i") * v[f] + c("Ytt_r", "Ytt_i") * v[t]
            cur = np.zeros(len(v), ct)
            np.add.at(cur, f, i_f)
            np.add.at(cur, t, i_t)
            cur += (b.GS.to_numpy() + 1j * b.BS.to_numpy()).astype(ct) / 100 * v
            mis = v * np.conj(cur) * 100 - (
                (b.Pg - b.Pd).to_numpy() + 1j * (b.Qg - b.Qd).to_numpy()
            )
            out[name].append([np.abs(mis).mean(), np.abs(mis.real).mean()])
    return {
        f"{k}_{m}": float(np.mean(np.array(v)[:, i]))
        for k, v in out.items()
        for i, m in enumerate(["PBE_mean_mva", "P_residual_mw"])
    }


def cmd_export_merged() -> None:
    res = json.loads((OUT / "representation.json").read_text())
    if res["verdict"] != "AC_EQUIVALENT":
        raise SystemExit("merged representation REJECTED: not exported")
    plan = planning_case()
    lines = merged_lines(plan)
    # (1) datakit case: reproduce the E4 network file from the original, then write the merged one
    dk_o, _ = ox.to_datakit_network(plan, ZS["slack_limits_mva"])
    ref = REPO_ROOT / ZS["s0_standard_synthetic"]["network_file"]
    chk = WORK / "network_check" / f"{NETWORK}.m"
    chk.parent.mkdir(parents=True, exist_ok=True)
    dk_o.to_mpc(str(chk))
    same = _mpc_arrays_equal(chk, ref)
    if not same:
        raise SystemExit("could not reproduce the E4 network file from the E1 planning case")
    mplan = rp.merge_lines(plan, lines)
    pp.runpp(mplan, calculate_voltage_angles=True)
    dk_m, _ = ox.to_datakit_network(mplan, ZS["slack_limits_mva"])
    dest = WORK / "network_merged" / f"{NETWORK}.m"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dk_m.to_mpc(str(dest))
    # (2) S1 in the merged representation: same states, same gates
    forcing = load_forcing(PVM, REPO_ROOT / MC["forcing"]["pv_series"])
    b = StateBuilder(REPO_ROOT / MC["network"]["interpretation"])
    ws = WeatherStates(b, forcing)
    mnet = rp.merge_lines(b.net, lines)
    slots = populations(b, forcing, MC["primary_population"]["period"])["primary"]

    def states() -> Iterator[tuple[dict, pp.pandapowerNet]]:
        for s in slots:
            info = ws.synchronous(s)
            rp.transfer_state(b.net, mnet)
            yield (
                {
                    "slot": s,
                    "p_hv_injected_mw": info["p_hv_injected_mw"],
                    "lines_out": ";".join(info["lines_out"]),
                },
                mnet,
            )

    fam = "S1_WEATHER_ALIGNED_MERGED"
    raw, gates = ox.export_stream(
        states(),
        NETWORK,
        WORK / "datasets" / fam,
        include_dc=True,
        slack_limits_mva=ZS["slack_limits_mva"],
    )
    gates.to_parquet(OUT / f"{fam}_gates.parquet", index=False)
    summary = {
        "family": fam,
        "accepted": int(gates.rejected.isna().sum()),
        "rejected": gates.rejected.value_counts().to_dict(),
        "network_file_reproduced": same,
        **runner.git_commit(),
    }
    (OUT / f"{fam}.json").write_text(json.dumps(summary, indent=2, default=str))
    print(summary)


def _mpc_arrays_equal(a: Path, b: Path) -> bool:
    from matpowercaseframes import CaseFrames

    ca, cb = CaseFrames(str(a)), CaseFrames(str(b))
    return all(
        np.allclose(
            getattr(ca, k).to_numpy(dtype=float),
            getattr(cb, k).to_numpy(dtype=float),
            rtol=1e-9,
            atol=1e-9,
        )
        for k in ("bus", "gen", "branch")
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["analyse", "export-merged"])
    a = ap.parse_args()
    cmd_analyse() if a.command == "analyse" else cmd_export_merged()
    return 0


if __name__ == "__main__":
    sys.exit(main())
