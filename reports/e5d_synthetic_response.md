# E5d: synthetic response learning (paired AC probes)

_12 October 2026. Synthetic data only. No real state was opened for anything in this report._
- Pre-registration: `17735ee`, A0 `80515b9`. Code: `496e1be`.
- Design: [`e5d_design.md`](e5d_design.md).

To reproduce:

```bash
uv run --env-file .env python scripts/build_e5d_pairs.py --set train --chunks 6   # + validation, test
uv run python scripts/train_e5d.py prepare && uv run python scripts/evaluate_e5d.py scale
uv run python scripts/train_e5d.py ladder --gpus 0 1 --per-gpu 3
uv run python scripts/evaluate_e5d.py synthetic
```

Outputs:
- [`tables/e5d_seed_results.csv`](tables/e5d_seed_results.csv): every run, static metrics, response summary, all 23 criteria;
- [`tables/e5d_response_probes.csv`](tables/e5d_response_probes.csv): run × set × type × magnitude class × output family;
- [`figures/e5d_synthetic_response.png`](figures/e5d_synthetic_response.png);
- [`experiments/e5d/`](experiments/e5d/): pair sets, splits, scale inspection, runs, synthetic evaluation.

## Answer

- **Response-aware training teaches GENCO the AC response to PV, battery and load on held-out synthetic pairs.** The best run (λ = 1, seed 0) reproduces the import response to a PV change with:
  - slope ratio **0.997** against 0.014 for the frozen E5c model;
  - relative error **2.6 %** against 98.9 %;
  - correlation 0.9998.

  This holds for **small steps of 0.05–0.375 MW too** (slope ratio 1.000, mean error 0.038 MW against a true 0.23 MW). Battery and load responses also become close to AC (ratios 0.998 and 0.962), as does the distributed response in branch flows, Vm and Va.
- **The ordinary loss does not do this, with the same code and data.** The λ = 0 control keeps E5c's blindness: PV ratio 0.001.
- **The result is not seed-robust at λ = 1.**
  - All five response-trained runs learn the PV **import** response (ratios 0.98–1.01).
  - Only λ = 1 seed 0 also learns the **distributed** response and the load response to gate level.
  - Seeds 1 and 2 end with worse absolute accuracy (PBE 2.06 and 1.53 MVA) than E5c.
- **No run passes the full 23-criterion gate.**
  - Every run, E5c included, fails ST3 (import sign ≥ 99 % on |import| ≥ 5 MW) and ST4 (import MAE ≤ 5 MW).
  - The best run also misses ST2 by 2 %: 0.672 against 0.661 MW (5 × DC-PF).
  - The pre-registered fallback therefore selects, **flagged**, λ = 1 seed 0, which passes all 15 response and all 3 retention criteria ([`e5d_checkpoint_selection.md`](e5d_checkpoint_selection.md)).

## 1. Data

| Set | Base states | Pairs pv / battery / load | AC states | Rejected | pv zero ↔ non-zero |
|---|---|---|---|---|---|
| train (seed 9700) | 3,000 | 3,000 each | 18,000 | 0 | 732 |
| validation (9800) | 500 | 500 each | 3,000 | 0 | 122 |
| test (9900) | 500 | 500 each | 3,000 | 0 | — |
| E5c probes (9500 / 9600) | 300 + 300 | 300 each | 1,800 + 1,800 | 0 | — |

- **Separation:** no base state is shared between any two of these sets ([`experiments/e5d/splits.json`](experiments/e5d/splits.json)).
  - The E5c probe bases were regenerated from their seeds; the regeneration reproduces every recorded probe x.
- **Absolute training data:** exactly E5c's n10000 splits (hashes checked). Every E5d normaliser is byte-identical to the E5c normaliser of the same seed.

**Scale inspection** (before training, report only; [`experiments/e5d/scale_inspection.json`](experiments/e5d/scale_inspection.json)):
- For the E5c n10000 checkpoints, κ·L_response at λ = 1 is 2.1–5.0 × L_original.
- Their PV import slope ratio on the training pairs is 0.0005–0.015.

