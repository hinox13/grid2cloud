# E2 follow-up: Sundon topology and measurement-interpretation sensitivity

_2 October 2026._

To reproduce:

```bash
uv run --env-file .env python scripts/run_topology_sensitivity.py
```

Outputs:

- [`tables/e2_topology_sensitivity.csv`](tables/e2_topology_sensitivity.csv) (one row per variant)
- [`tables/e2_topology_sensitivity_circuits.csv`](tables/e2_topology_sensitivity_circuits.csv)
- [`experiments/e2_validation/topology_sensitivity.json`](experiments/e2_validation/topology_sensitivity.json) (rule evaluation)
- per-variant outputs in `experiments/e2_validation/scenarios/<variant>/`

## Answer

- **No defensible interpretation moves Sundon from B to A.** The verdict stays **B — USABLE WITH LIMITATIONS** under the pre-registered criteria for every variant, including the calibration experiment.
- **One interpretation materially improves the network-wide fit:** rescaling the battery-customer meter `lne_SUND_CHAP`. Import NMAE falls from 0.084 to 0.058 (−31%), import RMSE from 8.1 to 6.5 MW, and both grid transformers on the SUND11 section improve. Its evidence is independent of the targets it improves.
- **The recommended default for later stages is `sundon_capacity_scaled_with_outages`.** The baseline `sundon_base_ltds` is **preserved unchanged**, still reproduces byte-for-byte, and must be reported alongside it.

## 1. Baseline preservation

- The validated reconstruction is now named **`sundon_base_ltds`** ([`configs/networks/sundon_base_ltds.yaml`](../configs/networks/sundon_base_ltds.yaml)). The file was renamed from `sundon_operating_state.yaml`, and its content changed only by an identifying `scenario:` block.
- Every alternative is a separate file that `extends:` it and declares `scenario.changes`, with the reason, evidence and affected elements.
- Re-running the baseline after the refactor reproduces `e2_metrics_by_circuit.csv` and `e2_timestamps.csv` **byte-identically**. `results.parquet` is frame-identical, and the verdict and aggregates are equal.
- The decision rule ([`configs/networks/topology_sensitivity.yaml`](../configs/networks/topology_sensitivity.yaml)) was written **before** any variant ran.

## 2. Battery-circuit investigation (UKPN evidence only)

The circuit `lne_SUND_CHAP` runs SUND31 → CHAP31, the customer node "EPN 0272", over 0.3 km with a 670 A (38.3 MVA) rating. It publishes active power only.

| Evidence | Finding |
|---|---|
| Monthly index (28 published months) | Monthly max \|P\| has a median of 61.8 MW (range 50.8–63.8), symmetric ± in every month since Oct 2023: a hard, battery-like ceiling |
| Published capacities | ECR storage **49.5 MW** (connected 2023-04-14); LTDS Table 5 storage at Sundon 33 kV **52.1 MVA**. Both are below the observed ceiling. Table 5 also lists 42.1 MVA of storage at Sundon **132 kV** |
| Do other 33 kV meters co-move? (night, n > 3,000 each) | **No.** Every metered 33 kV circuit has slope \|s\| ≤ 0.008 MW per MW of CHAP flow |
| Do the import meters co-move? | Yes, and **equally**: GT1/GT2/GT3 slopes 0.209 / 0.223 / 0.215; the independent 132 kV GIS meters −0.218 / −0.233 / −0.223. Total ≈ **0.65** |
| Busbar power balance (OLS; tee circuit included; validation timestamps excluded; n = 5,348) | Other metered outflows: coefficient **0.95** (≈ 1, as physics requires); `lne_SUND_CHAP`: **0.71**. Stable across 2023/2024/2025 (0.67–0.74) and at night and midday (0.65–0.72) |

**Interpretation.** Power balance at the Sundon 33 kV busbar holds about 1:1 for every metered circuit except `lne_SUND_CHAP`. Its readings are about 1.3–1.4× the power that actually crosses the busbar, according to two independent meter sets: the 33 kV-side grid-transformer meters and the 132 kV GIS meters. The physical cause is **not established**. It could be a measurement scaling issue, or an unpublished element electrically at the customer side; the ratio happens to be close to 1/√2, but that is a numerical observation, not an explanation. The LTDS rating is also exceeded by the readings, even after scaling.

## 3. Variants

| Variant | Change | Evidence | Affected | Calibrated? |
|---|---|---|---|---|
| `sundon_base_ltds` | none | E1/E2 | — | no |
| `sundon_battery_meter_capacity_scaled` | `lne_SUND_CHAP` input × **0.801** = 49.5 MW (ECR capacity) / 61.8 MW (observed ceiling) | capacity vs ceiling; uses **no** validation series | load EPN:CHAP31 | no |
| `sundon_observed_outages` | general rule: a core metered line reading \|P\| < 0.05 MW while the all-closed model carries > 1 MW is out of service at that timestamp, and that reading is not scored | E2 Chaul End signature | triggered **5×, all `CHAU_SU33_1`, one episode 10–11 Dec 2024** | no |
| `sundon_capacity_scaled_with_outages` | both of the above | as above | as above | no |
| `sundon_battery_meter_kcl_calibrated` | `lne_SUND_CHAP` × **0.714**, the coefficient of the busbar balance fitted on **held-out** timestamps | §2 | load EPN:CHAP31 | **yes (calibration experiment)** |

