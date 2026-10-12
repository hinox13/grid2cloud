# E5: learning curve of topology-only adaptation (synthetic Sundon)

_7 October 2026._
- Pre-registered in [`configs/experiments/e5_topology_adaptation.yaml`](../configs/experiments/e5_topology_adaptation.yaml) (commit `cb5b11d`).
- Checkpoint frozen in commit `61a4fbd` before any weather inference.
- Everything here uses **synthetic Sundon data only**.

To reproduce:

```bash
uv run --env-file .env python scripts/build_e5_training_data.py generate-all && \
  uv run --env-file .env python scripts/build_e5_training_data.py merge
uv run python scripts/finetune_genco_e5.py prepare
uv run python scripts/finetune_genco_e5.py ladder --gpus 0 1        # + --scratch for the secondary runs
uv run python scripts/evaluate_e5.py synthetic
```

Outputs:
- [`tables/e5_learning_curve.csv`](tables/e5_learning_curve.csv)
- [`tables/e5_seed_results.csv`](tables/e5_seed_results.csv)
- [`tables/e5_synthetic_summary.csv`](tables/e5_synthetic_summary.csv)
- [`figures/e5_learning_curve.png`](figures/e5_learning_curve.png)
- [`experiments/e5/runs/`](experiments/e5/runs/): per-run provenance

## Answer

- **On synthetic Sundon, GENCO adapts quickly and well.**
  - 10,000 synthetic states and about 1 hour of fine-tuning on one GPU cut the held-out PBE from 44.8 to 0.56–0.86 MVA (−98 %) and the active residual from 32.9 to 0.42–0.67 MW (−98 %).
  - 50,000 states (5.3 h) reach PBE 0.47 MVA and active residual 0.38 MW: **1.7× DC-PF**, against 146× zero-shot.
- **The pre-registered gate is first passed at 10k (all three seeds).** 1k reaches 5.8–6.2× DC-PF, just outside the 5× limit.
- **Pretraining is worth roughly 10× data.**
  - Fine-tuning with 1k states reaches about the accuracy of training from scratch with 10k.
  - At equal size, scratch is 2.6× (10k) to 16× (1k) worse on PBE.
- **Import sign is fixed from N = 100.** Import *tracking* stays weak even at 50k: correlation 0.42, MAE 8.1 MW.

## 1. Data and protocol

- **Recipe:** the E4 S0 recipe unchanged (official datakit `pf_small`; 43 load scenarios × 22 N-1 variants per seed), on the E1 case with the A1 slack limits.
- **Gates:** the same AC gates as E4; every rejection is `voltage_sanity`, as in E4.

| Pool | datakit seeds | Requested | Generated | Accepted | Load blocks |
|---|---|---|---|---|---|
| held-out test | 5000–5002 | 2,838 | 2,690 | **2,256** | 129 |
| validation | 5100–5109 | 9,460 | 8,903 | **7,642** | 430 |
| training | 6000–6069 | 66,220 | 62,407 | **53,200** | 3,010 |

**Isolation:**
- No E4 seed, real timestamp, UKPN reading or PV value enters any pool.
- Weather families are refused by the training code until a checkpoint is frozen.
- Tests: [`tests/satellite/test_e5.py`](../tests/satellite/test_e5.py).

**Training (official GENCO transfer workflow):**
- `gridfm_graphkit finetune` from `gridfm/genco-pf-transfer@e7a98e9` `pretraining/best_model_state_dict.pt`.
- The paper's `finetune/case118_N` recipe unchanged:
  - lr 5e-4 with plateau decay 0.7 / 5;
  - batch 64, 200 epochs, early-stopping patience 100;
  - loss 0.1 × physics + 0.9 × bus MSE;
  - best epoch by synthetic validation loss.
- **Normalizer:** graphkit's `fit_on_train`, fitted on each run's own training split only and saved with the checkpoint.
- **Subsets:**
  - training = first N of a seed-specific permutation (nested within a seed);
  - validation = first ⌈N/8⌉ of one fixed permutation;
  - the test set is identical for every run (sha256 `fb59e6f7…`).
- **Hardware:** one GPU per run; torch 2.11.0+cu126, graphkit 0.9.0.3, datakit 1.1.0.

