"""S2 — stratified PV–load reassignment control (E4-C2/C3).

For each base half-hour T (the S1 population), the PV forcing is taken from a DONOR slot T' of a
different day in the same stratum: (calendar month, UTC time of day). Within a month the solar
time of a given clock time drifts by only a few minutes (equation of time), so the stratum fixes
season and solar-time regime; historical active capacity is constant over the 2024 window.

Donors are a random DERANGEMENT of the stratum's own members, so:
    * the PV marginal distribution is preserved exactly within every stratum (and overall);
    * no base keeps its own weather (each stratum has at most one slot per day → donor day ≠ base);
    * the real association between this electrical state and this weather is broken.
This tests whether the JOINT relationship (real electrical state × real weather) changes what
GENCO sees — it is a "stratified PV–load reassignment control", not a test of temporal order
(GENCO is steady-state: reordering an unchanged set of states cannot change its errors).
Singleton strata cannot be deranged; they are excluded and reported.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def stratum(slots: pd.DatetimeIndex) -> pd.Series:
    s = pd.DatetimeIndex(slots)
    return pd.Series(
        [f"{t.month:02d}|{t.hour:02d}:{t.minute:02d}" for t in s], index=s, name="stratum"
    )


def derangement(n: int, rng: np.random.Generator, max_tries: int = 1000) -> np.ndarray | None:
    """Uniform random permutation of range(n) with no fixed point (rejection sampling)."""
    if n < 2:
        return None
    for _ in range(max_tries):
        p = rng.permutation(n)
        if not (p == np.arange(n)).any():
            return p
    raise RuntimeError("could not draw a derangement")


def assign_donors(base_slots: pd.DatetimeIndex, seed: int) -> pd.DataFrame:
    """One donor per base slot. Deterministic for a given (sorted) base set and seed."""
    st = stratum(pd.DatetimeIndex(sorted(base_slots)))
    rng = np.random.default_rng(seed)
    rows = []
    for key in sorted(st.unique()):
        members = st.index[st == key].sort_values()
        perm = derangement(len(members), rng)
        if perm is None:
            rows.append(
                {
                    "base_slot": members[0],
                    "donor_slot": pd.NaT,
                    "stratum": key,
                    "stratum_size": 1,
                    "excluded": "singleton stratum",
                }
            )
            continue
        for i, b in enumerate(members):
            rows.append(
                {
                    "base_slot": b,
                    "donor_slot": members[perm[i]],
                    "stratum": key,
                    "stratum_size": len(members),
                    "excluded": None,
                }
            )
    out = pd.DataFrame(rows)
    out["seed"] = seed
    return out
