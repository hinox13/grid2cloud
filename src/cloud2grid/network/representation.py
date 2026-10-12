"""E5 representation sensitivity: near-zero-impedance branches (configs/experiments/
e5_representation_sensitivity.yaml).

`near_zero_z_lines` applies the pre-registered rule (series |z| on 100 MVA at LTDS's quantisation
floor, same nominal voltage at both ends, lines only). `merge_lines` fuses each such line's end
buses with a closed zero-impedance bus–bus switch (pandapower's own bus fusion, as for the
SUND11–SUND12 coupler) and moves the line's total charging to a shunt at the fused node. Nothing
else changes. `ac_difference` compares two solved nets on everything they share.
"""

from __future__ import annotations

import copy

import numpy as np
import pandapower as pp
import pandas as pd

BASE_MVA = 100.0
OMEGA = 2 * np.pi * 50.0


def line_table(net: pp.pandapowerNet, base_mva: float = BASE_MVA) -> pd.DataFrame:
    """Per line: names, ends, length, per-unit series impedance, charging, admittance, dP/dθ."""
    ln = net.line
    vf = net.bus.vn_kv.loc[ln.from_bus].to_numpy()
    vt = net.bus.vn_kv.loc[ln.to_bus].to_numpy()
    par = ln["parallel"].to_numpy() if "parallel" in ln else np.ones(len(ln))
    zb = vf**2 / base_mva
    r = ln.r_ohm_per_km.to_numpy() * ln.length_km.to_numpy() / par / zb
    x = ln.x_ohm_per_km.to_numpy() * ln.length_km.to_numpy() / par / zb
    c_total_f = ln.c_nf_per_km.to_numpy() * 1e-9 * ln.length_km.to_numpy() * par
    b_pu = OMEGA * c_total_f * zb
    z = np.hypot(r, x)
    with np.errstate(divide="ignore"):
        y = 1.0 / z
    return pd.DataFrame(
        {
            "line": ln.index,
            "name": ln["name"].to_numpy(),
            "from_node": net.bus.name.loc[ln.from_bus].to_numpy(),
            "to_node": net.bus.name.loc[ln.to_bus].to_numpy(),
            "vn_kv": vf,
            "same_voltage": vf == vt,
            "length_m": ln.length_km.to_numpy() * 1000,
            "r_pu": r,
            "x_pu": x,
            "abs_z_pu": z,
            "b_pu": b_pu,
            "abs_y_pu": y,
            "dP_dtheta_mw_per_rad": y * base_mva,
            "dP_per_millidegree_mw": y * base_mva * np.deg2rad(1e-3),
            "ltds_quanta_r": np.round(r / 1e-4, 2),
            "ltds_quanta_x": np.round(x / 1e-4, 2),
            "charging_mvar_at_1pu": b_pu * base_mva,
        }
    )


def near_zero_z_lines(net: pp.pandapowerNet, max_abs_z_pu: float) -> list[int]:
    t = line_table(net)
    return t.loc[(t.abs_z_pu <= max_abs_z_pu) & t.same_voltage, "line"].astype(int).tolist()


def merge_lines(net: pp.pandapowerNet, lines: list[int]) -> pp.pandapowerNet:
    """Copy of `net` with each line replaced by a closed bus–bus switch + its charging as a shunt.

    The line rows are removed (callers such as StateBuilder.apply reset `line.in_service`); the
    shunt keeps reactive balance: q_mvar = −vn² · ω · C_total (pandapower load convention). The
    switch and shunt carry the line's index in `merged_line`, so an observed outage of the line
    maps to an OPEN switch (and no charging) — the same topology as the original."""
    out = copy.deepcopy(net)
    t = line_table(out).set_index("line")
    for c in ("switch", "shunt"):
        if "merged_line" not in out[c]:
            out[c]["merged_line"] = pd.Series(dtype="float64")
    for li in lines:
        f, to = int(out.line.from_bus.at[li]), int(out.line.to_bus.at[li])
        sw = pp.create_switch(
            out, f, to, et="b", closed=True, z_ohm=0.0, name=f"merged {out.line.name.at[li]}"
        )
        out.switch.at[sw, "merged_line"] = li
        q = -float(t.at[li, "charging_mvar_at_1pu"])
        if q != 0.0:
            sh = pp.create_shunt(
                out, f, q_mvar=q, p_mw=0.0, name=f"charging of {out.line.name.at[li]}"
            )
            out.shunt.at[sh, "merged_line"] = li
        out.line = out.line.drop(index=li)
    return out