## 2. Runs

- All six pre-registered runs completed 200 epochs, best epoch 195–199, about 4.6 h each with six runs sharing two GPUs.
- None was excluded.
- E5c n10000 seeds 0–2 (ordinary loss, frozen) are the baseline.

## 3. Static accuracy (E5c held-out synthetic test, 2,804 states; DC-PF active residual 0.132 MW)

| Run | λ | PBE | Active res. (MW) | Reactive res. | Vm MAE (pu) | Va MAE (°) | Branch P / Q MAE | Import MAE (MW) | Sign ≥ 5 MW | Val-pool PBE | Best val. total loss |
|---|---|---|---|---|---|---|---|---|---|---|---|
| zero-shot | – | 49.16 | 35.88 | 27.97 | 0.0223 | 3.69 | 25.2 / 19.6 | 266.5 | 6.4 % | 51.46 | – |
| E5c n10000 s0 | (0) | 1.520 | 1.236 | 0.661 | 0.0132 | 2.11 | 3.92 / 2.17 | 32.4 | 93.6 % | 1.476 | – |
| E5c n10000 s1 | (0) | 0.721 | 0.617 | 0.257 | 0.0119 | 1.24 | 2.27 / 0.98 | 15.9 | 93.6 % | 0.688 | – |
| E5c n10000 s2 (frozen E5c) | (0) | 0.614 | 0.528 | 0.209 | 0.0121 | 1.09 | 2.28 / 0.89 | 13.6 | 93.6 % | 0.584 | – |
| **E5d λ0 s0 (control)** | 0 | 0.972 | 0.774 | 0.423 | 0.0108 | 1.50 | 2.70 / 1.53 | 20.9 | 93.6 % | 0.928 | 0.0034 |
| E5d λ0.3 s0 | 0.3 | 0.758 | 0.636 | 0.288 | 0.0120 | 1.16 | 1.97 / 0.91 | 14.3 | 93.6 % | 0.723 | 0.0039 |
| **E5d λ1 s0** | 1 | **0.795** | 0.672 | 0.302 | 0.0125 | 1.15 | 2.00 / 0.89 | 14.2 | 95.0 % | 0.750 | 0.0050 |
| E5d λ1 s1 | 1 | 2.061 | 1.661 | 0.915 | 0.0162 | 2.38 | 4.62 / 3.20 | 37.0 | 93.6 % | 1.973 | 0.0159 |
| E5d λ1 s2 | 1 | 1.531 | 1.354 | 0.483 | 0.0110 | 2.06 | 3.29 / 1.57 | 31.5 | 93.6 % | 1.457 | 0.0115 |
| E5d λ3 s0 | 3 | 1.403 | 1.013 | 0.747 | 0.0159 | 1.23 | 1.98 / 1.79 | 12.4 | 96.7 % | 1.358 | 0.0171 |

**Reading:**
- **λ = 0.3 and λ = 1 seed 0 keep absolute accuracy inside E5c's seed range** (E5c 0.61–1.52 MVA).
- **λ = 3 and λ = 1 seeds 1–2 lose some** (1.40–2.06 MVA).
- **The import-sign failure (93.6 %, never predicting export) is shared by E5c and E5d.** Response training moves it only slightly (95.0 % / 96.7 %).

## 4. Response on held-out E5d TEST pairs (import; slope ratio and relative error, GENCO vs AC)

