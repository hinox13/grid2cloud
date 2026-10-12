"""E4-B / E4-D — real weather-driven Sundon states (+ AC reference, gated).

    uv run --env-file .env python scripts/build_weather_scenarios.py [--family ...]

Families (configs/experiments/e4_matched_control.yaml, e4_ramp_analysis.yaml):
    S1_WEATHER_ALIGNED            primary: half-hours T with usable slot T and complete E2 inputs;
                                  state = B(T) + HV PV of slot T (synchronous construction)
    S1_WEATHER_ALIGNED_BASE_LTDS  the same on the preserved sundon_base_ltds reference
    E4D_TIMELINE                  every usable 15-min slot whose half-hour base is complete

Each family: graphkit dataset (data/interim/e4/datasets/<family>/), per-state metadata + AC gate
table (reports/experiments/e4/families/<family>_gates.parquet) and a summary JSON.
No event selection, no visual selection: complete eligible populations only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Iterator
from typing import Any

import pandas as pd
import yaml

from cloud2grid.genco import opengridfm_export as ex
from cloud2grid.genco import runner
from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.network.states import StateBuilder
from cloud2grid.scenarios.weather import (
    PVForcing,
    WeatherStates,
    load_forcing,
    populations,
    slot_meta,
)

MC = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_matched_control.yaml").read_text())
ZS = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_zero_shot.yaml").read_text())
PVM = yaml.safe_load((REPO_ROOT / MC["forcing"]["pv_model"]).read_text())
WORK = REPO_ROOT / "data/interim/e4"
OUT = REPO_ROOT / "reports/experiments/e4/families"
NETWORK = "sundon_33kv"


def build(family: str, config_path: str, slots: pd.DatetimeIndex, forcing: PVForcing) -> dict:
    builder = StateBuilder(REPO_ROOT / config_path)
    ws = WeatherStates(builder, forcing)
    t0 = time.perf_counter()

    def states() -> Iterator[tuple[dict, Any]]:
        for s in slots:
            try:
                info = ws.synchronous(s)
            except KeyError as e:
                yield {"slot": s, "rejected_before_ac": str(e)}, None
                continue
            yield (
                {
                    "slot": s,
                    "base_halfhour": s.floor("30min"),
                    "donor_slot": s,
                    "p_hv_injected_mw": info["p_hv_injected_mw"],
                    "emb_delta_mw": 0.0,
                    "lines_out": ";".join(info["lines_out"]),
                    "load_p_mw": float(builder.net.load.p_mw.sum()),
                    "interpretation": builder.interpretation,
                    **slot_meta(forcing, s),
                },
                builder.net,
            )

    pre_rejected: list[dict] = []

    def gated() -> Iterator[tuple[dict, Any]]:
        for meta, net in states():
            if net is None:  # recorded, never silently dropped
                pre_rejected.append(
                    {**meta, "ac_converged": False, "rejected": meta["rejected_before_ac"]}
                )
                continue
            yield meta, net

    raw, gates = ex.export_stream(
        gated(),
        NETWORK,
        WORK / "datasets" / family,
        include_dc=True,
        slack_limits_mva=ZS["slack_limits_mva"],
    )
    gates = pd.concat([gates, pd.DataFrame(pre_rejected)], ignore_index=True)
    gates["family"] = family
    OUT.mkdir(parents=True, exist_ok=True)
    gates.to_parquet(OUT / f"{family}_gates.parquet", index=False)
    summary = {
        "family": family,
        "interpretation": builder.interpretation,
        "generated": int(len(slots)),
        "ac_attempted": int(len(gates)),
        "converged": int(gates["ac_converged"].sum()),
        "accepted": int(gates["rejected"].isna().sum()),
        "rejected": gates["rejected"].value_counts().to_dict(),
        "days": int(pd.Index(pd.DatetimeIndex(slots).date).nunique()),
        "wall_s": time.perf_counter() - t0,
        **runner.git_commit(),
    }
    (OUT / f"{family}.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, default=str))
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--family",
        nargs="*",
        default=["S1_WEATHER_ALIGNED", "S1_WEATHER_ALIGNED_BASE_LTDS", "E4D_TIMELINE"],
    )
    a = ap.parse_args()
    forcing = load_forcing(PVM, REPO_ROOT / MC["forcing"]["pv_series"])
    pops = populations(
        StateBuilder(REPO_ROOT / MC["network"]["interpretation"]),
        forcing,
        MC["primary_population"]["period"],
    )
    print({k: len(v) for k, v in pops.items()})
    spec = {
        "S1_WEATHER_ALIGNED": (MC["network"]["interpretation"], pops["primary"]),
        "S1_WEATHER_ALIGNED_BASE_LTDS": (MC["network"]["baseline_reference"], pops["primary"]),
        "E4D_TIMELINE": (MC["network"]["interpretation"], pops["timeline"]),
    }
    for fam in a.family:
        build(fam, *spec[fam], forcing)
    return 0


if __name__ == "__main__":
    sys.exit(main())
