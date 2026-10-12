# E5: topology adaptation, synthetic performance, import diagnostic and normalizer sensitivity

_7 October 2026. Frozen checkpoint `ft_n50000_s0` (commit `61a4fbd`); learning curve in [`e5_learning_curve.md`](e5_learning_curve.md)._

To reproduce (after freezing):

```bash
uv run python scripts/finetune_genco_e5.py predict --run ft_n50000_s0 --target <family> [--normalizer e4_s0|e4_s1own]
uv run --env-file .env python scripts/evaluate_e5.py weather
```

Outputs:
- [`tables/e5_import_diagnostic.csv`](tables/e5_import_diagnostic.csv)
- [`tables/e5_normalizer_sensitivity.csv`](tables/e5_normalizer_sensitivity.csv)
- [`tables/e5_family_summary.csv`](tables/e5_family_summary.csv)
- [`experiments/e5/weather_evaluation.json`](experiments/e5/weather_evaluation.json), [`experiments/e5/verdict.json`](experiments/e5/verdict.json)

## Answer

- **The topology error floor is removed on synthetic Sundon.** On the E4 S0 states, which none of the E5 pools contain:
  - PBE 45.3 → **0.48 MVA**;
  - active residual 33.7 → 0.38 MW (1.7× DC-PF, from 149×);
  - voltage tracking per bus r −0.19 → 0.93.
- **It is not removed on real Sundon operating states.**
  - On S1 the active residual stays at **28.8 MW (295× DC-PF)**, against 28.9 MW zero-shot. PBE falls from 49.0 to 33.2 MVA (median 7.1), with a heavy tail.
  - Voltage tracking gets worse (per-bus r 0.40 → −0.34).
- **Cause: the real states lie outside the synthetic support.** This is neither topology nor weather. datakit perturbs the planning case multiplicatively, so:
  - every 11 kV primary load in S1 is below the synthetic minimum, in ≥ 99.8 % of states;
  - the 33 kV customer node `CHAP31` swings between −24 and +21 MW in S1 but is fixed at 0 in all synthetic data;
  - the PV-export nodes `LBUZ31/32/33` (−2 to −0.1 MW in S1) are also fixed at 0;
  - synthetic total load is 106–142 MW, real total load −3 to 113 MW.
- **REF import:**
  - The sign is now correct (99.9 % of S1 states).
  - The magnitude collapses towards the training mean: about 116 MW predicted against 49 MW in AC, MAE 71 MW, correlation 0.12.
- **Normalizer sensitivity remains extreme.** The S1-own base (24.5 MVA) gives PBE 1,349 MVA, against 201 zero-shot. The E4 S0 base (116 MVA), close to the model's own 113.8, changes little.

## 1. Synthetic held-out performance

Means. DC-PF is on the same states.

| Population | Model | PBE Mean (MVA) | PBE Max | Active res. (MW) | ×DC | Reactive res. (MVAr) | Vm MAE (pu) | Va MAE (°) | Branch P / Q MAE |
|---|---|---|---|---|---|---|---|---|---|
| E5 held-out test (2,256) | zero-shot | 44.80 | 4,160 | 32.85 | 146 | 25.32 | 0.0376 | 7.09 | 28.7 / 21.5 |
| | **adapted** | **0.47** | 16.2 | **0.38** | **1.7** | 0.20 | 0.0092 | 0.81 | 1.60 / 0.68 |
| | DC-PF | – | – | 0.225 | 1 | – | – | – | – |
| E4 S0 states (2,297) | zero-shot (E4) | 45.29 | 2,757 | 33.65 | 149 | 24.91 | 0.0373 | 7.10 | 29.3 / 21.1 |
| | **adapted** | **0.48** [0.47, 0.50] | 16.0 | **0.38** | **1.7** | 0.21 | 0.0095 | 0.84 | 1.62 / 0.69 |

**Per-state view (E4 S0 states):**
- 94 % of adapted states have PBE < 1 MVA;
- 99.6 % are within 5× DC-PF;
- under zero-shot, none were.

## 2. REF/slack import diagnostic

REF-bus Pg, GENCO against AC.