| Run | pv ratio / rel. err | battery ratio / rel. err | load ratio / rel. err |
|---|---|---|---|
| zero-shot | −0.000 / 0.999 | 0.022 / 0.977 | 0.006 / 0.993 |
| E5c s0 / s1 / s2 | 0.001 / 0.002 / 0.014 — 1.00 / 1.00 / 0.99 | 0.36 / 0.70 / 0.72 — 0.64 / 0.31 / 0.28 | 0.02 / 0.57 / 0.60 — 0.96 / 0.45 / 0.42 |
| E5d λ0 (control) | 0.001 / 0.999 | 0.586 / 0.425 | 0.385 / 0.820 |
| E5d λ0.3 | 0.984 / 0.048 | 0.802 / 0.190 | 0.616 / 0.344 |
| **E5d λ1 s0** | **0.997 / 0.026** | **0.998 / 0.010** | **0.962 / 0.049** |
| E5d λ1 s1 | 0.998 / 0.039 | 1.005 / 0.025 | 0.671 / 0.328 |
| E5d λ1 s2 | 1.005 / 0.044 | 0.966 / 0.038 | 0.754 / 0.256 |
| E5d λ3 | 1.003 / 0.038 | 0.978 / 0.023 | 0.766 / 0.216 |

The held-out **E5c test probes** give the same picture. For λ1 s0: pv 1.000 / 0.020, battery 1.000 / 0.008, load 0.916 / 0.087. For E5c s2: pv 0.015 / 0.986.

### PV import response by perturbation size (test pairs; mean |error| in MW vs mean |AC response|)

| Class | AC \|ΔI\| | E5c s2 error / ratio | E5d λ1 s0 error / ratio |
|---|---|---|---|
| small (0.05–0.375 MW) | 0.228 | 0.228 / −0.002 | **0.038 / 1.000** |
| moderate (0.375–1.5) | 0.969 | 0.961 / 0.009 | **0.044 / 0.992** |
| large (1.5–7.5) | 4.285 | 4.228 / 0.014 | **0.059 / 0.998** |
| on/off (0 ↔ non-zero) | 3.270 | 3.232 / 0.014 | **0.046 / 0.996** |

The smallest class is the hardest in relative terms: 17 % relative error, from about 0.04 MW of absolute error. That absolute error is the same in every size class, so the model's sensitivity is right; what remains is a small offset.

### Distributed response, test pairs (relative error Σ|err| / Σ|ΔAC|; correlation)

| Output | pv: E5c s2 → λ0 → **λ1 s0** | battery: E5c s2 → **λ1 s0** | load: E5c s2 → **λ1 s0** |
|---|---|---|---|
| branch ΔP | 1.000 → 1.012 → **0.057** (r 0.999) | 0.494 → **0.177** | 0.568 → **0.232** |
| ΔVm (PQ buses) | 0.972 → 0.999 → **0.049** | 0.592 → **0.259** | 0.488 → **0.307** |
| ΔVa (non-REF) | 0.990 → 0.999 → **0.027** | 0.469 → **0.282** | 0.472 → **0.265** |
| branch ΔQ (reported, not gated) | 1.255 → 1.347 → **0.764** | 2.508 → **0.987** | 0.444 → **0.201** |

- **Reactive-flow responses remain the weakest output.** For PV, ΔQ is small in absolute terms: mean |ΔQ_AC| is 0.013 MVAr per edge.
- **The λ = 0 control keeps every PV distributed error at ≈ 1.0.**

## 5. What the runs show

1. **The objective is the intervention that matters.** Same data, splits, seeds, recipe and code path: λ = 0 → PV blind; λ > 0 → PV response learned in every run. E5c's 50k run (5× more absolute data) stayed blind (0.004).
2. **Import response is easy once supervised; distributed response is seed-sensitive.** Every λ > 0 run gets the PV import slope within 2 %. Only one of three λ = 1 seeds also gets flows, voltages and the load response to gate level.
3. **Response supervision costs absolute accuracy in two of five runs.** The cost is not monotonic in λ (λ0.3 and λ1 s0 fine; λ1 s1/s2 and λ3 worse). This is the seed instability E5/E5b/E5c also showed at 10k.
4. **The static failure is shared with E5c and not caused by E5d.** No model in E5c or E5d predicts export reliably (ST3) or reaches 5 MW import MAE on the broad envelope (ST4).

## Attribution

GENCO `gridfm/genco-pf-transfer` (Apache-2.0); gridfm-graphkit / datakit (Apache-2.0). UK Power Networks LTDS and ECR metadata (CC BY 4.0).
