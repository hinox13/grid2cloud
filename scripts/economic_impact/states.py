# ruff: noqa: E501
"""Build, AC-solve and predict the pre-registered counterfactual states (configs/economic_impact/prereg.yaml).

    .venv/bin/python scripts/economic_impact/states.py   → data/interim/economic_impact/imports.parquet

For each intact S1 state: the state as reconstructed (base), CF_noPV (explicit 33 kV PV = 0) and
CF_clear (explicit PV at its clear-sky estimate). All are solved by the unchanged E5d machinery (counterfactual.py: E1
planning case, pandapower AC, generator-aware export) and predicted by the frozen E5c and E5d.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
import clearsky  # noqa: E402
import counterfactual as cf  # noqa: E402

WORK = ROOT / "data/interim/economic_impact"
OUT = ROOT / "reports/economic_impact"
NAME = "economic_v1"
S1_RAW = ROOT / "data/interim/e4/datasets/S1_WEATHER_ALIGNED/sundon_33kv/raw"
GATES = ROOT / "reports/experiments/e4/families/S1_WEATHER_ALIGNED_gates.parquet"
NODES = pd.read_parquet(ROOT / "data/demo/events/jun15_cloud_clearing/network_nodes.parquet").set_index("bus").node_key


def build() -> pd.DataFrame:
    g = pd.read_parquet(GATES)
    g = g[g.lines_out.fillna("").astype(str) == ""]
    bus = pd.read_parquet(S1_RAW / "bus_data.parquet", columns=["scenario", "bus", "Pd", "Qd"])
    bus = bus[bus.scenario.isin(g.scenario)]
    bus["node"] = bus.bus.map(NODES)
    P = bus.pivot(index="scenario", columns="node", values="Pd")
    Q = bus.pivot(index="scenario", columns="node", values="Qd")
    loads = ["EPN:CHAU51", "EPN:CHAU52", "EPN:LEWS51", "EPN:LBUZ51", "EPN:LBUZ5A", "EPN:SURP5B", "EPN:SURP5A", "EPN:SUPR52", "EPN:CHAP31"]
    clear = clearsky.assets_table()
    clear = clear[clear.asset_id == "ECR:955"].set_index("slot").pv_clear_mw
    rows, sid = [], 0
    for r in g.itertuples():
        base = {f"P:{n}": float(P.at[r.scenario, n]) for n in loads} | {f"Q:{n}": float(Q.at[r.scenario, n]) for n in loads}
        pv = float(-P.loc[r.scenario, cf.PV_NODES].sum())
        pvc = float(clear.get(r.slot, np.nan))
        for role, action, pv_cf in (("A", "base", pv), ("B", "noPV", 0.0), ("B", "clear", pvc)):
            if not np.isfinite(pv_cf):
                continue
            st = dict(base)
            for n in cf.PV_NODES:
                st[f"P:{n}"], st[f"Q:{n}"] = -pv_cf / 3, 0.0
            rows.append({"state_id": sid, "scenario_id": int(r.scenario), "role": role, "action": action, "dpv_mw": pv_cf - pv, "dbat_mw": 0.0,
                         "slot": r.slot, "pv_mw": pv, "pv_clear_mw": pvc, "s1_ac_import_mw": np.nan, **st})  # fmt: skip
            sid += 1
    return pd.DataFrame(rows)


def main() -> int:
    S = build()
    root, man = cf.solve(S, NAME)
    walls = {}
    for model in cf.MODELS:
        _, walls[model] = cf.predict(model, root, f"{NAME}__gpu", gpu="0")
    imp = {}
    for model, run in cf.MODELS.items():
        bus, _ = cf.read_predictions(cf.WORK / "predictions" / run / f"{NAME}__gpu")
        imp[model] = cf.import_mw(bus, "Pg_pred")
        imp["AC"] = cf.import_mw(bus, "Pg_target")
    out = S[["state_id", "scenario_id", "role", "action", "slot", "pv_mw", "pv_clear_mw", "dpv_mw"]].merge(man[["state_id", "scenario", "rejected"]], on="state_id")
    for m in ("AC", "E5c", "E5d"):
        out[f"import_{m}"] = out.scenario.map(imp[m])
    # consistency: the re-solved base must reproduce the frozen S1 AC import (slack generator p_mw)
    gen = pd.read_parquet(S1_RAW / "gen_data.parquet", columns=["scenario", "p_mw", "is_slack_gen"])
    frozen = gen[gen.is_slack_gen == 1].groupby("scenario").p_mw.sum()
    out["s1_frozen_import_mw"] = out.scenario_id.map(frozen)
    base = out[out.action == "base"]
    dev = (base.import_AC - base.s1_frozen_import_mw).abs()
    out.to_parquet(WORK / "imports.parquet", index=False)
    rec = {"states": len(S), "accepted": int(man.scenario.notna().sum()), "rejected": man.rejected.value_counts().to_dict(),
           "predict_wall_s": walls, "base_vs_frozen_import_max_abs_mw": float(dev.max()), "base_vs_frozen_import_mean_abs_mw": float(dev.mean())}  # fmt: skip
    (OUT / "states_build.json").write_text(json.dumps(rec, indent=2, default=str))
    print(json.dumps(rec, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
