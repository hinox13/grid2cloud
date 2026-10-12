# E5: weather generalisation after topology adaptation (E4 repeated exactly)

_7 October 2026._
- Frozen checkpoint `ft_n50000_s0`, selected on synthetic validation only and committed in `61a4fbd` **before** any weather inference.
- Pre-registration: `cb5b11d`.

To reproduce:

```bash
uv run --env-file .env python scripts/evaluate_e5.py weather
```

Outputs:
- [`tables/e5_family_summary.csv`](tables/e5_family_summary.csv)
- [`tables/e5_generalisation_gaps.csv`](tables/e5_generalisation_gaps.csv)
- [`tables/e5_seed_gaps.csv`](tables/e5_seed_gaps.csv)
- [`tables/e5_conditioning.csv`](tables/e5_conditioning.csv)
- [`tables/e5_scenario_metrics.parquet`](tables/e5_scenario_metrics.parquet)
- [`figures/e5_family_distributions.png`](figures/e5_family_distributions.png)
- [`experiments/e5/weather_evaluation.json`](experiments/e5/weather_evaluation.json), [`experiments/e5/verdict.json`](experiments/e5/verdict.json)

## Answer

- **Weather still makes no measurable difference.** Real satellite-driven states (S1) and the stratified PV–load reassignment control (S2, 10 seeds) differ in PBE by **−0.075 MVA (−0.22 %; 95 % CI of rel. −1.4 % to +0.8 %)**. No core metric is material, and every control seed agrees.
- **But adaptation did not make GENCO accurate on real states**, so this is again **not** evidence of weather robustness.
  - S1 PBE is 33.2 MVA (median 7.1) and the active residual 28.8 MW, against DC-PF 0.098 MW (295×).
  - The topology floor is gone on synthetic data (S0 PBE 0.48). Its place on real data is taken by an **operating-distribution floor**: the real states lie outside the support of the datakit training data ([`e5_topology_adaptation.md`](e5_topology_adaptation.md) §3).
- **Adapted error rises with PV level**: PBE 18.6 MVA in the lowest fleet-capacity-factor quartile against 45.5 in the highest, with separated CIs.
  - S2 has the same PV marginal per stratum and shows the same errors.
  - This is a **PV-injection-level** effect (net export at the PV nodes moves states further from the synthetic support). It is not an effect of the real joint organisation of weather and load.
- **Primary E5 outcome: D — OTHER** (§6). The pre-registered rule as encoded returns A; that encoding is incomplete and its interpretation is contradicted by the data.

## 1. Population (identical to E4)

Only the GENCO weights and normalizer changed. Test `test_e4_and_e5_population_ids_are_identical` checks this.
- Same AC datasets, gate tables and accepted states: S1 2,829; S2 10 × 2,828 with the E4 donor mappings; E4D timeline 5,667; S0 2,297.
- Same day-block bootstrap (B = 2,000, seed 20261006).
- Same materiality rule: |rel| ≥ 10 % and CI excludes 0.

## 2. Results by family

Means [95 % block CI].

| Family | Model | PBE Mean (MVA) | PBE median | PBE Max | Active res. (MW) | Reactive res. (MVAr) | Vm MAE (pu) | Va MAE (°) | Branch P / Q MAE | DC-PF (MW) |
|---|---|---|---|---|---|---|---|---|---|---|
| S0 synthetic (E4 states) | zero-shot | 45.29 [42.43, 48.23] | 39.1 | 2,757 | 33.65 | 24.91 | 0.0373 | 7.10 | 29.3 / 21.1 | 0.225 |
| | **adapted** | **0.48** [0.47, 0.50] | 0.43 | 16 | **0.38** | 0.21 | 0.0095 | 0.84 | 1.62 / 0.69 | 0.225 |
| **S1 weather** | zero-shot | 48.99 [48.91, 49.06] | 49.2 | 767 | 28.90 | 34.99 | 0.0237 | 2.63 | 25.0 / 23.0 | 0.098 |
| | **adapted** | **33.18** [28.21, 38.52] | 7.1 | 9,221 | **28.85** | 12.40 | 0.0316 | 2.88 | 25.7 / 9.1 | 0.098 |
| S1 on `base_ltds` | adapted | 42.65 | | | 37.55 | | 0.0326 | 2.94 | 30.7 / – | 0.098 |
| **S2 control (10 seeds)** | zero-shot | 48.99 | 49.2 | 768 | 28.90 | 34.99 | 0.0237 | 2.63 | 25.0 / 23.0 | 0.098 |
| | **adapted** | **33.26** [28.31, 38.67] | 7.1 | 9,278 | **28.90** | 12.48 | 0.0315 | 2.88 | 25.7 / 9.2 | 0.098 |
| S2 per seed (adapted) | | 33.18 – 33.35 | | | 28.81 – 28.95 | | | | | |

**Notable rows:**
- **Interpretation sensitivity has appeared.** E4's two network interpretations differed by 0.05 MVA; the adapted model gives 33.2 against 42.7. This is consistent with the support gap: the two interpretations distribute measured load differently across nodes. It was not investigated further.
- **Zero-shot rows reproduce E4 exactly.** For example S1 48.987785 and S1−S2 −0.0001 MVA.

