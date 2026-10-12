# E2: Sundon operational validation against UKPN measurements

_2 October 2026._

To reproduce:

```bash
uv run --env-file .env python scripts/validate_operational.py
```

Outputs:

- [`experiments/e2_validation/summary.json`](experiments/e2_validation/summary.json) and `results.parquet`
- [`tables/e2_metrics_by_circuit.csv`](tables/e2_metrics_by_circuit.csv)
- [`tables/e2_topology_diagnostics.csv`](tables/e2_topology_diagnostics.csv)
- [`tables/e2_timestamps.csv`](tables/e2_timestamps.csv)
- figures `figures/e2_*.png`

> **Follow-up (same day):** [`e2_topology_sensitivity.md`](e2_topology_sensitivity.md) tests explicit topology and measurement-interpretation variants on the same 200 timestamps. The baseline below is preserved as `sundon_base_ltds` and reproduces byte-for-byte. A battery-meter interpretation cuts import NMAE from 0.084 to 0.058. **No variant changes the verdict.**

## Verdict: **B — USABLE WITH LIMITATIONS**

The criteria were fixed in [`configs/networks/sundon_base_ltds.yaml`](../configs/networks/sundon_base_ltds.yaml) **before** the full E2 run, with only one probe timestamp inspected. They apply to the uncalibrated primary scenario V0.

| Criterion | A (strong) | B (usable) | Result |
|---|---|---|---|
| Structural checks | all pass | all pass | ✅ all pass |
| AC PF convergence | 100% | ≥ 99% | ✅ 100% (200/200, all scenarios) |
| Core P circuits meeting fit | ≥ 80% with r ≥ 0.9 & NMAE ≤ 0.15 | ≥ 60% with r ≥ 0.8 & NMAE ≤ 0.30 | **A: 64% ❌** · B: 100% ✅ |
| Direction agreement (each core circuit, \|obs\| ≥ 0.5 MW) | ≥ 0.95 | ≥ 0.90 | ✅ 0.99–1.00 |
| Total import NMAE (V0) | ≤ 0.10 | ≤ 0.25 | ✅ 0.084 |

**A fails on one criterion only.** Four core circuits miss the A fit: the three GT/GIS import meters (r = 0.86–0.87) and `SUND_LBUZ_3(1)` (r = 0.88). §5 traces the import error mainly to an inconsistency in the metered battery-customer circuit, not to the network model.

## 1. Design

- **Inputs are observations only**, plus LTDS parameters. See E1 §5 for the nodal loads, the customer circuit and the transformer sign conventions.
- **Validation targets are metered circuits never used as inputs:** 12 active-power targets, 1 current target, plus the total import.
- **Timestamp selection** uses data completeness only, never model error, and no GENCO and no weather data are involved:
  - 15,343 half-hours have every load input and the import;
  - a seeded, stratified sample takes 3 per (calendar month × 6-hour block), giving **200 timestamps over 18 months**.
- **Eligibility is limited by input availability, and mostly falls in 2024:**
  - Sundon Primary T3/T4 feeders: 8% available in 2023;
  - the customer circuit `lne_SUND_CHAP` (redacted 9/37 months);
  - LBUZ T1/T2 P: **3% in 2026**.
  - As a result, almost no validated states postdate the 15 MW farm's connection (2026-02-25).
- **Data quality.** No validation observation exceeded 1.5× its rating. Only the input circuit `lne_SUND_CHAP` did (§5).
- **Scenarios:**
  - **V0_none (primary):** unobserved 33 kV customers inject 0. Fully uncalibrated.
  - **V1_tee_customer_nodes / V1_lbuz_33kv_busbars (diagnostic):** the residual "observed − modelled import" is placed at candidate nodes. The import then matches by construction.

## 2. Active-power validation (V0, primary)

Sign convention: P > 0 from the monthly index's from-node to its to-node, metered at the from-node end. This was verified on radial feeders and is applied identically to the model.

