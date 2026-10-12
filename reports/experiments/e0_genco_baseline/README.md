# E0 — minimal GENCO baseline

**Status: reproduced.** Run with the official OpenGridFM tooling, the official GENCO checkpoint and the official test split, unchanged. The metrics match the GENCO paper §5.4.2 numbers to within 1.7%.

```text
gridfm/pf_small_case14_ieee (datakit AC-PF states, SIMULATED)
        ↓  split_by_load_scenario_idx, seed 0  → test = 21,946 scenarios (identical to paper eval)
GENCO Base (hidden 48, 12 layers), gridfm/genco-pf-datakit case14_ieee/base/seed0
        ↓  gridfm_graphkit evaluate   (gridfm-graphkit @ f104900)
power-balance residuals + state RMSE (PREDICTED vs SIMULATED)
```

## Result

Most recent run: `metrics.json`. All values are on the test split; the metric definitions are gridfm-graphkit's.

| Metric | This repo (latest run) | GENCO paper (§5.4.2) | Rel. diff | Spread over 3 local runs |
|---|---|---|---|---|
| Avg. active residual (MW) | 0.0021081 | 0.0021052 | +0.14% | 0.007% |
| Avg. reactive residual (MVar) | 0.0011575 | 0.0011385 | +1.67% | 0.03% |
| PBE Mean | 0.0026974 | 0.0026823 | +0.56% | 0.004% |
| PBE Max | 0.57251 | 0.57255 | −0.01% | 0.11% |

State RMSE (`metrics.json → rmse`) matches the published `case14_ieee_RMSE.csv` to about 5 significant figures. For example, Vm RMSE at PQ buses is 1.16010e-4 here against 1.16009e-4 published.

The train/val/test scenario IDs are **identical** to the published evaluation run. This was checked against `case14_ieee_scenario_splits.json` in the model repository (`split_matches_paper_eval: true`). The split SHA-256 hashes are in `run_info.json`.

### Non-determinism and the residual gap to the paper

GPU evaluation is **not bit-reproducible**. Three runs on the same machine, the same GPU and identical inputs differ by up to 0.11% (PBE Max: 0.57309, 0.57246, 0.57251) and by ≤ 0.03% on the means. The likely cause is non-deterministic CUDA scatter reductions in message passing.

This run-to-run spread is **smaller** than the gap to the paper on the reactive residual (+1.67%) and PBE Mean (+0.56%). That gap is therefore systematic, not noise. The split and the checkpoint are identical, so the most plausible causes are software or hardware differences from the paper's environment: torch 2.11/cu126 on a single GPU here, while the paper's versions and GPU are not recorded in the model repo. This has not been investigated further. A CPU run, or a run in the graphkit `Containerfile` environment, would separate the two causes.

Consequences for later work:

- The README §43 test "deterministic inference where expected" should either run on CPU or compare with a tolerance.
- S0–S4 comparisons (E4) must report run-to-run spread, and must be computed in **one fixed environment**. They must never be compared against numbers produced elsewhere.

The 5% tolerance in `configs/experiments/e0_genco_baseline.yaml` was set **after** the first run, as a regression guard. It is not a statistical criterion.

## Exact provenance

| Item | Value |
|---|---|
| Dataset | `gridfm/pf_small_case14_ieee` @ `5669b8cec913ce1a1ef174d0283c6f6949135455` (Apache-2.0); 219,606 scenarios, 1,099 Hive partitions |
| Checkpoint | `gridfm/genco-pf-datakit` @ `7014f145635f26fa29e9e003f0dc33f689d615da`, `case14_ieee/base/seed0/best_model_state_dict.pt` + `normalizer_stats.pt` (Apache-2.0) |
| Model config | `case14_ieee_base_seed0.yaml` (shipped with the checkpoint; schema v0, converted in memory with `--config_conversion auto_inline`). Full resolved config: `config.yaml` |
| Code | `gridfm-graphkit` git `f104900245cba26d1380037eea562cf633a97484`. The model card says `main` reproduced the paper at this commit. It brings in `gridfm-datakit==1.1.0` |
| Reference numbers | `pf_eval_combined_eval_metrics.csv` on graphkit branch `genco-paper-repro`, row `case14, seed1, base` (CSV seed1 = YAML seed 0, per the repro guide) |
| Hashes of downloaded files | `metadata/provenance.json` |
| Environment | `run_info.json`: Python 3.11.15, torch 2.11.0+cu126, torch-scatter 2.1.2+pt211cu126, lightning 2.6.6, 1× GPU |

## Runtime

| Step | Wall time |
|---|---|
| Download (cold): 466 MB dataset, 7,261 files | ~10 min (many small files) |
| First evaluate: one-time conversion of 1,099 partitions to `processed/` | ~18 min |
| Later evaluate (cached `processed/`) | ~33 s (343 test batches, ~17 it/s) |

## Reproduce

```bash
uv sync --extra genco                        # Linux x86_64; CUDA 12.x driver (or set GPU to "" for CPU)
uv run python scripts/run_genco_baseline.py  # licence gate → download → evaluate → metrics
```

The script exits non-zero if any metric is outside the tolerance or the split differs from the paper's. It runs exactly this upstream command (paths relative to the repo root):

```bash
MLFLOW_ALLOW_FILE_STORE=true CUDA_VISIBLE_DEVICES=0 \
python -m gridfm_graphkit evaluate \
  --config_conversion auto_inline \
  --config data/raw/opengridfm/checkpoints/genco-pf-datakit/case14_ieee/base/seed0/case14_ieee_base_seed0.yaml \
  --data_path data/raw/opengridfm/datasets \
  --model_path data/raw/opengridfm/checkpoints/genco-pf-datakit/case14_ieee/base/seed0/best_model_state_dict.pt \
  --normalizer_stats data/raw/opengridfm/checkpoints/genco-pf-datakit/case14_ieee/base/seed0/normalizer_stats.pt \
  --log_dir data/interim/e0_genco_baseline/mlruns --exp_name e0_genco_baseline --run_name <run>
```

Outputs:

- `metrics.json`: metrics, RMSE, paper comparison, split check.
- `config.yaml`: experiment config and GENCO model config.
- `run_info.json`: command, runtime, git commit, split hashes, environment.
- The MLflow run and full log go to `data/interim/e0_genco_baseline/` (gitignored).

## Notes and caveats

- **What this does and does not show.** It shows that the toolchain, checkpoint, data and metrics work end to end in this repository and agree with the paper. It says nothing yet about UKPN topologies or weather-driven states. Case14 is a synthetic IEEE test grid.
- **Ground truth is SIMULATED.** The datakit labels are AC power-flow solutions, and GENCO outputs are PREDICTED (README §41).
- **Install details.** `torch-scatter` is pinned to the PyG wheel URL, as the graphkit README requires. Torch uses the `cu126` index because the host driver (535) supports CUDA ≤ 12.2, and cu12.6 wheels run under CUDA minor-version compatibility. The lock is restricted to Linux x86_64 (`[tool.uv] environments`).
- **Harmless warnings.** Graphkit logs a `--mp_context` warning (the default on Linux, not `spawn`) and some numpy "invalid value in divide" warnings from correlation plots of constant columns. Neither affects the metrics.
- **Not used:** the `genco-paper-repro` branch. The model card states that `main` at `f104900` gives the same numbers, which this run confirms.