| Population | Model | Sign correct | MAE (MW) | r | Dynamic range (σ_pred/σ_AC) | Mean AC → GENCO (MW) |
|---|---|---|---|---|---|---|
| held-out synthetic test | zero-shot | 0.0 % | 331.6 | 0.02 | 4.30 | – |
| | adapted | 100 % | 8.1 | 0.42 | 1.22 | – |
| E4 S0 | zero-shot | 0.0 % | 330.2 | −0.03 | 4.43 | 123.8 → −206.4 |
| | adapted | 100 % | 8.3 | 0.44 | 1.24 | 123.8 → 125.9 |
| **S1 weather** | zero-shot | 0.1 % | 260.0 | 0.05 | 0.23 | 48.6 → −211.4 |
| | **adapted** | **99.9 %** | **70.7** | **0.12** | **17.7** | 48.6 → **116.4** |
| S2 control | adapted | 99.8 % | 68.2 | 0.14 | 13.0 | 48.6 → 114.0 |
| E4D timeline | adapted | 99.9 % | 70.6 | 0.12 | 17.8 | 48.6 → 116.4 |

**The three E4 symptoms:**
- **Wrong import sign:** fixed everywhere.
- **Near-constant −211 MW import:** gone, but on real states it is replaced by an import centred near the *synthetic* operating point (about 116 MW). Its spread is dominated by a heavy tail of extreme predictions (dynamic range 17.7).
- **Weak voltage tracking:** fixed on synthetic data (r 0.93) but not on real data (S1 r −0.34).

## 3. Why real states fail: support gap, not topology or weather

| Quantity | Synthetic training pool | S1 real states |
|---|---|---|
| Total load | 106–142 MW | −3 to 113 MW (median 49) |
| 11 kV primary loads (8 buses) | 1.2–2 × planning peak | below the synthetic minimum in ≥ 99.8 % of states |
| `CHAP31` (33 kV customer) | 0 (planning case: unobserved customer = 0) | −24 to +21 MW |
| `LBUZ31/32/33` (33 kV, embedded / PV export) | 0 | −2.0 to −0.1 MW |
| Buses with negative net load | 0 % | 9.3 % |

**The error follows the distance from the training support:**
- S1 states with load ≤ 55 MW have PBE about 7–8 MVA.
- The top load quintile (61–116 MW) has 127 MVA.
- By number of negative-injection nodes: states with 3 have PBE 50, states with 4 have 7.5.

**Why the synthetic data can't reach these states:**
- datakit's `agg_load_profile` multiplies each bus's planning-case load by a scaling factor and noise.
- A bus that is 0 in the planning case stays 0.
- No bus can ever export.

**Representation:**
- On synthetic data the Sundon-site share of PBE falls from 91 % to 16 % after adaptation.
- On S1 the Sundon-site buses still hold 54 % of the adapted error (zero-shot 94 %); the LBUZ nodes hold 18 % and `CHAP31` 5 %.
- Reading: the out-of-support inputs produce angle inconsistencies, and the stiff near-zero-Z branches still amplify them into power-balance error on real states.
- The merged graph was rejected on AC-equivalence grounds ([`e5_representation_sensitivity.md`](e5_representation_sensitivity.md)), so no merged cells were run.

## 4. Normalizer sensitivity after adaptation (reported only; nothing chosen from it)

| Model | Normalizer (base MVA) | Synthetic test PBE / active res. | S1 PBE / active res. |
|---|---|---|---|
| zero-shot | E4 fixed S0 (116.0) | 44.8 / 32.9 | 49.0 / 28.9 |
| zero-shot | E4 S1-own (24.5) | 429.3 / 356.1 | 200.9 / 175.6 |
| adapted | **own train-fitted (113.8), primary** | **0.47 / 0.38** | **33.2 / 28.8** |
| adapted | E4 fixed S0 (116.0) | 0.48 / 0.38 | 32.3 / 28.1 |
| adapted | E4 S1-own (24.5) | 1,310 / 1,260 | 1,349 / 1,292 |

- **E4's sensitivity is still there, and stronger.** A per-unit base 4.6× smaller multiplies the adapted error by about 40× (zero-shot: 4×).
- Bases near the training base are harmless, so the training-fitted base must travel with the checkpoint, as pre-registered. Re-fitting a normalizer on the target data, as in the official zero-shot protocol, is not safe after adaptation.

## Attribution

UK Power Networks data (CC BY 4.0). EUMETSAT LSA SAF MDSSFTD, LSA-207 (CC BY 4.0). GENCO `gridfm/genco-pf-transfer` (Apache-2.0).
