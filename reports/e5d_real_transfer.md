# E5d: real-state transfer and verdict

_12 October 2026._
- Frozen checkpoint `e5d_l1_s0`, a **flagged** fallback selected on synthetic data only and frozen in **`1c4cc93`** ([`e5d_checkpoint_selection.md`](e5d_checkpoint_selection.md)).
- Real states were opened only after that commit.
- Criteria were pre-registered in `17735ee` ([`configs/experiments/e5d_selection.yaml`](../configs/experiments/e5d_selection.yaml) `real_transfer`, `verdict`).

To reproduce:

```bash
uv run python scripts/train_e5d.py predict --run e5d_l1_s0 --target S1_WEATHER_ALIGNED_GENAWARE
uv run --env-file .env python scripts/evaluate_e5d.py transfer
uv run python scripts/evaluate_e5d.py postfreeze      # report-only diagnostics (§5)
```

Outputs:
- [`tables/e5d_real_transfer.csv`](tables/e5d_real_transfer.csv)
- [`tables/e5d_response_transfer.csv`](tables/e5d_response_transfer.csv)
- [`tables/e5d_branch_pv_slopes.csv`](tables/e5d_branch_pv_slopes.csv)
- [`tables/e5d_bus_pv_slopes.csv`](tables/e5d_bus_pv_slopes.csv)
- [`tables/e5d_postfreeze_runs_real.csv`](tables/e5d_postfreeze_runs_real.csv)
- [`experiments/e5d/real_transfer.json`](experiments/e5d/real_transfer.json)

## Answer

- **The PV blind spot is closed on real 2024 states.**
  - The frozen E5d model's predicted import responds to satellite-derived PV with slope **−1.07 MW/MW**, against −1.02 in AC (ratio 1.05). E5c gave −0.04 and E5b −0.06.
  - The PV-attributed import error falls from 2.77 MW (E5c) to **0.14 MW**.
  - The branch-level PV response error falls 5× (median 0.074 → 0.014 MW/MW).
  - The bus-angle PV response becomes essentially exact (median error 0.050 → 0.0009 °/MW, against a true 0.053).
  - No real state, satellite value or real slope was used to train or select it.
- **The load response is repaired too:** slope ratio 0.65 → **0.99**. Import correlation rises from 0.959 to **0.994**.
- **The pre-registered transfer gate is still not met:**
  - **R3 import fails:** E5d predicts import with a nearly constant **+13.1 MW offset** (MAE 13.2 MW). It follows the variation (r 0.994) but not the level.
  - **R4 voltage fails:** Vm MAE 0.0109 pu against the 0.010 limit, although E5d is the most accurate model so far (E5c 0.0163).
  - **R6 battery fails narrowly:** the battery slope overshoots (ratio 1.17; its error 0.172 against an allowance of 0.161).
  - Absolute PBE rises from 0.44 to 0.68 MVA but stays well inside R2.
- **Verdict: E5D-D — PARTIAL / OTHER.**
  - The selection was flagged (no run passed the static synthetic gate), so E5D-A was excluded before any real state was opened.
  - The full real-transfer gate also fails (R3, R4, R6).
  - Not B: the PV response did transfer (R5 passes).
  - Not C: the synthetic PV response was learned.
- **Weather rule: STOP.** S1/S2, ramps and heroes were not rerun. Weather remains unresolved because E5d did not pass the full real-transfer gate.

## 1. Same real states, every model (S1, 2,829 states)

Means; block-bootstrap 95 % CI for E5d.