def ac_difference(orig: pp.pandapowerNet, merged: pp.pandapowerNet) -> dict[str, float]:
    """Max absolute differences between two SOLVED nets on shared buses / branches / slack."""
    bus = orig.res_bus.join(merged.res_bus, rsuffix="_m", how="inner")
    dva = (bus.va_degree - bus.va_degree_m + 180.0) % 360.0 - 180.0
    ln = orig.res_line.join(merged.res_line, rsuffix="_m", how="inner")
    tr = orig.res_trafo.join(merged.res_trafo, rsuffix="_m", how="inner")
    dp = np.concatenate(
        [
            (ln.p_from_mw - ln.p_from_mw_m).abs().to_numpy(),
            (ln.p_to_mw - ln.p_to_mw_m).abs().to_numpy(),
            (tr.p_hv_mw - tr.p_hv_mw_m).abs().to_numpy(),
            (tr.p_lv_mw - tr.p_lv_mw_m).abs().to_numpy(),
        ]
    )
    dq = np.concatenate(
        [
            (ln.q_from_mvar - ln.q_from_mvar_m).abs().to_numpy(),
            (ln.q_to_mvar - ln.q_to_mvar_m).abs().to_numpy(),
            (tr.q_hv_mvar - tr.q_hv_mvar_m).abs().to_numpy(),
            (tr.q_lv_mvar - tr.q_lv_mvar_m).abs().to_numpy(),
        ]
    )
    return {
        "max_abs_dVm_pu": float((bus.vm_pu - bus.vm_pu_m).abs().max()),
        "max_abs_dVa_deg": float(dva.abs().max()),
        "max_abs_dP_branch_mw": float(dp.max()),
        "max_abs_dQ_branch_mvar": float(dq.max()),
        "max_abs_d_slack_p_mw": float(
            abs(orig.res_ext_grid.p_mw.sum() - merged.res_ext_grid.p_mw.sum())
        ),
        "max_abs_d_slack_q_mvar": float(
            abs(orig.res_ext_grid.q_mvar.sum() - merged.res_ext_grid.q_mvar.sum())
        ),
        "merged_power_balance_mva": internal_mismatch_mva(merged),
        "n_bus_internal_orig": int(orig._ppc["internal"]["bus"].shape[0]),
        "n_bus_internal_merged": int(merged._ppc["internal"]["bus"].shape[0]),
    }


def internal_mismatch_mva(net: pp.pandapowerNet) -> float:
    """max |S(V) − S_bus| over the internal (fused) buses of a solved net, MVA."""
    ppc = net._ppc["internal"]
    v = np.asarray(ppc["V"])
    sbus = np.asarray(ppc["Sbus"]) if "Sbus" in ppc else None
    ybus = ppc["Ybus"]
    s_calc = v * np.conj(ybus @ v)
    if sbus is None:
        from pandapower.pypower.makeSbus import makeSbus

        sbus = makeSbus(ppc["baseMVA"], ppc["bus"], ppc["gen"])
    mis = (s_calc - sbus) * ppc["baseMVA"]
    # the slack bus absorbs the balance: exclude reference buses (type 3)
    ref = ppc["bus"][:, 1].real == 3
    return float(np.abs(mis[~ref]).max())


def transfer_state(src: pp.pandapowerNet, dst: pp.pandapowerNet) -> None:
    """Copy an operating state (loads, sgens, line statuses) from the original net to its merged
    copy, so both representations hold the SAME state. Outage detection (E2) runs on the original
    only (one of its meters, SUG1_SUG1_1, is a merged branch). A merged line that is out of service
    in the state opens its switch and removes its charging shunt."""
    dst.load[["p_mw", "q_mvar"]] = src.load.loc[dst.load.index, ["p_mw", "q_mvar"]]
    if len(dst.sgen):
        dst.sgen[["p_mw", "q_mvar", "in_service"]] = src.sgen.loc[
            dst.sgen.index, ["p_mw", "q_mvar", "in_service"]
        ]
    status = src.line["in_service"].astype(bool)
    dst.line["in_service"] = status.loc[dst.line.index]
    sw = dst.switch["merged_line"].notna()
    dst.switch.loc[sw, "closed"] = status.loc[
        dst.switch.loc[sw, "merged_line"].astype(int)
    ].to_numpy()
    sh = dst.shunt["merged_line"].notna()
    dst.shunt.loc[sh, "in_service"] = status.loc[
        dst.shunt.loc[sh, "merged_line"].astype(int)
    ].to_numpy()