| Circuit | Mapping | Status | n | MAE (MW) | RMSE | Bias (sim−obs) | r | NMAE | Direction agreement |
|---|---|---|---|---|---|---|---|---|---|
| CHAU_SU33_1 | exact | core | 193 | 0.48 | 0.72 | +0.29 | 0.960 | 0.060 | 1.00 |
| SU33_CHAU_2 | exact | core | 200 | 0.68 | 1.05 | −0.68 | 0.903 | 0.093 | 1.00 |
| SU33_CHAU_3 | exact | core | 200 | 0.33 | 0.38 | −0.32 | 0.985 | 0.056 | 1.00 |
| SU33_LEWS_1 | exact | core | 200 | 0.28 | 0.45 | +0.12 | 0.940 | 0.065 | 1.00 |
| SU33_LEWS_2 | exact | core | 200 | 0.31 | 0.46 | −0.01 | 0.926 | 0.071 | 1.00 |
| SU33_LBUZT_1 | exact | core | 196 | 0.24 | 0.29 | −0.15 | 0.986 | 0.044 | 1.00 |
| SUND_LBUZ_3(1) | exact | core | 200 | 0.59 | 0.75 | −0.05 | **0.879** | 0.096 | 1.00 |
| SU33_LBUZT_2_(1) | node path (composite) | core | 60 | 0.42 | 0.69 | +0.26 | 0.941 | 0.068 | 1.00 |
| SUG1_SUG1_1 (GT1, 132 kV) | exact | core | 199 | 2.03 | 3.06 | −0.94 | **0.870** | 0.117 | 0.99 |
| SUG1_SUG1_2 (GT2) | exact | core | 198 | 2.62 | 3.63 | +1.93 | **0.856** | 0.131 | 0.99 |
| SUG1_SUG1_3 (GT3) | exact | core | 200 | 1.95 | 3.04 | −0.76 | **0.868** | 0.111 | 0.99 |
| **SU33_SU11_1** | exact | **flagged** | 199 | 1.68 | 1.76 | **+1.67** | 0.602 | **2.605** | 1.00 |
| Total import | aggregate | — | 200 | 4.60 | 8.14 | −0.14 | 0.888 | 0.084 | 0.99 |

Aggregates:

- **Core P circuits:** n = 2,046, MAE 0.94 MW, r = 0.985, NMAE 0.098, direction agreement 0.997.
- **All P circuits:** n = 2,245, NMAE 0.115.

Figure: [`figures/e2_obs_vs_sim_V0_none.png`](figures/e2_obs_vs_sim_V0_none.png).

How to read the results:

- **33 kV circuits feeding primaries are reproduced to about 0.2–0.7 MW.** These include the parallel pairs (Chaul End 2+1 circuits onto two 11 kV busbars; Lewsey 2 circuits onto one). The split between parallel circuits is predicted by the model from LTDS impedances, not given. This is the strongest available test of the LTDS parameters and assumption A01.
- **The grid-transformer split** (GT2 on the SUND12 section, GT1/GT3 on SUND11) has biases of opposite sign: GT2 +1.9 MW against GT1/GT3 −0.8 to −0.9 MW. That is consistent with an operational busbar arrangement differing from the assumed closed coupler (A06), plus the import error from §5.
- **`SU33_SU11_1` is flagged, not hidden.** Observation-only evidence fixed before the run showed its P is about 0.25× the transformer it supposedly feeds. The model reproduces the transformer, so the circuit meter disagrees. It remains unresolved.

## 3. Current validation (separate; no direction inferred)

| Circuit | n | MAE (A) | RMSE (A) | Bias (A) | r | NMAE |
|---|---|---|---|---|---|---|
| SU33_SU11_2 (current only) | 200 | 2.96 | 3.89 | +1.22 | 0.959 | 0.070 |

Figure: [`figures/e2_current_validation.png`](figures/e2_current_validation.png).

Simulated |I| at the metered end is compared with the observed magnitude. The other current-only series are primary-transformer currents, and those are model **inputs**.

## 4. Diagnostic scenarios (V1: residual placed at candidate nodes)

| Circuit | r V0 | r V1 tee nodes | r V1 LBUZ busbars |
|---|---|---|---|
| SUG1_SUG1_1 / _2 / _3 | 0.870 / 0.856 / 0.868 | 0.957 / 0.920 / 0.966 | same |
| SU33_LBUZT_1 | **0.986** | 0.903 | 0.651 |
| SU33_LBUZT_2_(1) | **0.941** | 0.533 | 0.741 |
| SUND_LBUZ_3(1) | 0.879 | 0.879 | 0.592 |

Closing the import gap improves the GT split, but **putting the residual on the Leighton Buzzard group (at either candidate location) degrades the circuits there.** The unobserved residual is therefore **not** an injection on the LBUZ tee circuits. The next section shows where it comes from.

## 5. Planning vs operational topology and measurement diagnostics

Full list: [`tables/e2_topology_diagnostics.csv`](tables/e2_topology_diagnostics.csv).