| Metric | Zero-shot (E4) | E5 | E5b | E5c | **E5d** | DC-PF |
|---|---|---|---|---|---|---|
| PBE mean (MVA) | 48.99 | 33.18 | **0.338** | 0.442 | 0.676 [0.654, 0.701] | – |
| PBE median / p95 / max | 49.2 / 50.7 / 767 | 7.1 / 228 / 9,221 | 0.26 / 0.84 / 9.3 | 0.34 / 0.96 / 35.3 | 0.59 / 1.24 / 22.7 | – |
| Active residual (MW) | 28.90 | 28.85 | **0.271** | 0.342 | 0.567 [0.549, 0.588] | 0.098 |
| ×DC-PF | 296 | 295 | 2.8 | 3.5 | 5.8 | 1 |
| Reactive residual (MVAr) | 34.99 | 12.40 | 0.154 | 0.195 | 0.275 | – |
| Vm MAE (pu) | 0.0237 | 0.0316 | 0.0144 | 0.0163 | **0.0109** | – |
| Va MAE (°) | 2.63 | 2.88 | **0.39** | 0.42 | 0.66 | – |
| Branch P / Q MAE | 25.0 / 23.0 | 25.7 / 9.1 | **0.85 / 0.32** | 1.23 / 0.42 | 1.49 / 0.42 | – |
| Voltage tracking (median per-bus r) | 0.40 | −0.34 | 0.75 | **0.86** | 0.80 | – |
| Import MAE (MW) | 260.0 | 70.7 | **7.30** | 7.74 | 13.16 | – |
| Import bias (MW) | −260.0 | +67.8 | **+4.4** | +7.7 | +13.1 | – |
| Import r | 0.05 | 0.11 | 0.87 | 0.96 | **0.994** | – |
| Spread σ_pred / σ_AC | 0.23 | 17.7 | 0.60 | **0.95** | 1.15 | – |
| Sign accuracy, all / \|AC\| ≥ 5 MW | 0.1 % / 0 % | 99.9 % / 100 % | 99.9 % / 100 % | 99.9 % / 100 % | 99.6 % / 100 % | – |

AC is the reference.
- **Same population:** identical scenario ids and AC targets for every model, checked in code and by test.
- **Encodings:** E5c and E5d on the re-encoded generator-aware copy; earlier models on the original export.

## 2. Physical response on real states (E5b regression: import on primary load, CHAP31 and PV injection)

| | AC | E5b | E5c | **E5d** |
|---|---|---|---|---|
| **PV → import slope (MW/MW)** | **−1.020** | −0.063 | −0.037 | **−1.070** |
| PV slope ratio | 1 | 0.06 | 0.04 | **1.05** |
| PV-attributed import error (MW) | 0 | 2.70 | 2.77 | **0.14** |
| Branch PV slope, median \|error\| (MW/MW) | 0 | 0.094 | 0.074 | **0.014** |
| Bus Vm PV slope, median \|error\| (pu/MW; true median 1.6e-4) | 0 | – | 1.1e-4 | **2e-5** |
| Bus Va PV slope, median \|error\| (°/MW; true median 0.053) | 0 | – | 0.050 | **0.0009** |
| Battery (CHAP31) → import slope | 1.002 | 0.506 | **0.941** | 1.175 |
| Load → import slope | 0.933 | 0.557 | 0.609 | **0.926** |

- **Errors are reported with every slope.** PV-attributed error = |slope error| × mean PV injection.
- The bus Vm/Va rows are report-only diagnostics computed after the verdict (§5).
- **E5c's battery gain is not lost but overshoots:** 0.94 → 1.17. The load response, which E5c only half-learned, is now essentially exact.

## 3. Pre-registered criteria

| Criterion | Threshold | E5d | Pass |
|---|---|---|---|
| R1 active residual | ≤ 2.885 MW | 0.567 | ✓ |
| R2 PBE mean and p95 | ≤ 3.318 and ≤ 10 MVA | 0.676 / 1.239 | ✓ |
| R3 import | sign ≥ 99 % (\|AC\| ≥ 5 MW), MAE ≤ 5, r ≥ 0.9, spread 0.75–1.33 | 100 %, **13.16**, 0.994, 1.15 | ✗ |
| R4 voltage | per-bus r ≥ 0.8 and Vm MAE ≤ 0.01 | 0.804 / **0.0109** | ✗ |
| R5 PV response | slope within [0.8, 1.2] × AC | 1.049 | ✓ |
| R6 battery no-regression | \|ratio − 1\| ≤ E5c's 0.061 + 0.10 | **0.172** | ✗ |
| R7 load no-regression | \|ratio − 1\| ≤ E5c's 0.347 + 0.10 | 0.008 | ✓ |
| Selection flagged | – | yes | E5D-A excluded |
| SYN_PV_LEARNED (held-out test pairs) | RS1 + RS2 pv | 0.997 / 0.026 | ✓ |

