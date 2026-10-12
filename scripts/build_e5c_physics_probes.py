"""E5c — paired synthetic physics probes (validation: gate + selection; test: reporting only).

    uv run --env-file .env python scripts/build_e5c_physics_probes.py --set validation
    uv run --env-file .env python scripts/build_e5c_physics_probes.py --set test

Each pair is two AC-solved states on the E1 planning network (LTDS topology, unperturbed
admittances, intact, A1 slack limits) that differ in ONE physical input: total LBUZ generation
(`pv`), the CHAP31 battery (`battery`) or one primary demand (`load`). Base states come from the
E5c static envelope sampler; deltas follow configs/experiments/e5c_generator_aware.yaml
`physics_probes`. Solved with pandapower + PowerModels (E4 export_stream, same AC gates), then
re-encoded generator-aware. The AC solutions are the targets (slopes are not assumed ±1).

Outputs: data/interim/e5c/probes/<set>/sundon_33kv/raw (+ probes.parquet) (gitignored);
reports/experiments/e5c/probes_<set>.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Iterator

import pandapower as pp
import pandas as pd
import yaml

from cloud2grid.genco import adaptation_e5c as ad
from cloud2grid.genco import opengridfm_export as ox
from cloud2grid.genco import runner
from cloud2grid.genco.generator_aware import reencode_dataset
from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.scenarios import envelope_e5c as ev

OUT = REPO_ROOT / "reports/experiments/e5c"
ZS = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_zero_shot.yaml").read_text())


def planning_net() -> tuple[pp.pandapowerNet, dict[str, int], dict[str, int]]:
    """E1 planning-case network (static LTDS) with load elements and LBUZ sgens."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import build_network as bn  # noqa: PLC0415

    cfg = yaml.safe_load(bn.DEFAULT_CONFIG.read_text())
    inp = bn.load_inputs(cfg)
    net, _ = bn.build(cfg, inp)
    loads = bn.add_load_elements(net, cfg)
    bus = {name: i for i, name in net.bus["name"].items()}
    sg = {
        n: pp.create_sgen(net, bus[n], 0.0, 0.0, name=f"gen@{n}")
        for n in ad.CFG["representation"]["gen_buses"].values()
    }
    return net, loads, sg


def states(
    pairs: pd.DataFrame, net: pp.pandapowerNet, loads: dict[str, int], sg: dict[str, int]
) -> Iterator[tuple[dict, pp.pandapowerNet]]:
    for d in pairs.to_dict("records"):
        for node, idx in loads.items():
            net.load.loc[idx, ["p_mw", "q_mvar"]] = [d[f"P:{node}"], d[f"Q:{node}"]]
        for node, idx in sg.items():
            net.sgen.loc[idx, ["p_mw", "q_mvar"]] = [-d[f"P:{node}"], 0.0]
        yield {k: d[k] for k in ("probe_id", "probe_type", "member", "node", "x_mw")}, net


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["validation", "test"], required=True)
    a = ap.parse_args()
    pcfg = ad.CFG["physics_probes"]
    seed = int(pcfg["seeds"][a.set])
    n_base = int(pcfg["n_base_states"])
    gen = ev.E5cLoadGenerator()
    base = gen.sample(n_base, seed)
    pairs = ev.probe_pairs(base, seed)
    net, loads, sg = planning_net()
    tmp = ad.WORK / "probes" / f"{a.set}_solved"
    raw, gates = ox.export_stream(
        states(pairs, net, loads, sg),
        ad.NETWORK,
        tmp,
        include_dc=True,
        slack_limits_mva=ZS["slack_limits_mva"],
    )
    acc = gates[gates.rejected.isna()].copy()
    acc["scenario"] = acc["scenario"].astype(int)
    complete = acc.groupby("probe_id")["member"].transform("nunique") == 2
    dest = ad.WORK / "probes" / a.set / ad.NETWORK / "raw"
    n = reencode_dataset(raw, dest, ad.GEN_BUSES, ad.PMAX)
    shutil.rmtree(tmp)
    inj = pairs[[c for c in pairs.columns if c.startswith(("P:", "Q:"))]].reset_index(drop=True)
    gates = pd.concat([gates.reset_index(drop=True), inj], axis=1)
    acc = acc.assign(complete=complete.to_numpy())
    acc.to_parquet(dest.parent.parent / "probes.parquet", index=False)
    OUT.mkdir(parents=True, exist_ok=True)
    gates.drop(columns=[c for c in gates if c.startswith(("P:", "Q:"))]).to_parquet(
        OUT / f"probes_{a.set}_gates.parquet", index=False
    )
    rec = {
        "set": a.set,
        "seed": seed,
        "base_states": n_base,
        "pairs": int(pairs.probe_id.nunique()),
        "states_requested": int(len(pairs)),
        "states_accepted": int(len(acc)),
        "written": n,
        "rejected": gates["rejected"].value_counts().to_dict(),
        "complete_pairs": {
            t: int(acc[acc.complete & (acc.member == "A")].probe_type.eq(t).sum())
            for t in ("pv", "battery", "load")
        },
        **runner.git_commit(),
    }
    (OUT / f"probes_{a.set}.json").write_text(json.dumps(rec, indent=2, default=str))
    print(json.dumps(rec, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
