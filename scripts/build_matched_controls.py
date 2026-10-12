"""E4-C2/C3 — S2_MATCHED_PV_CONTROL: stratified PV–load reassignment control (10 fixed seeds).

    uv run --env-file .env python scripts/build_matched_controls.py [--seeds 101 102 ...]

Same base half-hours as S1_WEATHER_ALIGNED. Per seed, donors are a derangement within each
(month, UTC time-of-day) stratum (`scenarios.matched_control`); each state is the documented
transplant (`scenarios.weather.WeatherStates.transplant`): HV PV from the donor, embedded PV
grossed up at the base slot and replaced by the donor. Same AC gates as every family.

Outputs per seed s (family S2_MATCHED_PV_CONTROL_s<s>):
    data/interim/e4/datasets/<family>/          graphkit dataset (gitignored)
    reports/experiments/e4/families/<family>_gates.parquet, <family>.json
    reports/experiments/e4/families/S2_donors.parquet   (all seeds: base, donor, stratum)
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
from cloud2grid.scenarios.matched_control import assign_donors
from cloud2grid.scenarios.weather import WeatherStates, load_forcing, populations, slot_meta

MC = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_matched_control.yaml").read_text())
ZS = yaml.safe_load((REPO_ROOT / "configs/experiments/e4_zero_shot.yaml").read_text())
PVM = yaml.safe_load((REPO_ROOT / MC["forcing"]["pv_model"]).read_text())
WORK = REPO_ROOT / "data/interim/e4"
OUT = REPO_ROOT / "reports/experiments/e4/families"
NETWORK = "sundon_33kv"
FAM = "S2_MATCHED_PV_CONTROL"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", nargs="*", type=int, default=MC["families"][FAM]["seeds"])
    a = ap.parse_args()
    forcing = load_forcing(PVM, REPO_ROOT / MC["forcing"]["pv_series"])
    builder = StateBuilder(REPO_ROOT / MC["network"]["interpretation"])
    primary = populations(builder, forcing, MC["primary_population"]["period"])["primary"]
    ws = WeatherStates(builder, forcing)
    OUT.mkdir(parents=True, exist_ok=True)
    all_donors = []
    for seed in a.seeds:
        t0 = time.perf_counter()
        donors = assign_donors(primary, seed)
        all_donors.append(donors)
        family = f"{FAM}_s{seed}"
        pairs = donors[donors["excluded"].isna()]

        def states(pairs: pd.DataFrame = pairs, seed: int = seed) -> Iterator[tuple[dict, Any]]:
            for r in pairs.itertuples():
                info = ws.transplant(r.base_slot, r.donor_slot)
                yield (
                    {
                        "slot": r.base_slot,
                        "base_halfhour": r.base_slot,
                        "donor_slot": r.donor_slot,
                        "stratum": r.stratum,
                        "control_seed": seed,
                        "p_hv_injected_mw": info["p_hv_injected_mw"],
                        "emb_delta_mw": info["emb_delta_mw"],
                        "lines_out": ";".join(info["lines_out"]),
                        "load_p_mw": float(builder.net.load.p_mw.sum()),
                        "interpretation": builder.interpretation,
                        **slot_meta(forcing, r.donor_slot),
                        **slot_meta(forcing, r.base_slot, "base_"),
                    },
                    builder.net,
                )

        raw, gates = ex.export_stream(
            states(),
            NETWORK,
            WORK / "datasets" / family,
            include_dc=True,
            slack_limits_mva=ZS["slack_limits_mva"],
        )
        gates["family"] = family
        gates.to_parquet(OUT / f"{family}_gates.parquet", index=False)
        summary = {
            "family": family,
            "control_seed": seed,
            "method": "stratified PV–load reassignment (derangement "
            "within month × UTC time-of-day)",
            "base_timestamps": int(len(primary)),
            "excluded_singleton_strata": int(donors["excluded"].notna().sum()),
            "generated": int(len(pairs)),
            "converged": int(gates["ac_converged"].sum()),
            "accepted": int(gates["rejected"].isna().sum()),
            "rejected": gates["rejected"].value_counts().to_dict(),
            "wall_s": time.perf_counter() - t0,
            **runner.git_commit(),
        }
        (OUT / f"{family}.json").write_text(json.dumps(summary, indent=2, default=str))
        print(json.dumps(summary, default=str), flush=True)
    pd.concat(all_donors, ignore_index=True).to_parquet(OUT / "S2_donors.parquet", index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
