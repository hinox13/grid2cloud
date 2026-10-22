# G2A Aylesbury East: operational validation fails the pre-registered gate; study stopped before training

_17 October 2026. Experiment G2A (Aylesbury East cross-network replication, authorised by the project owner on 17 October 2026). Criteria pre-registered in [`configs/g2/g2a_gate_and_validation.yaml`](../configs/g2/g2a_gate_and_validation.yaml) (commit `73e00c3`) before the network was built, before any AC solve and before the PV series existed._

## Answer

**STOP.** The reconstructed Aylesbury East network with satellite-derived PV fails the pre-registered E2-style validation (level **FAIL**, below B "usable"), and it fails the PV-specific criterion. As pre-registered, no synthetic data were generated, no model was trained and no GENCO evaluation was run. **The central G2A question remains untested.**

## Gate result

| Criterion (pre-registered) | Required | Result | |
|---|---|---|---|
| Structural checks | all pass | all pass | ✓ |
| AC convergence | ≥ 0.99 | 1.00 (200/200) | ✓ |
| Import NMAE | ≤ 0.25 | 0.154 | ✓ |
| Core circuits with r ≥ 0.8 and NMAE ≤ 0.30 | ≥ 60 % | 17 % (1 of 6) | ✗ |
| Direction agreement, every core circuit | ≥ 0.90 | 0.00 (`lne_AYLE_GT1`) | ✗ |
| PV: daylight import r | ≥ 0.80 | 0.814 | ✓ |
| PV: \|r(import residual, simulated HV PV)\| | ≤ 0.50 | 0.659 | ✗ |
| Real-evaluation states | ≥ 1,000 | 1,837 | ✓ |

**Per target (200 stratified half-hours, April–September 2024):**

| Target | r | NMAE | Bias (sim − obs, MW) | Direction |
|---|---:|---:|---:|---:|
| Import (AYLE_SUG1_1 + 2) | 0.796 | 0.154 | −2.19 | 1.00 |
| AYLE_BUCK_1 | 0.344 | 0.439 | −2.05 | 0.81 |
| AYLE_BUCK_2 | 0.316 | 0.449 | +1.70 | 0.81 |
| AYLE_EXCHT_1 | 0.930 | 0.100 | +0.43 | 1.00 |
| AYLE_EXCH_4 | 0.828 | 0.778 | +1.83 | 1.00 |
| AYLE_EXCH_7 | 0.847 | 0.494 | +1.30 | 1.00 |
| lne_AYLE_GT1 | −0.302 | 4.745 | +23.10 | 0.00 |

## Why it fails (post-hoc diagnostics; they do not change the decision)

- **Only about half of the estimated PV appears in the measured import.** Over all 1,837 complete daylight half-hours, a regression of the observed import on the measured loads and the satellite-derived PV gives **−0.51 MW per MW of PV** (the model implies about −1.0) and +1.21 per MW of measured load. Binned by estimated PV (5, 15, 25 and 36 MW), the observed import minus the measured loads falls by only 16 MW. Possible reasons that public data cannot separate: part of the registered 41 MW does not export into this import (export limits, curtailment, or a farm connected elsewhere than ECR and LTDS imply), or the PV-chain assumptions overstate these farms.
- **The grid-transformer section does not work as the LTDS planning topology implies.** `lne_AYLE_GT1` (AYLE3A → AYLE31) carries a steady 4–5 MW *towards* the GT1 busbar at every hour of the day. In the model it carries about half the import in the opposite direction. This points to unmodelled load or different switching at the GT1 busbar, consistent with the loads coefficient above 1.
- **The Buckingham Road feeder pair is not reproduced even as a sum** (r 0.34, NMAE 0.44), so the current-derived loads and the Waddesdon supply path also deviate.

**Implication:** if trained and evaluated on this reconstruction, the dominant driver of the "real" states, satellite PV, would act about twice as strongly as the measurements support. The cloud-driven signal would then be largely an imposed modelling assumption, which the brief explicitly ruled out.

## What was done

- **Gate and criteria:** pre-registered (`73e00c3`).
- **Network:** `configs/g2/aylesbury_east_base_ltds.yaml` with the unchanged E1 model code (`scripts/g2/a_build_network.py`): 56 buses, 53 lines, 16 transformers; structural checks pass; converges at the LTDS winter and summer peaks.
- **Satellite PV:** the unchanged E3 chain (`configs/g2/g2a_pv_model.yaml`; every PV parameter identical to Sundon's) on the existing April–September 2024 MDSSFTD crops, which cover Aylesbury East (`scripts/g2/a_build_pv.py`). 41.2 MW active; 8,185 of 9,040 daylight slots usable; all real-data checks pass; 15-minute ramps up to −32.6 MW.
- **Validation:** `scripts/g2/a_validate.py`, with the unchanged Sundon state machinery (`network.states.StateBuilder`, `scenarios.weather`). Results in `reports/g2/a/validation_*`; timestamps in `reports/tables/g2a_validation_timestamps.csv`.
- **Shared-code changes (additive; Sundon behaviour unchanged, tests pass):** `measurements.observed_import` accepts metered supply circuits (`import_circuits`), and `nodal_demand` gains a `circuit_monthly_mean` method for a customer circuit redacted most months.

## What would be needed to continue

Each option is a new protocol and needs the project owner's explicit authorisation; none is started here:

1. **A calibrated reconstruction, pre-registered as such.** Fit a PV export factor and a load at the GT1 busbar on a calibration split of half-hours, then re-validate on disjoint, held-out half-hours with the same criteria. The study would then be explicitly a calibrated reconstruction, and the PV scale an empirical estimate, not satellite physics alone.
2. **A topology-only replication.** Use the reconstructed Aylesbury network and its real loads with satellite PV as a realistic but unvalidated operating envelope, and report GENCO's state/sensitivity/conservation gaps on a second *topology*, explicitly not as validated real operation.
3. **Stop**, and keep the Sundon-only submission.
