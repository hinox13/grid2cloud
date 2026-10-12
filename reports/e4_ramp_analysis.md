# E4-D: ramp and trajectory analysis (15-minute satellite timeline)

_6 October 2026. Pre-registered in [`configs/experiments/e4_ramp_analysis.yaml`](../configs/experiments/e4_ramp_analysis.yaml) (commit `6ebb60e`)._

Outputs:
- [`tables/e4_ramp_conditioned.csv`](tables/e4_ramp_conditioned.csv)
- [`tables/e4_transitions_by_event.csv`](tables/e4_transitions_by_event.csv)
- [`figures/e4_ramp_conditioned.png`](figures/e4_ramp_conditioned.png)
- `figures/e4_hero_*.png`
- [`experiments/e4/hero/`](experiments/e4/hero/) (UI-ready CSVs)

## Answer

- **GENCO under-tracks weather-driven network changes, and the deficit grows with ramp size.**
  - In within-half-hour transitions (load held, PV the only change), the median branch-flow tracking ratio Σ|ΔP_GENCO| / Σ|ΔP_AC| falls from about 1.1 for the smallest ramps to **0.62, 0.50 and 0.46** for medium, high and extreme ramps.
  - So for large ramps GENCO reproduces about half of the true change in branch flows.
  - Its voltage-change error is about as large as the true voltage change: ΔVm error 3.9e-4 pu against a true 4.3e-4 pu in the extreme bin.
- **Steady-state error does not rise with ramp size** (end-state PBE 48.7–49.1 across bins). The weakness is in *tracking the response*, which the steady-state comparison of E4-B/C cannot see.
- All of this sits on the topology failure of [`e4_zero_shot.md`](e4_zero_shot.md). It describes zero-shot behaviour on an unseen network, not a weather-specific defect that could be separated from topology.

## 1. Timeline and transitions

**Timeline:** every usable 15-minute slot (E3 QC) whose half-hour base is complete.
- 5,667 states on 136 days, all passing the AC gates.
- Slots at :15 and :45 share their half-hour's averaged load; there is no interpolation.

**Transitions:** 5,396 consecutive 15-minute pairs.
- 2,739 are **within the half-hour** (primary: load identical, so the change is the injected PV only).
- 2,657 cross a half-hour boundary, where load also changes.
- 2 pairs change branch set (an observed outage starts or ends); their branch metrics are excluded.

**Ramp bins:** quantiles 0 / 50 / 80 / 95 / 100% of |ΔPV_injected| over primary transitions, fixed before results.

## 2. Ramp-conditioned tracking (within-half-hour transitions)

Means per transition; 95% day-block CI for branch P.

| Bin | n | \|ΔPV\| (MW) | AC \|ΔP\| per edge (MW) | GENCO ΔP error (MW) | Median tracking ratio | AC \|ΔVm\| (pu) | GENCO ΔVm error (pu) | GENCO ΔVa error / AC \|ΔVa\| (°) | End-state PBE |
|---|---|---|---|---|---|---|---|---|---|
| low | 1,370 | 0.00–0.33 | 0.020 | 0.031 | 1.14 | 3.0e-5 | 2.8e-5 | 0.0083 / 0.0090 | 48.93 |
| medium | 821 | 0.33–0.67 | 0.062 | 0.057 | 0.62 | 9.5e-5 | 8.6e-5 | 0.026 / 0.028 | 49.08 |
| high | 411 | 0.67–1.40 | 0.130 | 0.106 | 0.50 | 2.0e-4 | 1.8e-4 | 0.055 / 0.059 | 48.96 |
| extreme | 137 | 1.41–4.20 | 0.277 | **0.210** [0.200, 0.221] | **0.46** | 4.3e-4 | 3.9e-4 | 0.116 / 0.126 | 48.75 |

Exact values, including the ΔQ column, are in the CSV.

- **Crossing half-hour boundaries** (load also changes): the true mean |ΔP| per edge is 0.73 MW and GENCO's ΔP error is 0.81 MW. The error exceeds the true change, so the predicted change is largely wrong in direction or distribution.
- **Interpretation.** GENCO's outputs respond to the input change, but only partially, and its voltage-magnitude and angle responses are close to absent: errors are about 90% of the true changes. A per-state accuracy metric hides this: at a near-constant 49 MVA error floor, a missed 4 MW PV ramp is invisible.