## 3. Generalisation gaps (adapted model)

| Metric | S1 − S2 (paired, primary): Δ (rel.) [95 % CI of rel.] | Material | S1 − S0: Δ (rel.) | Material |
|---|---|---|---|---|
| **PBE Mean** | **−0.075 MVA (−0.22 %) [−1.41 %, +0.79 %]** | **no** | +32.7 MVA (×68) | yes |
| Active residual | −0.047 MW (−0.16 %) [−1.2 %, +0.8 %] | no | +28.5 MW (×74) | yes |
| Reactive residual | −0.08 (−0.61 %) [−2.5 %, +1.1 %] | no | ×58 | yes |
| Vm MAE | +0.03 % [−0.02 %, +0.07 %] | no | ×2.3 | yes |
| Va MAE | +0.00 % [−0.42 %, +0.38 %] | no | ×2.4 | yes |
| Branch P MAE | +0.03 % [−0.55 %, +0.66 %] | no | ×15 | yes |
| Branch Q MAE | −0.33 % [−1.4 %, +0.6 %] | no | ×12 | yes |
| Max loading error | −0.06 % [−0.47 %, +0.28 %] | no | ×26 | yes |

**Across the 10 S2 seeds:** the relative PBE gap ranges from −0.48 % to +0.01 %.

**Reading:**
- **S1 − S2** compares the same base load states with the same PV marginal. After adaptation it still shows nothing. The CI is now about ±1 % rather than ±0.01 %, because the adapted model actually responds to PV.
- **S1 − S0 is enormous**, about 70× on PBE. It is an operating-distribution comparison (load level, N-1, admittance perturbation, export nodes), **not** a weather effect. It is the dominant E5 finding.

## 4. Conditioning on the pre-registered weather variables (adapted, S1)

PBE Mean, in MVA:

| Variable | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|
| Fleet capacity factor | **18.6** [13.5, 24.6] (cf 0–0.21) | 27.5 | 41.1 | **45.5** [35.8, 56.7] (cf 0.72–1.0) |
| Clear-sky index | 28.5 | 39.3 | 34.7 | 30.3 |
| HV ramp vs previous 15 min | 31.9 | 32.1 | 32.0 | 39.1 |

- In E4 (zero-shot) more PV slightly *lowered* the error, by 1.5 %. After adaptation more PV raises it by about 2.4×.
- PV lowers net load and creates export at the LBUZ nodes, pushing states further outside the synthetic support. S2 has the same PV distribution and the same error, which is why S1 = S2.

## 5. Operational detection (S1)

| | Zero-shot | Adapted |
|---|---|---|
| Overload (69 true AC overloads) | 69 TP, 2,760 FP | 69 TP, 2,760 FP: unusable |
| Voltage outside ±6 % (417 true) | 0 TP | **331 TP, 86 FN, 265 FP** |

Voltage-limit detection becomes informative but is not reliable; overload detection is unchanged.

## 6. E5 verdict

- **Pre-registered rule as encoded** in `scripts/evaluate_e5.py` (commit `cb5b11d`): gate passed, no material S1−S2 gap, and |1 − ramp tracking| smaller than zero-shot in the high and extreme bins. **It returns A.**
- **Why that is not the outcome:**
  - The specification defines A as *"synthetic topology-only adaptation enables generalisation to real satellite-driven operating states"*. The encoded rule never checked real-state accuracy; that omission is an error in my encoding.
  - The data contradict A's interpretation:
    - the S1 active residual is unchanged (28.85 against 28.90 MW, 295× DC-PF);
    - no S1 state reaches PBE < 1 MVA or ≤ 5× DC-PF, against 94 % and 99.6 % of S0 states;
    - voltage tracking is worse;
    - the ramp "improvement" is an overshoot with a 4× larger absolute transition error ([`e5_ramp_analysis.md`](e5_ramp_analysis.md)).
- **The other outcomes don't fit either:**
  - **B** requires a material S1−S2 gap; there is none.
  - **C** requires poor synthetic held-out performance; it is good (gate passed at 10k and 50k).
- **Primary outcome: D — OTHER.**
  > Topology-only adaptation on standard datakit synthetic data removes GENCO's topology error floor on the synthetic distribution (−99 %, 1.7× DC-PF), but does not transfer to real Sundon operating states, which lie outside the synthetic support (lighter primary loads, a ±24 MW customer node and PV-export nodes that datakit holds at zero). Real weather and matched controls remain indistinguishable, so no weather-specific gap is detected. The weather question is now bounded by an operating-distribution floor, not a topology floor.
- The mechanical rule output (A) and this classification are both recorded in [`experiments/e5/verdict.json`](experiments/e5/verdict.json). Nothing was re-run or re-selected after seeing the weather results.

## Attribution

UK Power Networks data (CC BY 4.0). EUMETSAT LSA SAF MDSSFTD, LSA-207 (CC BY 4.0). GENCO `gridfm/genco-pf-transfer` (Apache-2.0).
