# E4-B/C: weather-driven Sundon states against synthetic and matched controls

_6 October 2026. Pre-registered in [`configs/experiments/e4_matched_control.yaml`](../configs/experiments/e4_matched_control.yaml) (commit `6ebb60e`). GENCO is zero-shot; no weights change._

To reproduce:

```bash
uv run --env-file .env python scripts/build_weather_scenarios.py     # S1, S1_BASE_LTDS, E4D_TIMELINE
uv run --env-file .env python scripts/build_matched_controls.py      # S2, 10 seeds
uv run python scripts/run_genco_e4.py predict --family <family>      # each family
uv run --env-file .env python scripts/evaluate_e4.py
```

Outputs:
- [`tables/e4_generalisation_gaps.csv`](tables/e4_generalisation_gaps.csv)
- [`tables/e4_seed_gaps.csv`](tables/e4_seed_gaps.csv)
- [`tables/e4_conditioning.csv`](tables/e4_conditioning.csv)
- [`tables/e4_family_summary.csv`](tables/e4_family_summary.csv)
- [`figures/e4_family_distributions.png`](figures/e4_family_distributions.png)

## Answer

- **No material weather gap. D applies, after B.**
  - On the primary metric (PBE Mean), real satellite-driven states (S1) and the stratified PV–load reassignment control (S2, 10 seeds) differ by **−0.0001 MVA** (−0.0002%, 95% CI −0.0045 to +0.0039 MVA).
  - That is the size of GPU run-to-run noise. All 10 control seeds agree.
- **The result is uninformative about weather *in principle*, because topology dominates.**
  - GENCO's error on every Sundon family is a nearly constant structural floor: PBE about 49 MVA and an active residual about 300× DC-PF ([`e4_zero_shot.md`](e4_zero_shot.md)).
  - Satellite-driven PV moves the state by at most a few MW. Its effect on per-state error is about 1.5% across capacity-factor quartiles.
- **S1 against conventional synthetic (S0)** is mixed: lower voltage and angle errors, a higher reactive residual, and PBE +8% (not material).
  - S0 and S1 differ in load level, N-1 topologies and admittance perturbation as well as weather.
  - This is reported as operating-distribution generalisation, **not** a weather effect.

## 1. Population (exact)

| Family | Generated | AC-converged | Rejected (reason) | Accepted | Days |
|---|---|---|---|---|---|
| S1_WEATHER_ALIGNED | 2,829 | 2,829 | 0 | **2,829** | 136 |
| S1 on preserved `sundon_base_ltds` | 2,829 | 2,829 | 0 | 2,829 | 136 |
| S2_MATCHED_PV_CONTROL, each of 10 seeds | 2,828 | 2,828 | 0 | **2,828** (28,280 total) | 136 |
| S0_STANDARD_SYNTHETIC | 2,671 (of 2,838 requested) | 2,671 | 374 (`voltage_sanity`, Vm < 0.8 pu) | 2,297 | — (129 load blocks) |

**Primary timestamps:**
- They are half-hours T in 2024-04-01 → 2024-09-30 where both (a) satellite slot T is usable under E3 QC, with every active asset GOOD, and (b) every E2 base-state input is present.
- 4,148 usable satellite half-hours exist, of which 31.8% lack an E2 input. That leaves **2,829**.
- **No E3 events, no visual selection and no 15-minute interpolation** were used.

**Timestamp convention:**
- UKPN half-hourly values are 30-minute averages labelled by **period start**. Every month runs from day 1 00:00 to the last day 23:30.
- Half-hour T is paired with satellite slot T, which is acquired over Sundon at T + 11.6 min, inside [T, T + 30).

**S2 exclusions:** each seed excludes one base half-hour whose (month, UTC time-of-day) stratum has a single member and cannot be deranged.

**AC gates** (every family):
- pandapower and PowerModels both converge;
- balance mismatch ≤ 1e-3 MVA;
- 0.8 ≤ Vm ≤ 1.2 pu;
- the two solvers disagree by ≤ 1e-3 pu.

**Family-specific rejection:** only S0 has rejections. 14% of its states are rejected for low voltage, a property of datakit's heavy load scaling.

## 2. Construction (as documented; nothing redesigned)

- **S1:** the E2 base state B(T) under the recommended interpretation, plus the 6 MW 33 kV farm's satellite PV at slot T, injected explicitly. The 2.9 MW embedded at ≤11 kV stays inside the observed loads and is not double-counted. Only capacity active in 2024 is used (8.945 MW).
- **S2 ("stratified PV–load reassignment control"):** the same B(T), with the full PV vector of a donor slot T′ from **another day** in the same (calendar month, UTC time-of-day) stratum.
  - HV PV comes from T′.
  - Embedded PV is grossed up at T and replaced by T′.
  - Donors are a random **derangement** within each stratum, so the PV marginal is preserved **exactly** per stratum.
  - Seeds 101–110 are stored in [`experiments/e4/families/S2_donors.parquet`](experiments/e4/families/S2_donors.parquet).
  - **What it tests:** whether the *joint* relation between this real electrical state and its own real weather changes what GENCO sees.
  - **What it doesn't test:** temporal order. GENCO is steady-state, and reordering an unchanged set of states cannot change its per-state errors.
- **No spatial shuffle.** Sundon's 2024 ≥1 MW PV sits in one native pixel, so **H2 is not evaluated on Sundon**. It belongs to Canterbury South.

## 3. Results by family

Means [95% day-block bootstrap CI]; B = 2,000, seed 20261006.

