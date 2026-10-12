"""E5c — generator-aware GENCO graphs: Leighton Buzzard generation as EXPLICIT generator nodes.

What E4–E5b gave GENCO (verified on the exported tables, reports/e5c_design.md §1): pandapower
folds every `sgen` into bus demand, and datakit generation used negative load, so the 33 kV
generation at LBUZ31/32/33 was a NEGATIVE `Pd` on PQ buses; the only `gen` node in every graph
was the slack.

Why not explicit generators in the solver input: PowerModels' network correction (run by datakit
and by our export) converts every bus carrying a generator into a PV bus with a fixed voltage
set-point. A fixed-output, fixed-power-factor distribution generator is a PQ injection, and a PV
bus would hand GENCO the true voltage magnitude as an input. Prototype on 20 S1 states: all 20
rejected by the solver-disagreement gate (0.040 pu).

What E5c does instead (closest representation the official pipeline supports): the AC state is
solved EXACTLY as before; the solved tables are then re-encoded so the injection at each
generation bus becomes a graphkit `gen` node (Pg known input, Qg fixed, bus stays PQ — graphkit's
PF mask predicts only REF-bus generator output). Bus demand there becomes 0. Pg − Pd per bus,
voltages, flows, Y-bus and the DC baseline are unchanged, so the physics is identical.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def reencode(
    bus: pd.DataFrame, gen: pd.DataFrame, gen_buses: list[int], pmax_mw: dict[int, float]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Move the (negative-demand) injection at `gen_buses` to explicit generator rows.

    Requires zero load at those buses (true for LBUZ31/32/33 in every E4–E5c population): the
    whole `-Pd` there is generation. One generator per bus per scenario, always present
    (in service, Pg may be exactly 0)."""
    b = bus.copy()
    sel = b["bus"].isin(gen_buses)
    if (b.loc[sel, "Pd"] > 1e-9).any():
        raise ValueError("positive demand at a generation bus: cannot attribute it to generation")
    rows = b.loc[sel, ["scenario", "load_scenario_idx", "bus", "Pd", "Qd"]].copy()
    p, q = -rows["Pd"].to_numpy(), -rows["Qd"].to_numpy()
    for col, add in (("Pg", p), ("Qg", q)):
        b.loc[sel, col] = b.loc[sel, col].to_numpy() + add
    if "Pg_dc" in b:
        b.loc[sel, "Pg_dc"] = b.loc[sel, "Pg_dc"].to_numpy() + p
    b.loc[sel, ["Pd", "Qd"]] = 0.0
    g = gen.copy()
    start = g.groupby("scenario")["idx"].max().rename("start")
    new = pd.DataFrame(
        {
            "scenario": rows["scenario"].to_numpy(),
            "load_scenario_idx": rows["load_scenario_idx"].to_numpy(),
            "bus": rows["bus"].to_numpy(),
            "p_mw": p,
            "q_mvar": q,
            "min_p_mw": 0.0,
            "max_p_mw": [pmax_mw[int(k)] for k in rows["bus"]],
            "min_q_mvar": q,
            "max_q_mvar": q,
            "cp0_eur": 0.0,
            "cp1_eur_per_mw": 0.0,
            "cp2_eur_per_mw2": 0.0,
            "in_service": 1.0,
            "is_slack_gen": 0.0,
        }
    )
    if "p_mw_dc" in g:
        new["p_mw_dc"] = p
    new = new.merge(start, left_on="scenario", right_index=True, how="left")
    new["idx"] = new["start"] + 1 + new.groupby("scenario").cumcount()
    new = new.drop(columns="start")
    for c in g.columns:
        if c not in new:
            new[c] = np.nan
    g = pd.concat([g, new[g.columns]], ignore_index=True).sort_values(["scenario", "idx"])
    return b, g.reset_index(drop=True)


def reencode_dataset(
    src_raw: str | Path,
    dst_raw: str | Path,
    gen_buses: list[int],
    pmax_mw: dict[int, float],
    scenarios: list[int] | None = None,
) -> int:
    """Copy a graphkit raw dataset (optionally a scenario subset, renumbered 0..n−1) with the
    generator re-encoding applied. Returns the number of scenarios written."""
    import shutil

    import pyarrow as pa
    import pyarrow.parquet as pq

    src_raw, dst_raw = Path(src_raw), Path(dst_raw)
    f = [("scenario", "in", [int(s) for s in scenarios])] if scenarios is not None else None
    tabs = {
        t: pd.read_parquet(src_raw / f"{t}.parquet", filters=f).drop(
            columns="scenario_partition", errors="ignore"
        )
        for t in ("bus_data", "branch_data", "gen_data", "y_bus_data", "runtime_data")
    }
    ids = sorted(tabs["bus_data"]["scenario"].unique())
    remap = {old: i for i, old in enumerate(ids)}
    for t in tabs:
        tabs[t]["scenario"] = tabs[t]["scenario"].map(remap)
    tabs["bus_data"], tabs["gen_data"] = reencode(
        tabs["bus_data"], tabs["gen_data"], gen_buses, pmax_mw
    )
    if dst_raw.parent.exists():
        shutil.rmtree(dst_raw.parent)
    dst_raw.mkdir(parents=True)
    for t, df in tabs.items():
        df = df.sort_values("scenario", kind="stable")
        df["scenario_partition"] = df["scenario"] // 1000
        pq.write_to_dataset(
            pa.Table.from_pandas(df, preserve_index=False),
            str(dst_raw / f"{t}.parquet"),
            partition_cols=["scenario_partition"],
        )
    m = next(src_raw.parent.glob("*.m"), None)
    if m is not None:
        shutil.copy(m, dst_raw.parent / m.name)
    pd.DataFrame({"scenario": range(len(ids)), "source_scenario": ids}).to_parquet(
        dst_raw.parent / "scenario_map.parquet", index=False
    )
    return len(ids)