**Considered and not implemented, because the evidence doesn't support them:**

- **`sundon_coupler_open`.** The battery swings are shared equally by all three grid transformers, including GT2 on the SUND12 section. With both 132 kV sections at equal source voltage (A05), an open coupler gives the same solution as a closed one, and no voltage or angle measurements exist to tell them apart.
- **`sundon_secondary_path`.** Contradicted by the data: no metered circuit co-moves with the battery flow, and the only unmetered outlet (`SU33_SU11_2`, about 2 MVA) cannot carry the missing ~30% of ±63 MW swings.

No electrical parameter (R/X, transformer impedance, rating) and no load multiplier was tuned.

## 4. Results (primary scenario V0, same 200 timestamps)

| Variant | Import NMAE | Import RMSE (MW) | Import r | Core MAE (MW) | Core NMAE | Core r ≥ 0.9 | Min direction | Current SU33_SU11_2 (MAE A / r) | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| sundon_base_ltds | 0.084 | 8.14 | 0.888 | 0.94 | 0.098 | 64% | 0.99 | 2.96 / 0.959 | B |
| battery_meter_capacity_scaled | **0.058** | **6.52** | 0.911 | 0.82 | 0.086 | 64% | 1.00 | 2.96 / 0.959 | B |
| observed_outages | 0.084 | 8.14 | 0.888 | 0.92 | 0.096 | 64% | 0.99 | 2.96 / 0.959 | B |
| **capacity_scaled_with_outages** | **0.058** | **6.52** | 0.911 | **0.81** | **0.085** | 64% | 1.00 | 2.96 / 0.959 | B |
| kcl_calibrated *(calibration)* | 0.058 | 6.24 | 0.917 | 0.82 | 0.086 | 73% | 1.00 | 2.97 / 0.959 | B |

Circuit-level r and NMAE (unchanged circuits omitted; full table in the CSV):

| Circuit | base | cap-scaled | outages | cap+out | kcl (calib.) |
|---|---|---|---|---|---|
| SUG1_SUG1_1 (GT1) | 0.870 / 0.117 | 0.894 / 0.086 | 0.870 / 0.117 | 0.894 / 0.086 | 0.901 / 0.081 |
| SUG1_SUG1_2 (GT2) | 0.856 / 0.131 | 0.871 / 0.126 | 0.856 / 0.131 | 0.871 / 0.126 | 0.874 / 0.130 |
| SUG1_SUG1_3 (GT3) | 0.868 / 0.111 | 0.891 / 0.082 | 0.868 / 0.111 | 0.891 / 0.082 | 0.897 / 0.078 |
| CHAU_SU33_1 | 0.960 / 0.060 | 0.960 / 0.060 | 0.990 / 0.049 | 0.990 / 0.049 | 0.960 / 0.060 |
| SU33_CHAU_2 | 0.903 / 0.093 | 0.903 / 0.093 | 0.941 / 0.082 | 0.941 / 0.082 | 0.903 / 0.093 |
| SUND_LBUZ_3(1) | 0.879 / 0.096 | unchanged | unchanged | unchanged | unchanged |
| SU33_SU11_1 (flagged) | 0.602 / 2.605 | unchanged | unchanged | unchanged | unchanged |

**Why A remains out of reach.** The A fit needs r ≥ 0.9 on 80% of core circuits. After the best non-calibrated variant, three circuits still fall short:

- the GT meters (r 0.87–0.89; GT2 keeps a systematic +1.9 MW sharing bias that no evidenced variant explains);
- `SUND_LBUZ_3(1)` (r 0.879), which no variant touches.

Even the calibrated scale only reaches 73%. Nothing evidence-based remains that would justify further changes.

## 5. Replacement decision (pre-declared rule)

| Variant | Rule result | Notes |
|---|---|---|
| battery_meter_capacity_scaled | eligible | Network-wide improvement (import, GT1, GT3); evidence independent of the improved targets |
| observed_outages | eligible *formally* | Its "import NMAE decrease" is numerically negligible (5th decimal), so the import criterion passes on a technicality. The real benefit is local (two Chaul End circuits) but physically justified |
| **capacity_scaled_with_outages** | **eligible; recommended** | Best non-calibrated result on every network-wide metric; 4 core circuits improved, none worse |
| kcl_calibrated | **not eligible** (calibration experiment) | Confirms the capacity-based scale is the right direction and size (0.71 vs 0.80) |

**Decision.** For later stages, use `sundon_capacity_scaled_with_outages` as the **default operating interpretation**. Keep `sundon_base_ltds` as the preserved planning-topology reference, and report both wherever Sundon results appear.

Caveats that travel with the default:

- The 0.80 factor **assumes** the observed ceiling corresponds to the 49.5 MW ECR capacity. The held-out calibration (0.71) suggests it may slightly under-correct.
- The outage rule only applies to historical timestamps where meters exist. It cannot be used for hypothetical states.
- `lne_SUND_CHAP` still exceeds its LTDS rating after scaling (simulated loading up to 137%). The rating question is open.
- The Sundon verdict remains **B**.

## Attribution

Contains UK Power Networks data licensed under CC BY 4.0. These are the operational circuit and transformer power-flow data, LTDS Tables 1, 2a, 3a and 5, and the Embedded Capacity Register.