| Family | PBE Mean (MVA) | PBE Max | Active res. (MW) | Reactive res. (MVAr) | Vm MAE (pu) | Va MAE (°) | Branch P MAE (MW) | Branch Q MAE (MVAr) | DC-PF active (MW) |
|---|---|---|---|---|---|---|---|---|---|
| S0 synthetic | 45.29 [42.43, 48.23] | 2,757 | 33.65 | 24.91 | 0.0373 | 7.10 | 29.31 | 21.05 | 0.225 |
| **S1 weather** | **48.988** [48.910, 49.061] | 767 | 28.895 | 34.987 | 0.02371 | 2.631 | 25.042 | 22.956 | 0.0978 |
| S1, base_ltds | 48.934 [48.850, 49.016] | 859 | 28.907 | 34.915 | 0.02386 | 2.646 | 25.103 | 22.956 | 0.0979 |
| **S2 control (10 seeds)** | **48.988** [48.911, 49.061] | 768 | 28.895 | 34.987 | 0.02371 | 2.632 | 25.042 | 22.956 | 0.0978 |
| S2 per seed (min – max) | 48.9876 – 48.9891 | | 28.8949 – 28.8960 | | | | | | |

The max loading error is about 2,700% of rating in every Sundon family. It comes from GENCO's flows on low-impedance branches and is not meaningful as a distribution comparison ([`e4_zero_shot.md`](e4_zero_shot.md) §5).

## 4. Generalisation gaps (S1 − control)

**Material** = |relative| ≥ 10% and the difference CI excludes 0 (pre-registered).

| Metric | vs S0 synthetic: Δ (rel.) [95% CI of rel.] | Material | vs S2 matched (paired): Δ (rel.) [95% CI of rel.] | Material |
|---|---|---|---|---|
| **PBE Mean** | +3.70 MVA (+8.2%) [+1.8%, +15.4%] | no | **−0.0001 MVA (−0.0002%) [−0.009%, +0.008%]** | **no** |
| Active residual | −4.76 MW (−14.1%) [−20.1%, −7.3%] | yes | −0.00002 MW (0.000%) | no |
| Reactive residual | +10.08 MVAr (+40.5%) [+32.8%, +49.0%] | yes | −0.00007 (0.000%) | no |
| Vm MAE | −0.0136 pu (−36.5%) [−38.1%, −34.8%] | yes | +0.000001 (+0.006%) | no |
| Va MAE | −4.47° (−62.9%) [−63.9%, −62.0%] | yes | −0.0003° (−0.012%) | no |
| Branch P MAE | −4.27 MW (−14.6%) [−17.9%, −10.9%] | yes | +0.0005 MW (+0.002%) | no |
| Branch Q MAE | +1.90 MVAr (+9.0%) [+6.1%, +12.3%] | no | +0.0004 (+0.002%) | no |

**Across the 10 S2 seeds:** the relative PBE gap ranges from −0.0019% to +0.0012%. No seed is a "lucky permutation"; all agree.

**Reading:**

- **S1 vs S2: weather organisation does not change GENCO's steady-state accuracy on Sundon.** The precision is very high (CI about ±0.01%), but the comparison sits on a topology error floor that swamps any PV effect.
- **S1 vs S0** answers a different question: real Sundon operation against conventional synthetic perturbation.
  - GENCO's voltage and angle errors are much lower on real states, which are lighter (about 40–60 MW), intact and unperturbed. Its reactive residual is higher.
  - These differences reflect load level, N-1 and admittance perturbations, as well as PV. They are **not** a weather effect.

## 5. Conditioning on pre-registered weather variables (S1)

PBE Mean (MVA) by quartile; bins and variables were fixed before any GENCO result.

| Variable | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|
| Fleet capacity factor | 49.37 [49.22, 49.53] (cf 0.00–0.21) | 49.12 | 48.82 | 48.64 [48.47, 48.80] (cf 0.72–1.00) |
| Clear-sky index | 49.01 (kc 0.08–0.52) | 48.91 | 48.89 | 49.15 (kc 1.08–1.84) |
| HV ramp vs previous 15 min | 48.93 (0–0.14 MW) | 49.04 | 49.07 | 48.85 (0.54–4.4 MW) |

- More PV slightly *lowers* GENCO's error, by 1.5% from lowest to highest capacity-factor quartile, with separated CIs.
- Ramp magnitude does not raise the steady-state error.
- The clear-sky index carries the known E3 limitation (about 1.16 on clear days); it is not recalibrated.

## 6. Sensitivities and robustness

| Check | Result |
|---|---|
| Normalizer fitted on S1 itself (official per-dataset protocol) instead of fixed S0 | PBE Mean **200.9** (vs 49.0) and active residual 175.6 MW. Errors are 4× worse, but the Va MAE falls to 0.80°. Results depend strongly on the per-unit scale; the verdict is unchanged (still ≫ DC-PF) |
| Preserved `sundon_base_ltds` reference instead of the recommended interpretation | PBE 48.93 vs 48.99. The interpretation does not matter for GENCO here |
| Repeat inference (GPU) | family-mean PBE changes by 4 × 10⁻⁶, the same order as the S1−S2 difference |

## 7. Verdict for E4-B/C

- **B (topology shift dominates):** yes. GENCO is 150–300× worse than DC-PF on every Sundon family.
- **D (no material weather gap):** yes, after B. Real weather organisation (S1 vs S2) has no detectable effect.
- **Caveat:** this does **not** show that GENCO is robust to weather in general. It shows that, zero-shot on an unseen topology, the topology error is so large that no weather signal is visible. The weather question must be re-asked after E5 topology adaptation.

## Attribution

UK Power Networks data (CC BY 4.0). EUMETSAT LSA SAF MDSSFTD, LSA-207 (CC BY 4.0). GENCO checkpoints `gridfm/genco-pf-transfer` (Apache-2.0).
