# Erratum: the E5 automatic verdict rule

_7 October 2026. Recorded before any E5b data generation. E5 files are not modified: the E5 pre-registration (`cb5b11d`), the coded rule in `scripts/evaluate_e5.py`, the frozen checkpoint (`61a4fbd`) and the E5 results (`acda62c`) stay exactly as committed._

| | E5 |
|---|---|
| Coded automatic verdict (`weather_evaluation.json` → `outcome`) | **A** — topology adaptation sufficient, weather robust |
| Scientific adjudication (`verdict.json` → `e5_primary_outcome`) | **D** — other |

## What the coded rule checked

The rule required:
1. the synthetic adaptation gate passed; and
2. no material S1 − S2 gap; and
3. |1 − median ramp tracking ratio| smaller than zero-shot in the high and extreme bins.

## Why it returned the wrong label

- **No real-state accuracy condition.** The E5 specification defines A as *synthetic topology-only adaptation enables generalisation to real satellite-driven operating states*. The coded rule never measured real-state accuracy.
  - It treated **"no weather gap"** (S1 ≈ S2) as if it meant **"successful real-state generalisation"**. These are not equivalent: S1 and S2 can be equally bad.
  - In E5 they were: S1 active residual 28.85 MW against 28.90 MW zero-shot, 295× DC-PF, while the synthetic test was at 1.7× DC-PF.
- **A ratio-only ramp criterion.** A tracking ratio of 1.37 is closer to 1 than 0.46, yet the absolute transition error was 4× larger. Ratio alone cannot show physical improvement.

## Consequence for later experiments (E5b onward)

- Three separate concepts, each with its own pre-registered criterion ([`configs/experiments/e5b_adaptation.yaml`](../configs/experiments/e5b_adaptation.yaml)):
  - **SYNTHETIC ADAPTATION SUCCESS**: the synthetic gate on held-out synthetic states;
  - **REAL-STATE TRANSFER SUCCESS**: absolute accuracy thresholds on the real S1 states for the frozen checkpoint;
  - **WEATHER-GAP TEST**: S1 − S2, run only if real transfer succeeds.
- Ramp improvement requires a lower **absolute** transition error as well as a tracking ratio near 1.
