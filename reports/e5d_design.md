# E5d design: physics-response-aware training (pre-registration)

_9 October 2026. Written and committed before any E5d pair generation, training or evaluation._
- Parents: E4 `0f3101b`, E5 `acda62c` (D), E5b `4569a81` (E5B-C), E5c `5bf4f4d` (**E5C-B**, frozen and not modified).
- Starting commit: `7176b91`, with a clean working tree.
- Configs:
  - [`configs/experiments/e5d_response_training.yaml`](../configs/experiments/e5d_response_training.yaml): pairs, loss, λ, runs;
  - [`configs/experiments/e5d_selection.yaml`](../configs/experiments/e5d_selection.yaml): gates, selection, transfer criteria, verdicts, weather rule.
- **E5d is the final planned model-training experiment.** No E5e or further loss search follows automatically, whatever the result.

## Question

> Can physics-response-aware training teach GENCO the correct sensitivity to small generation perturbations while preserving its absolute state accuracy and generalisation to real operation?

The goal is not to fit weather. It is to learn *change in physical input → correct change in electrical state*, from synthetic AC solutions only.

## Why the objective, not the data

E5c already gave GENCO the generator explicitly, over a broad envelope that includes exact-zero and full generation. GENCO fitted the absolute states (held-out PBE 0.61 MVA) but reproduced only about 1.4 % of the AC import response to a PV change, on synthetic paired probes, before any real data entered:

| E5c n10000 (validation probes) | pv | battery | load |
|---|---|---|---|
| import slope ratio, seeds 0 / 1 / 2 | 0.000 / 0.002 / 0.014 | 0.36 / 0.70 / 0.73 | 0.04 / 0.77 / 1.23 |
| branch ΔP error / AC branch ΔP (MW), seed 2 | 0.327 / 0.329 | 0.68 / 1.38 | 3.80 / 0.42 |
| ΔVm error / AC ΔVm (pu), seed 2 | 5.5e-4 / 5.7e-4 | 5.7e-4 / 1.0e-3 | 1.9e-3 / 2.5e-3 |

- 50,000 absolute states did not change this: the E5c 50k pv ratio is 0.004 on the validation probes.
- **Mechanism:** a 1–4 MW PV change moves import by the same amount and voltages by about 1e-4 pu. In the ordinary loss (normalised Vm/Va MSE + physics residual) that is a tiny fraction of the error budget of a state with 50 MW of import.
- **So E5d changes only the objective.** The envelope, representation, absolute data, splits, recipe and normaliser are E5c's.

## Intervention

**L_total = L_original + λ · κ · L_response**
- **L_original:** graphkit's loss, unchanged (0.1 · LayeredWeightedPhysics + 0.9 · MaskedBusMSE).
- **Implementation:** a graphkit plugin task, `PowerFlowResponse`, which subclasses `PowerFlowTask` and runs under the official `gridfm_graphkit finetune` with `--plugins`.
  - It adds no parameter, so checkpoints load into the unchanged `PowerFlow` task for prediction.

### Paired synthetic states (the supervision)

- **Construction:** two AC-solved states on the E1 planning network (the E5c probe network) that differ in exactly one controllable input.
  - **pv:** total LBUZ generation, equal split over the 3 buses.
  - **battery:** CHAP31.
  - **load:** one of the 8 primary loads, power factor kept.
- **Base states:** the E5c envelope sampler (static metadata).
- **Targets:** the AC solutions of both members: Δy = y_AC(B) − y_AC(A). Nothing is assumed to be ±1.
- **Perturbation sizes come from static capacities and envelope bounds, never from 2024 ramps.**
  - **pv** (7.5 MW): small 0.05–0.375, moderate 0.375–1.5, large 1.5–7.5 MW, plus 15 % on/off pairs (exact zero ↔ non-zero).
  - **battery** (49.5 MW): 0.25–2.5 / 2.5–10 / 10–49.5 MW.
  - **load:** 1–5 / 5–20 / 20–60 % of the node's envelope maximum, minimum 0.05 MW.
  - Both directions are used; a direction is flipped or clipped only at a bound.

| Set | Sampler seed | Base states | Pairs (pv / battery / load) | Use |
|---|---|---|---|---|
| train | 9700 | 3,000 | 3,000 each | response loss, scales σ |
| validation | 9800 | 500 | 500 each | best epoch, early stop, LR plateau, response gate |
| test | 9900 | 500 | 500 each | reporting, synthetic part of the verdict |
| E5c probes | 9500 / 9600 | 300 + 300 | 300 each | held out, reporting only |

**Separation:** each base state belongs to exactly one set. Tests check that no base injection vector is shared between E5d sets or with the E5c probes.

### Response loss (exact formula)

