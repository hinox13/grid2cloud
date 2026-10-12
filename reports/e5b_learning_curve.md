# E5b: learning curve on the broad synthetic envelope, synthetic gate and frozen checkpoint

_8 October 2026. Pre-registration `14ccda8`; checkpoint frozen in `e7c4abb` before any real-state inference. Design: [`e5b_design.md`](e5b_design.md)._

To reproduce:

```bash
uv run --env-file .env python scripts/build_e5b_training_data.py generate-all && \
  uv run --env-file .env python scripts/build_e5b_training_data.py merge
uv run python scripts/finetune_genco_e5b.py prepare && uv run python scripts/finetune_genco_e5b.py ladder --gpus 0 1
uv run python scripts/evaluate_e5b.py synthetic && uv run python scripts/evaluate_e5b.py freeze
```

Outputs:
- [`tables/e5b_learning_curve.csv`](tables/e5b_learning_curve.csv)
- [`tables/e5b_seed_results.csv`](tables/e5b_seed_results.csv)
- [`figures/e5b_learning_curve.png`](figures/e5b_learning_curve.png)
- [`../metadata/e5b_checkpoint_registry.yaml`](../metadata/e5b_checkpoint_registry.yaml)

## Answer

- **GENCO learns the broad envelope, but more slowly than E5's narrow one.**
  - On the E5b held-out test, PBE falls from 48.2 (zero-shot) to 0.83 MVA at 50k.
  - The active residual reaches 0.67–1.0 MW, about 5.6–8.5× DC-PF (0.118 MW).
  - E5's model reached 1.7× DC-PF on its own narrower test.
- **No E5b run passes the pre-registered synthetic gate.**
  - **Every run fails G3**, the requirement of ≥ 99 % correct import sign. 8.6 % of envelope test states export to the grid, and most models predict a positive import for every state: sign accuracy is exactly 91.4 %.
  - G4 (≤ 5× DC-PF) is met only by 10k seed 2.
  - As pre-registered, selection then fell back to all fine-tuned runs, flagged.
- **Selected and frozen: `e5b_ft_n10000_s2`**, the lowest full-validation-pool PBE (0.584 MVA).
  - The 50k run is second (0.834). It early-stopped with best epoch 38 of 139.
- **Retention:** E5b models are worse than E5's on E5's own heavy-load test (best 1.27 against 0.47 MVA). The E5 model is far worse on the E5b test (PBE 70.7 MVA, 551× DC-PF).

## 1. Pools

- **Recipe:** E5's datakit pipeline and seeds structure, with only the load-scenario generator changed.

| Pool | datakit seeds | Requested | Accepted | Rejected (`voltage_sanity`) |
|---|---|---|---|---|
| held-out test | 7000–7002 | 2,838 | **2,818** | 3 |
| validation | 7100–7109 | 9,460 | **9,356** | 90 |
| training | 8000–8069 | 66,220 | **65,433** | 723 |

- **Rejections:** about 1 % against 14 % in E5. The envelope stays mostly inside the voltage-feasible region.
- **Synthetic support versus E5** ([`e5b_coverage.md`](e5b_coverage.md)):

  | | E5 | E5b |
  |---|---|---|
  | Total net load | +101 to +146 MW | −51 to +164 MW |
  | CHAP31 | 0 | ±49.5 MW |
  | LBUZ 33 kV export | 0 | 0.04–2.5 MW per node |
  | Primary loads | high only | from 0 |

## 2. Learning curve (held-out synthetic tests)

Mean over seeds, with the range in brackets.

| Training states | Seeds | E5b test PBE (MVA) | E5b test active res. (MW) | Branch P MAE (MW) | Vm MAE (pu) | Va MAE (°) | E5 test PBE (retention) | Train time |
|---|---|---|---|---|---|---|---|---|
| 0 (E4 zero-shot) | – | 48.22 | 35.64 (302× DC) | 24.7 | 0.022 | 3.33 | 44.80 | – |
| 100 | 3 | 2.97 [2.84, 3.09] | 2.33 | 6.63 | 0.063 | 3.14 | 4.37 | 2.4 min |
| 1,000 | 3 | 2.17 [2.08, 2.25] | 1.73 | 5.07 | 0.022 | 2.42 | 3.15 | 8.3 min |
| 10,000 | 3 | 1.20 [0.59, 1.80] | 1.01 [0.50, 1.44] | 3.36 | 0.012 | 1.79 | 2.09 [1.27, 2.82] | 47–68 min |
| 50,000 | 1 | 0.83 | 0.67 | 2.48 | 0.010 | 1.36 | 1.66 | 220 min (early stop) |

**Comparison with E5 at the same sizes** (E5 recipe on its own test): PBE 5.36 / 1.71 / 0.71 / 0.47.
- With 100 training states, E5b's broad envelope is easier to fit than E5's narrow one.
- From 1k upward it is harder: a wider distribution needs more data for the same synthetic accuracy.

**Saturation rule:** 1k → 10k improved PBE by 45 % and the active residual by 42 %, so 50k was run.

**Seed variance is large at 10k:** PBE 0.59–1.80. As in E5, seed 1 early-stopped; here it was best at epoch 41 of 142.

## 3. Synthetic gate (E5 gate, unchanged)

| Run | G1 PBE ≤ 10 % of zero-shot (4.82) | G2 active ≤ 10 % (3.56) | G3 import sign ≥ 99 % | G4 ≤ 5× DC-PF (0.59 MW) |
|---|---|---|---|---|
| 100 (all seeds) | ✓ | ✓ | ✗ (24–91 %) | ✗ (19–20×) |
| 1k (all) | ✓ | ✓ | ✗ (91.4 %) | ✗ (14–15×) |
| 10k s0 / s1 / s2 | ✓ | ✓ | ✗ (91.4 / 91.4 / 94.1 %) | ✗ / ✗ / **✓ (4.2×)** |
| 50k | ✓ | ✓ | ✗ (91.4 %) | ✗ (5.6×) |

- **First size passing:** none.
- **Why G3 is the binding failure:** G3 was carried over from E5, where the true import was always strongly positive. On the envelope, the 8.6 % of test states that export test whether GENCO can predict the export *direction*, and it generally cannot. This is a real limitation; the gate is not relaxed.

## 4. Selected and frozen checkpoint (synthetic validation only)

**Rule:** if no run passes the gate, candidates are all fine-tuned runs (flagged); select the lowest PBE on the full validation pool (9,356 states).

| Run | Validation-pool PBE (MVA) |
|---|---|
| **e5b_ft_n10000_s2** | **0.584** |
| e5b_ft_n50000_s0 | 0.834 |
| e5b_ft_n10000_s0 | 1.217 |
| e5b_ft_n10000_s1 | 1.831 |
| 1k seeds | 2.14–2.29 |
| 100 seeds | 2.98–3.20 |

| Item | Value |
|---|---|
| Training states / seed | 10,000 / 2 (pretrained, fine-tuned) |
| Weights | sha256 `ca653efe7e85…95aa` |
| Normalizer | own: baseMVA **34.86** (E5: 113.8), fitted on its 10,000 E5b training states only; sha256 `39a6fc0f975c…adda` |
| Best epoch | 197 of 200; validation loss 2.36e-3 |
| Held-out E5b test | PBE 0.586, active res. 0.500 MW (4.2× DC-PF) |
| Frozen | `e7c4abb`, before any S1 inference |

## Attribution

GENCO `gridfm/genco-pf-transfer` (Apache-2.0); gridfm-graphkit / datakit (Apache-2.0). UK Power Networks LTDS and ECR metadata (CC BY 4.0).
