# E5c design: generator-aware representation, physics probes, robustness-aware selection (pre-registration)

_8 October 2026. Written and committed before any E5c data generation or training._
- Parents: E4 `0f3101b`, E5 `acda62c` (D), E5b `4569a81` (E5B-C; coverage INCONCLUSIVE; E5b frozen and reproduced in this cycle).
- Configs:
  - [`configs/experiments/e5c_generator_aware.yaml`](../configs/experiments/e5c_generator_aware.yaml): representation, sampling, probes, ladder;
  - [`configs/experiments/e5c_selection.yaml`](../configs/experiments/e5c_selection.yaml): gates, selection, transfer criteria, verdicts, weather rule.

## Question

Can a generator-aware synthetic representation and physics-sensitive checkpoint selection teach GENCO the correct response to generation and export, while preserving E5b's real-state gains?

- **Not weather adaptation.**
- **No real states in selection:** no real state from any year or period is used for selection. Training and selection use synthetic states and static metadata only.

## 1. What GENCO saw in E4–E5b (diagnosis from the exported tables)

| Layer | Leighton Buzzard generation (LBUZ31/32/33) |
|---|---|
| pandapower (S1 states) | `sgen` objects `pv_hv@EPN:LBUZ3x` (6 MW HV PV, equal split) |
| pandapower internal ppc / MATPOWER export | folded into bus demand: PD = load − sgen, so **negative PD**; no generator row |
| E5b datakit generation | the envelope generator wrote generation as **negative load** |
| graphkit tables (`bus_data`) | `Pd = −0.53 MW` (example) on PQ buses 8/9/10; `Pg = 0` there |
| GENCO graph | bus feature PD_H < 0 on a PQ bus; the **only `gen` node is the slack** at bus 22 |

So for GENCO, PV was indistinguishable from a small negative load. E5b's import slope on PV was −0.06, against −1.02 in AC.

## 2. Can the official pipeline hold explicit generators?

- **graphkit: yes.** `gen` nodes carry PG (a known input for every non-REF generator in the PF mask), and a PQ bus carries QG as a known feature.
- **datakit / PowerModels solver input: no, for fixed-power generators.**
  - PowerModels' network correction turns every bus with a generator into a **PV bus** with a fixed voltage set-point.
  - Fixed-power-factor distribution generation would become voltage-controlled, and its true voltage magnitude would become a GENCO input.
  - Prototype: 20 S1 states exported with explicit generators were **20/20 rejected** by the AC solver-disagreement gate (0.040 pu).
- **E5c representation (closest supported):**
  - solve the AC state exactly as before;
  - **re-encode the solved tables**: the injection at each LBUZ bus becomes a graphkit `gen` node, with Pg known, Qg fixed and the bus still PQ; demand there becomes 0.
  - Tested unchanged: Pg − Pd per bus, Vm/Va, flows, Y-bus and the DC/AC residuals (bit-identical on 50 S1 states).
  - graphkit loads and predicts on the re-encoded graphs.
- **One generator node per LBUZ bus** (6 MW solar + 1.5 MW wind aggregated, Pmax 2.5 MW per bus). gen nodes have no technology feature and Pmin/Pmax are masked in the PF task, so separate PV and wind nodes would be indistinguishable to GENCO.

## 3. Synthetic design (static sources only)

- **Loads and battery:** the E5b envelope, unchanged.
  - LTDS 3a primaries from near zero to the planning/forecast maximum;
  - hierarchical site/node variation;
  - CHAP31 ±49.5 MW (ECR), with a 20 % idle mode.
- **Generation:** ECR 6 MW solar + 1.5 MW wind. Solar level S and wind level W are sampled independently from a zero-inflated mixture:

  | Component | Probability | Level |
  |---|---|---|
  | zero | 0.25 | exactly 0 |
  | low | 0.20 | U(0, 0.25) |
  | medium | 0.20 | U(0.25, 0.60) |
  | high | 0.20 | U(0.60, 1.0) |
  | full | 0.15 | exactly 1 |

  - total = 6 S + 1.5 W MW, split equally over the three buses;
  - exact-zero total 6.25 %, exact-full 2.25 %.
  - The justification is physical (plant can be off or at rating), not observed 2024 output.
- **Pools:** datakit seeds 9000–9002 (test), 9100–9109 (validation) and 9200–9269 (train), with the E5/E5b pipeline otherwise unchanged. The E5 narrow and E5b broad test pools are re-encoded for retention checks.

## 4. Paired physics probes

- **Construction:** two AC-solved states on the static E1 planning network that differ in one input:
  - `pv`: total LBUZ generation ±1–3.75 MW;
  - `battery`: CHAP31 ±5–25 MW;
  - `load`: one primary ±max(0.5 MW, 20–60 %).
- **Size:** 300 bases per set, validation (seed 9500) and test (seed 9600), so 900 pairs and 1,800 states per set. The solver and gates are E4's (pandapower + PowerModels).
- **Targets:** the AC solutions of both states. Slopes are not assumed to be ±1.
- **Metrics** (x = Δ net withdrawal at the perturbed node):
  - response slope Σ(ΔI·x)/Σx², GENCO against AC, and their ratio;
  - relative import-response MAE;
  - branch ΔP error and ΔVm error.

## 5. Gates and selection (synthetic only; fixed before training)

- **Static gate** (E5c held-out test):
  - PBE ≤ 10 % of zero-shot;
  - active residual ≤ 5× DC-PF;
  - import sign ≥ 99 % on states with |AC import| ≥ 5 MW (twice the largest single-bus generation capacity);
  - import MAE ≤ 5 MW over all states;
  - Vm MAE ≤ 0.015 pu.
- **Response gate** (validation probes): for each of pv, battery and load, slope ratio in [0.8, 1.2] **and** relative response MAE ≤ 0.25. A model with low PBE but near-zero PV response cannot pass.
- **Retention:** PBE on the re-encoded E5 test ≤ 2.539 MVA and on the E5b test ≤ 1.173 MVA (2× the E5b frozen checkpoint).
- **Selection (hierarchical):**
  1. eligible = static + response + retention;
  2. lowest full-validation-pool PBE;
  3. within 10 % of it, prefer the training size with the smallest seed coefficient of variation (single-seed sizes rank after multi-seed ones), then the smaller N.
  - **If none is eligible:** most criteria passed (of 13), then validation PBE. The selection is flagged and the verdict capped at C.
- **Freeze:** hash, commit, then open real states.

## 6. Real transfer, verdicts, weather (fixed before training)

- **Population:** S1 (2,829 states). E5c is scored on its re-encoded copy; zero-shot, E5 and E5b on their own encoding.
- **Criteria:**
  - R1: active residual ≤ 2.885 MW;
  - R2: PBE mean ≤ 3.318 and p95 ≤ 10 MVA;
  - R3: import sign ≥ 99 % (|import| ≥ 5 MW), MAE ≤ 5, r ≥ 0.9, spread 0.75–1.33;
  - R4: voltage tracking r ≥ 0.8 and Vm MAE ≤ 0.01 pu;
  - **R5: PV slope within [0.8, 1.2] × the AC slope** (E5b regression).
- **Verdicts:**
  - **E5C-A:** all of R1–R5;
  - **E5C-B:** R5 fails and less than half of E5b's PV-slope gap is closed;
  - **E5C-C:** anything else.
- **Weather, ramps and heroes:** only on A. Ramps are judged on absolute transition error and tracking ratio.