1. **The battery-customer circuit is inconsistent with the import meters.**
   - `lne_SUND_CHAP` (SUND31→CHAP31, the customer node "EPN 0272", 0.3 km) swings between **−63.4 and +63.8 MW**. That exceeds its LTDS rating of 38.3 MVA in 1,787 half-hours, and exceeds 1.5× the rating in 272.
   - The data-only residual (import − Σ observed nodal demand) correlates with this flow at **r = −0.70 with slope −0.34 at night (22–03 UTC, when PV is exactly zero)**, and −0.69 / −0.37 at midday.
   - So only about two thirds of the swings metered on this circuit appear in the independently metered import.
   - Possible explanations: a metering/scaling error on this circuit; the battery being split across this circuit and an unpublished path; or the LTDS rating being outdated. **This is the dominant source of the import and GT-split error.** Because the circuit is an input, it also inflates simulated loading on `lne_SUND_CHAP`, up to 171%.
2. **Battery attribution conflict across datasets.**
   - The ECR (49.5 MW storage) gives the Leighton Buzzard site FLOC.
   - LTDS Table 5 lists 52.1 MVA storage at "Sundon 33kV".
   - The operational data and the ECR coordinates (beside Sundon substation) point to `lne_SUND_CHAP`.
3. **Composite metered circuit.** `SU33_LBUZT_2_(1)` is one meter covering the LTDS sections `_(5)` + `_(6)`, with customer tees GFSF31/MFES31 in between. Its validation is good (r = 0.94), but it is published in only 12 of 37 months.
4. **Index/LTDS node mismatch.** The operational index puts `SU33_SU11_4` at the nonexistent node SUND30. The circuit is used only as an input (via its LTDS name).
5. **Possible outages, which the planning model can't represent.** `CHAU_SU33_1` reads |P| < 0.05 MW in 5 of 193 sampled states while the all-closed model carries 3–4 MW. In the same states `SU33_CHAU_2` reads higher than the model. That is consistent with Chaul End T1's circuit being out, with load carried through the shared 11 kV busbar. These states were **not** removed and no topology was changed ad hoc.
6. **Duplicate-looking LTDS records:** `SU33_LBUZT_1_(3A)` / `(3B)` (see E1 §4).
7. **The observation-only power balance at the Sundon 33 kV busbar closes:** median +1.6 MW, p05/p95 −5.7 / +12.1 MW, n = 5,400. This uses Sundon T2's P as a proxy for the current-only `SU33_SU11_2`. The wide tails coincide with battery activity.
8. **The PV signature is small.**
   - With the battery idle (|CHAP| < 2 MW), the residual at midday is **−1.2 MW relative to night in May–Aug** and +0.4 MW in Nov–Feb.
   - During the validation window the ECR lists about 26 MW of connected 33 kV PV (6 MW since 2015, plus 20 MW with no connection date; the 15 MW farm only from Feb 2026).
   - The observed midday dip is far smaller than that capacity implies. Possible reasons: curtailment (the 20 MW farm has a flexible/ANM connection), the farm not generating in 2024, or a connection outside this measurement envelope. **Unresolved.**

**No operational-topology adjustment was implemented.** The evidence above can justify future, explicitly configured scenarios: coupler open at 132 kV, the Chaul End T1 outage, and a corrected battery-circuit scaling. Any of these must be added as named configurations, not hidden patches.

## 6. What this means for the satellite/GENCO experiment

- **Network credibility: adequate for scenario studies (B).**
  - The topology, impedances and observed loads reproduce 33 kV flows to about 5–10% NMAE with correct direction.
  - Two independent AC solvers (pandapower and datakit/PowerModels) agree, and the OpenGridFM export loads in graphkit.
- **The limits matter scientifically.**
  - The battery-customer meter inconsistency means the **unobserved/uncertain 33 kV injection is the largest error term** (import RMSE 8.1 MW).
  - The observed PV footprint in Sundon's measurements is **small** (about 1–2 MW at summer midday).
  - The four major farms lie within about 4 × 4 km.
  - Together these make **H2 (spatial structure) weak on Sundon**, and observed-data validation of satellite-driven PV states will be hard.
  - Synthetic satellite-driven scenarios on this network remain technically feasible: the model accepts PV injections at its nodes, and GENCO can consume the export.
- **Results from any later stage on Sundon must be accompanied by** the battery-meter inconsistency, the small observed PV footprint, the narrow (mostly 2024) validated window, and the planning-topology caveats.

## Attribution

Contains UK Power Networks data licensed under CC BY 4.0. The datasets used are LTDS Tables 1, 2a, 3a and 5; Grid and Primary Sites; the Embedded Capacity Registers; the 132 kV and 33 kV (EPN) circuit operational data; and the grid and primary transformer power-flow data.

Site coordinates contain Ordnance Survey data © Crown copyright and database right [2019-], and Office for National Statistics data under the Open Government Licence v3.0.

Derived tables in `reports/` contain no customer-identifying ECR fields.