**Differences from the paper's transfer experiment:**
- network `sundon_33kv` instead of `case118_ieee`;
- N counts *training* states (the paper's N is the total of an 80/10/10 split);
- explicit split files with disjoint datakit pools;
- seeds 0, 1, 2 (the paper uses 0).

## 2. Learning curve (held-out synthetic test, 2,256 states)

Mean over seeds, with the seed range in brackets. DC-PF on the same states: active residual **0.225 MW**.

| Training states | Seeds | PBE Mean (MVA) | Active res. (MW) | ×DC-PF | Branch P MAE (MW) | Vm MAE (pu) | Va MAE (°) | Import MAE (MW) | Import r | Train time | Gate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **0** (E4 zero-shot) | – | 44.80 | 32.85 | 146 | 28.66 | 0.0376 | 7.09 | 331.6 | 0.02 | – | ✗ |
| 100 | 3 | 5.36 [5.32, 5.38] | 4.79 [4.77, 4.81] | 21 | 7.43 | 0.0292 | 2.60 | 25.9 | −0.09 | 2.2 min | ✗ |
| 1,000 | 3 | 1.71 [1.63, 1.75] | 1.35 [1.30, 1.39] | 6.0 | 2.93 | 0.0185 | 1.58 | 21.3 | −0.07 | 8 min | ✗ (G4) |
| 10,000 | 3 | 0.71 [0.56, 0.86] | 0.54 [0.42, 0.67] | 2.4 | 1.63 | 0.0105 | 0.91 | 9.4 | 0.25 | 45–67 min | ✓ all seeds |
| 50,000 | 1 | **0.47** | **0.38** | **1.7** | 1.60 | 0.0092 | 0.81 | 8.1 | 0.42 | 320 min | ✓ |

**Training effort:**
- Every fine-tuned run except one used all 200 epochs, with the best epoch at 196–199. `ft_n10000_s1` stopped early: its best epoch was 41 of 142 run, which is why its seed spread is wider.
- `scratch_n1000_s0` used all 200 epochs with its best epoch at 101.
- Since most best epochs fall at 196–199, the 200-epoch budget is still binding; this is reported, not tuned.
- Inference takes about 2–4 ms per scenario including CLI start-up.

**Explicit checks:**

| Check | 0 | 100 | 1k | 10k | 50k |
|---|---|---|---|---|---|
| Wrong import sign (accuracy < 99 %) | yes (0 %) | no (100 %) | no | no | no |
| Near-constant import (dynamic range < 0.2) | no (4.3; the −206 MW constant is specific to S1) | no | no | no | no |
| Weak voltage tracking (per-bus r < 0.9) | yes (−0.25) | yes (0.09) | yes (0.45) | no (0.92) | no (0.93) |

**Where the error sits:**
- Zero-shot, 91 % of the PBE is on the Sundon-site buses with near-zero-impedance branches.
- At 10k this falls to 16 %, and the remaining error spreads over the 11 kV primaries and the Leighton Buzzard 33 kV ring.
- The near-zero-Z concentration was therefore a symptom of missing adaptation, not a fixed property of the graph ([`e5_representation_sensitivity.md`](e5_representation_sensitivity.md)).

## 3. Pretraining benefit (secondary, seed 0)

| Training states | Fine-tuned PBE / active res. | Scratch PBE / active res. | Scratch ×DC-PF |
|---|---|---|---|
| 1,000 | 1.63 / 1.30 | 25.6 / 5.70 (branch P MAE 3,938 MW, import nonsense) | 25 |
| 10,000 | 0.56 / 0.42 | 1.43 / 1.12 | 5.0 (just passes G4) |

GENCO's subgrid pretraining reduces the Sundon data needed for a given accuracy by roughly an order of magnitude, consistent with the paper's IEEE 118 transfer curve.

## 4. Adaptation gate (frozen before weather; all on the held-out synthetic test)

| Criterion | Threshold | 10k s0 / s1 / s2 | 50k s0 |
|---|---|---|---|
| G1 PBE ≤ 10 % of zero-shot | ≤ 4.48 MVA | 0.56 / 0.86 / 0.71 ✓ | 0.47 ✓ |
| G2 active residual ≤ 10 % of zero-shot | ≤ 3.29 MW | 0.42 / 0.67 / 0.53 ✓ | 0.38 ✓ |
| G3 import sign ≥ 99 % | | 100 % ✓ | 100 % ✓ |
| G4 active residual ≤ 5 × DC-PF | ≤ 1.13 MW | 1.9× / 3.0× / 2.4× ✓ | 1.7× ✓ |
| DC parity (reported, not required) | ≤ 0.225 MW | ✗ | ✗ |

- **Saturation rule:** 1k → 10k improved PBE by 59 % and the active residual by 60 % (threshold 5 %), so 50k was required and was run.

## 5. Selected and frozen checkpoint

- **Selection rule:** among gate-passing fine-tuned runs, lowest PBE on the **full validation pool** (7,642 states); a tie within 1 % would go to the smaller N. Scratch runs are excluded by the rule.
- **Validation PBE:**

  | Run | Validation PBE (MVA) |
  |---|---|
  | `ft_n50000_s0` | **0.483** |
  | `ft_n10000_s0` | 0.575 |
  | `ft_n10000_s2` | 0.718 |
  | `ft_n10000_s1` | 0.864 |

  No tie, so the selection is **`ft_n50000_s0`**.

| Item | Value |
|---|---|
| Training states / seed | 50,000 / 0 (pretrained, fine-tuned) |
| Weights | `data/interim/e5/checkpoints/ft_n50000_s0/best_model_state_dict.pt`, sha256 `be88790a54b9…6061` |
| Normalizer | own, fitted on its 50,000 training states only: baseMVA 113.84; sha256 `abeeb82c8cca…a888` |
| Best epoch | 198 of 200; best validation loss 9.4e-4 |
| Registry | [`metadata/e5_checkpoint_registry.yaml`](../metadata/e5_checkpoint_registry.yaml), committed in `61a4fbd` before any weather inference |

## Attribution

GENCO `gridfm/genco-pf-transfer` (Apache-2.0); gridfm-graphkit / gridfm-datakit (Apache-2.0). Network from UK Power Networks LTDS (CC BY 4.0).