## 3. Pre-registered events (E3 frozen; ranking not changed)

| Event | Class | States | Max \|ΔPV\| (MW) | ΔP error (MW) | ΔVm error (pu) | Median tracking ratio | PBE Mean | Vm MAE |
|---|---|---|---|---|---|---|---|---|
| B01 2024-07-07 08:00 | fast ramp | 12 | 4.20 | 0.38 | 8e-4 | 0.57 | 49.11 | 0.021 |
| B02 2024-06-15 08:45 | fast ramp | 12 | 3.96 | 0.59 | 1.5e-3 | 0.83 | 48.99 | 0.024 |
| B03 2024-04-25 10:15 | fast ramp | 12 | 4.10 | 0.32 | 6e-4 | 0.96 | 48.48 | 0.031 |
| C01 2024-04-15 12:15 | broken cloud | 12 | 3.40 | 0.24 | 7e-4 | **0.43** | 49.19 | 0.028 |
| C02 2024-06-10 10:15 | broken cloud | 12 | 2.77 | 1.47 | 3.1e-3 | 0.64 | 48.40 | 0.025 |
| C03 2024-08-20 08:30 | broken cloud | 0 | — | — | — | — | — | — |
| D01 2024-06-15 09:30 | coherent transition | 12 | 3.96 | 0.59 | 1.5e-3 | 0.64 | 49.42 | 0.022 |
| A02 2024-08-23 10:45 | clear control | 12 | 0.00 | 0.48 | 1.4e-3 | 0.80 | 49.77 | 0.020 |
| A03 2024-05-20 10:30 | clear control | 12 | 0.00 | 0.34 | 7e-4 | 1.03 | 48.86 | 0.024 |

- **C03 and A01 are not evaluable.** UKPN Leighton Buzzard primary-transformer data (`LBUZ51`) is missing in their windows, so no E2 base state exists. They are reported, not substituted.
- Event transitions include half-hour crossings, which is why the A-class controls show non-zero ΔP error with ΔPV = 0: load changes between half-hours.

## 4. Hero events

| Hero | Figure | What it shows |
|---|---|---|
| **D01 / B02**: 15 Jun 2024 clearing | [`e4_hero_D01_20240615T0930.png`](figures/e4_hero_D01_20240615T0930.png), [`e4_hero_B02_20240615T0845.png`](figures/e4_hero_B02_20240615T0845.png) | Satellite PV rises from about 2 to 9 MW (6 MW injected at 33 kV) at 11:15. AC import falls from about 54 to 34 MW. **GENCO's predicted import stays flat at −211 MW.** Its PBE stays about 49 MVA against DC-PF residual ≈ 0.1 MW |
| **C01**: 15 Apr 2024 broken cumulus | [`e4_hero_C01_20240415T1215.png`](figures/e4_hero_C01_20240415T1215.png) | Repeated 2–9 MW PV swings; tracking ratio 0.43 (the lowest of all events) |
| **A01**: 16 Sep 2024 clear control | — | **not evaluable** (LBUZ51 data gap) |
| A02: 23 Aug 2024 clear control (added after results, for illustration only; ranking unchanged) | [`e4_hero_A02_20240823T1045.png`](figures/e4_hero_A02_20240823T1045.png) | Flat 8.9 MW PV (clipping). GENCO's errors match the cloudy events: the error is not weather-driven |

Hero CSVs (`experiments/e4/hero/<event>.csv`) carry, per 15-minute state:
- PV (fleet and injected), capacity factor and clear-sky index;
- AC and GENCO import;
- PBE, Vm, Va and branch errors;
- AC maximum loading, loading error and DC residual.

They are ready for the future event bundle.

## 5. Not done (by design)

- No temporal shuffle: GENCO is steady-state, so reordering states cannot change its per-state errors.
- No spatial shuffle (H2 not evaluated on Sundon).
- No overcast class: none qualifies under E3-v1 criteria.
- No counterfactual PV-penetration states.

## Attribution

UK Power Networks data (CC BY 4.0). EUMETSAT LSA SAF MDSSFTD, LSA-207 (CC BY 4.0). GENCO `gridfm/genco-pf-transfer` (Apache-2.0).
