# E5d: weather generalisation — NOT EVALUATED (transfer gate not met)

_12 October 2026._

**Pre-registered rule** ([`configs/experiments/e5d_selection.yaml`](../configs/experiments/e5d_selection.yaml) `weather_rule`): the frozen S1 − S2 test (10 S2 seeds, E4 donors, bootstrap B = 2,000, seed 20261006, materiality |rel| ≥ 10 % with the CI excluding 0) is repeated **only on E5D-A**.

**Result:** E5D-D — PARTIAL / OTHER ([`e5d_real_transfer.md`](e5d_real_transfer.md)).
- The selection was flagged.
- R3 (import level, MAE 13.2 MW), R4 (Vm MAE 0.0109 pu) and R6 (battery slope 1.17) fail.

**Consequences:**
- **Weather remains unresolved because E5d did not pass the full real-transfer gate.**
- No S1, S2 or timeline inference was run with E5d. The E4 populations, donors, seeds and bootstrap remain untouched.

**What changed for a future attempt:**
- For the first time, a frozen GENCO model responds to real satellite-derived PV with approximately the physical sensitivity: import slope −1.07 against AC −1.02.
- The remaining blockers are an absolute import offset (+13 MW) and small voltage and battery-response errors, not PV blindness.
