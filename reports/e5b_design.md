# E5b design: broad physics-informed synthetic envelope (pre-registration)

_7 October 2026. Written and committed before any E5b data generation or training._
- Parents: E4 `0f3101b`; E5 `acda62c` (D — OTHER; [erratum](e5_verdict_erratum.md)).
- Configs:
  - [`configs/experiments/e5b_operating_envelope.yaml`](../configs/experiments/e5b_operating_envelope.yaml): the envelope;
  - [`configs/experiments/e5b_adaptation.yaml`](../configs/experiments/e5b_adaptation.yaml): the protocol, gates, transfer criterion and verdicts.

## Question and hypothesis

- **Hypothesis under test:** E5 failed on real states mainly because its synthetic operating envelope did not cover realistic Sundon operation.
- **Question:** if GENCO is adapted on synthetic Sundon states covering the physically plausible operating envelope — with no real 2024 state, satellite or weather information in training or selection — does it generalise to the real 2024 states?

## What changes from E5, and what doesn't

**Only datakit's load-scenario generator changes.** Everything else is held constant:
- network file (E1 case + A1 slack limits);
- N-1 topology variants (22 per load scenario);
- admittance perturbation σ 0.2;
- OPF/PF solves, DC baseline and AC gates;
- GENCO checkpoint, official fine-tuning recipe and normalizer rule;
- ladder, seeds, splits and selection rule.

So E5 vs E5b isolates the operating envelope.

| | E5 (datakit `agg_load_profile`) | E5b (envelope) |
|---|---|---|
| Demand | one global multiplier on the planning case, 1.2–2 × peak (feasibility-scaled) | per-site net demand from min(0, LTDS published minimum-load factor) to max(winter MD, 2029/30 forecast MD) |
| Variation | one profile × ±20 % node noise | global level + site deviation (±0.15) + node-share jitter (±10 %), pf from the LTDS range |
| CHAP31 (battery customer) | 0 always | ±49.5 MW (ECR row 447 registered / export capacity), 20 % idle mode |
| 33 kV generation (LBUZ31/32/33) | 0 always | 0 → 7.5 MW: ECR rows 955 (6 MW solar, 2015) and 187 (1.5 MW wind, 2014), equal split |
| Sampled total net load | about 106–142 MW | about −54 to +167 MW (median 56) |

## Per-element bounds (static sources only)

Full table: [`tables/e5b_operating_envelope.csv`](tables/e5b_operating_envelope.csv).

| Element | Min (MW) | Max (MW) | Source |
|---|---|---|---|
| CHAU51 / CHAU52 | 0 | 26.3 / 11.0 | LTDS 3a Chaul End: winter MD 31.3, 2029/30 forecast 37.3, min-load 25.6 % (→ 0); E1 node shares |
| LBUZ51 / LBUZ5A | 0 | 22.9 / 12.1 | LTDS 3a Leighton Buzzard: 30.0, 35.0, 23.8 % |
| LEWS51 | 0 | 16.4 | LTDS 3a Lewsey: 15.5, 16.4, 29.3 % |
| SUPR52 / SURP5A / SURP5B | −0.45 / −0.39 / −0.39 | 12.2 / 10.6 / 10.6 | LTDS 3a Sundon Primary T1&T2 + T3&T4: 12.5, 33.4, **−9.8 %** (LTDS publishes net export) |
| LBUZ31/32/33 generation | 0 | 2.5 each | ECR 33 kV, connected on or before 2024-09-30 (E3 capacity rule) |
| CHAP31 storage | −49.5 | +49.5 | ECR 49.5 MW; LTDS T5 52.1 MVA = 49.5 / 0.95 |
| every other node | 0 | 0 | no load or generation in the planning case or registers |

**Documented choices:**
- **Assets left out:** the undated 20 MW solar and the 2026 15 MW solar fail the E3 dated-assets rule.
- **Circuit rating not imposed:** the CHAP31 circuit rating (38.3 MVA) is not applied; the AC gates decide feasibility.
- **Power factor:** generation and storage run at unity.
- **Independence:** demand, solar, wind and battery are sampled independently; no time or weather structure is imposed.

## Leakage controls (enforced in code and tests)

- **Envelope reads are restricted** to the files in `ALLOWED_SOURCES`:
  - LTDS 3a;
  - the study-region asset register;
  - the envelope config.

  Any other read raises an error. The source of `envelope.py` contains no access path to UKPN time series, S1/S2, satellite or event data ([`tests/satellite/test_e5b.py`](../tests/satellite/test_e5b.py)).
- **Training data** must be `data/interim/e5b/synthetic`, with an E5b manifest and seeds disjoint from E4/E5.
- **Real populations are refused** by the training/predict code until `metadata/e5b_checkpoint_registry.yaml` is frozen and lists the run.
- **Checkpoint selection** uses the E5b validation pool only; there is no real-state validation set.
- **Normalizer:** graphkit `fit_on_train` on each run's E5b training split, stored with the checkpoint, and used unchanged on real states.

## Pre-registered decisions

- **Ladder:** 100 / 1k / 10k (seeds 0, 1, 2) and 50k (seed 0), ascending. The E5 saturation rule applies; optional 10k from-scratch after the main ladder.
- **Pools:** test seeds 7000–7002, validation 7100–7109, train 8000–8069 (extended if fewer than 50,000 accepted). The E5 held-out test is also scored, for retention.
- **Synthetic gate (E5 gate):**
  - PBE ≤ 10 % of zero-shot;
  - active residual ≤ 10 % of zero-shot;
  - import sign ≥ 99 %;
  - active residual ≤ 5× DC-PF.
- **Selection:** among gate-passing runs (all runs if none pass, flagged), lowest PBE on the full validation pool, ties → smaller N. Then freeze and commit before any real-state inference.
- **Real-transfer success** (S1, frozen checkpoint, set before any E5b result; all four required):
  - R1: active residual ≤ 2.885 MW (10 % of E5);
  - R2: PBE mean ≤ 3.318 MVA and 95th percentile ≤ 10 MVA;
  - R3: import sign ≥ 99 %, MAE ≤ 5 MW, r ≥ 0.9, spread ratio 0.75–1.33;
  - R4: voltage tracking r ≥ 0.8 and Vm MAE ≤ 0.01 pu.
- **Partial transfer:** active residual and PBE each ≤ 50 % of E5, and import r ≥ 0.5.
- **Verdicts:**
  - **E5B-A:** success;
  - **E5B-B:** neither success nor partial;
  - **E5B-C:** partial, or no run passes the synthetic gate.
- **Coverage hypothesis:**
  - **SUPPORTED** = E5B-A;
  - **NOT SUPPORTED** = E5B-B with ≥ 95 % of S1 states inside the E5b training range on every coverage variable;
  - otherwise **INCONCLUSIVE**.
- **Weather, ramps and heroes run only after transfer succeeds.** Ramps are judged on absolute transition error **and** tracking ratio.