**REAL_TRANSFER_SUCCESS = false → E5D-D_PARTIAL_OR_OTHER.**

## 4. What remains wrong

- **The import level is offset by about +13 MW in nearly every state.** The bias is 13.09 MW and the MAE 13.16 MW, while r is 0.994.
  - **What it is not:** a sensitivity problem. E5d tracks how import moves with PV, load and battery.
  - **What it is:** the absolute import level on the real operating mix sits too high, the same failure that kept every E5c/E5d run from the synthetic ST4 gate (14 MW).
  - This is the same kind of absolute-level error E5b (+4.4) and E5c (+7.7) had, and it is larger here.
- **The battery response now overshoots** (1.17), while the synthetic battery pairs gave 0.998. Real CHAP31 swings coexist with load and PV changes in ways the one-at-a-time pairs do not cover.
- **Absolute accuracy trades off slightly against response.** PBE is 0.44 → 0.68 MVA and the active residual 3.5 → 5.8 × DC-PF.

## 5. Post-freeze diagnostics (report only; nothing here feeds the verdict)

Every E5d run on the same S1 states ([`tables/e5d_postfreeze_runs_real.csv`](tables/e5d_postfreeze_runs_real.csv)):

| Run | Real PBE | Import MAE / bias (MW) | r | PV / CHAP31 / load slope ratio | Branch PV slope err |
|---|---|---|---|---|---|
| E5c (frozen) | 0.442 | 7.7 / +7.7 | 0.959 | 0.04 / 0.94 / 0.65 | 0.074 |
| **e5d_l1_s0 (selected)** | 0.676 | 13.2 / +13.1 | 0.994 | **1.05 / 1.17 / 0.99** | **0.014** |
| e5d_l0.3_s0 | 0.510 | 7.4 / +7.3 | 0.974 | 0.88 / 1.12 / 0.57 | 0.039 |
| e5d_l3_s0 | 1.626 | 22.5 / +8.3 | 0.939 | 0.62 / 2.99 / 0.81 | 0.040 |
| e5d_l1_s1 | 3.277 | 65.4 / +65.4 | 0.962 | 0.68 / 1.67 / 0.78 | 0.104 |
| e5d_l1_s2 | 4.314 | 19.2 / +19.2 | 0.903 | 0.80 / 1.98 / 0.76 | 0.181 |
| e5d_l0_s0 (λ = 0 control) | 5.961 | 10.9 / +6.7 | 0.608 | (−0.97) / 0.91 / 0.16 | 0.219 |

**Reading:**
- **Every λ > 0 run responds to real PV** (ratio 0.62–1.05). Among the ordinary-loss models, E4, E5b and E5c stayed at or below 0.06. E5's 0.65 came with an import spread 17.7× too wide and r 0.11, so it is not a usable response.
- **But transfer quality varies a lot between seeds and λ.**
  - The synthetic selection happened to pick the run with the best real PV response.
  - λ = 1 seeds 1–2 are poor on real states, as E5/E5b 10k seeds also varied.
- **The λ = 0 control** (same code, data and seed as λ1 s0, ordinary loss) is unstable on real states (PBE 6.0, r 0.61). Its PV slope is therefore not interpretable. The frozen E5c checkpoint is the clean ordinary-loss reference.

## 6. Weather, ramps, heroes

**Not evaluated**, as pre-registered: the verdict is not E5D-A. See [`e5d_weather_generalisation.md`](e5d_weather_generalisation.md) and [`e5d_ramp_analysis.md`](e5d_ramp_analysis.md).

The Cloud2Grid Explorer is unchanged and does not show E5d.

## Attribution

UK Power Networks data (CC BY 4.0). EUMETSAT LSA SAF MDSSFTD, LSA-207 (CC BY 4.0). GENCO `gridfm/genco-pf-transfer` (Apache-2.0).