Outputs (graphkit's normalised units):
- **REF import:** the decoded Pg at the REF bus;
- **branch P and Q:** sending-end flows of every directed branch, computed with graphkit's `ComputeBranchFlow` from the clamped prediction, as in graphkit's own test/predict;
- **Vm:** buses where it is unknown (PQ);
- **Va:** non-REF buses.

For pair *p* of type *k*, element *j* of output family *o*, and x_p the Δ net withdrawal at the perturbed node (MW):

```text
Δŷ = ŷ(B) − ŷ(A)                (GENCO, gradients through both members)
Δy = y_AC(B) − y_AC(A)
σ_{k,o} = sqrt( mean_{training pairs of type k, elements of o} (Δy / x)² )     # AC, training pairs only
r = (Δŷ − Δy) / (|x| · σ_{k,o})                                              # dimensionless
h_δ(r) = r²/(2δ) if |r| ≤ δ else |r| − δ/2,   δ = 0.1                         # Huber
L_response = (1/3) Σ_k (1/5) Σ_o mean_{pairs in batch of type k, elements of o} h_δ(r)
```

- **Per-unit-perturbation normalisation (÷|x|).** A 0.05 MW PV step counts as much as a 5 MW one, so small perturbations are not numerically ignored. No PV-specific weight is used.
- **Per-family RMS sensitivity (÷σ).** A response-blind model scores |r| ≈ 1 on every family, so import, flows and voltages are commensurable.
- **Huber with bounded gradient.** No single family can dominate through outliers. This matters because the near-zero-impedance branches amplify spurious angle changes into large flow errors: E5c load pairs show 3.8 MW branch ΔP error against 0.42 MW true.
- **Equal balance.** Equal weights over the three perturbation types and five output families. Each step draws 8 pairs of each type.

### κ and λ (fixed now)

- **κ = L̄_orig(E5c) / h_δ(τ):**
  - L̄_orig(E5c) = 0.0035037, the mean best synthetic validation loss of the three E5c n10000 runs;
  - τ = 0.25, the response tolerance of the gate, with h_δ(0.25) = 0.20.
  - So **κ = 0.017519**.
- **What λ = 1 means:** a model whose every normalised response error sits exactly at the 25 % tolerance pays E5c's absolute validation loss again in response loss. A response-blind model pays about 4–5 times it.
- **Runs (6, fixed):**
  - λ = 1 with seeds 0, 1, 2 (primary);
  - λ = 0.3 and λ = 3 with seed 0 (bracket of the anchor);
  - λ = 0 with seed 0: a code-path control, same plugin with zero response weight, not selectable.
- **Baseline (ordinary loss):** the frozen E5c n10000 seeds 0–2, with identical data, splits, seeds and recipe, re-scored on every E5d set.
- **Scale inspection:** L_original and L_response of zero-shot and the E5c checkpoints on the training pairs are reported before training. It is a report only; the λ set does not change.
- **Validation monitor:** "Validation total loss" = graphkit's Validation loss + λκ · L_response on the full E5d validation pair set. It drives the best epoch, early stopping and the LR plateau. At λ = 0 it equals the E5c rule.

## Gates, selection, freeze (synthetic only)

- **Static:** E5c ST1–ST5, unchanged, on the E5c held-out test.
  - Every E5c run failed ST3 (import sign: never predicts export) and ST4 (import MAE ≥ 13.6 MW). These are not relaxed.
- **Response:** on the E5d validation pairs, for each of pv, battery and load:
  - RS1: import slope ratio in [0.8, 1.2];
  - RS2: import relative MAE ≤ 0.25;
  - RS3: branch ΔP relative error ≤ 0.5;
  - RS4: ΔVm relative error ≤ 0.5;
  - RS5: ΔVa relative error ≤ 0.5.
  - A low-PBE, PV-blind model cannot pass. Thresholds RS3–RS5 sit at half of E5c's PV-blind level (≈ 1.0).
- **Retention:**
  - RT1/RT2 as E5c: E5 test ≤ 2.539 MVA, E5b test ≤ 1.173 MVA;
  - RT3: E5c test PBE ≤ 1.5 × the frozen E5c checkpoint (0.920 MVA).
- **Selection:**
  1. eligible = all 23 criteria;
  2. then the lowest E5c full-validation-pool PBE;
  3. ties within 10 % → seed stability, then λ closest to 1.
  - **If nothing is eligible:** lexicographic fallback (static, PV response, battery/load response, retention, number passed), flagged, and the verdict cannot be A.
- **Freeze:**
  - sha256 of the weights, normaliser, σ scales, configs, pair manifests and selection table go into `metadata/e5d_checkpoint_registry.yaml`;
  - this is committed **before** any real state is opened;
  - the predict code refuses real targets until then.

## Real transfer, verdicts, weather (fixed now)

- **Population:** the S1 2,829 states exactly as E4–E5c. E5c and E5d are scored on the E5c re-encoded copy.
- **Criteria:**
  - R1–R5: E5c's criteria unchanged (active residual, PBE, import, voltage, PV slope within [0.8, 1.2] × AC);
  - R6/R7: no severe regression in the battery and load slopes, |ratio − 1| no more than 0.10 worse than E5c.
- **Verdicts, evaluated in this order:**

  | Verdict | Condition |
  |---|---|
  | **E5D-A** | all of R1–R7 and an unflagged selection |
  | **E5D-C** | the selected checkpoint does not pass RS1 + RS2 for pv on the held-out test pairs (fails even synthetically) |
  | **E5D-B** | synthetic PV response learned but R5 fails |
  | **E5D-D** | anything else |

- **Weather, ramps and heroes: only on E5D-A.**
  - Exact frozen S1/S2/timeline/heroes, bootstrap, materiality and ramp bins.
  - Ramps are judged on tracking ratio **and** absolute ΔP/ΔVm/ΔVa error.
  - **Otherwise STOP:** weather remains unresolved and model development closes.

## Leakage controls (enforced in code and tests)

- **The pair sampler reads only static sources**: the E5b/E5c envelope `ALLOWED_SOURCES` plus this config.
- **Training data roots are fixed:** the E5c synthetic pool and the three E5d pair sets. Manifests carry a source tag, and weather columns are refused.
- **σ comes from training pairs; κ from E5c synthetic validation losses; λ is fixed above.** No real number enters any of them.
- **The absolute splits must hash-equal E5c's n10000 splits** of the same seed.
- **Real targets are refused** until the frozen registry lists the run, with sha256 re-verified.
- **The demo is not modified during E5d.**
