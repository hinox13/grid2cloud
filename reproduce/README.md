# Verify the Cloud2Grid frozen models (E5c, E5d)

**The script re-runs two frozen GENCO checkpoints on held-out synthetic data and checks the main synthetic finding:**
- **E5c is blind to PV:** its predicted grid import barely moves when PV changes.
- **E5d recovers the response:** it reproduces the AC response to PV, battery and load, including branch flows and voltages.
- **Both keep a ~14 MW absolute import error.**

```bash
uv sync --extra genco                       # Linux x86-64; installs PyTorch 2.11 + GraphKit
uv run python reproduce/verify_models.py    # CPU, about 2–3 minutes after the download
uv run python reproduce/verify_models.py --device gpu   # optional, CUDA 12.6
```

No credentials, training data or GPU are needed. The script exits with code 0 only if every check passes.

## From Hugging Face

The same three archives, byte-identical (the verifier checks their SHA256 first), are on Hugging Face: [E5c](https://huggingface.co/oriolh/cloud2grid-e5c-ft-n10000-s2), [E5d](https://huggingface.co/oriolh/cloud2grid-e5d-l1-s0) and the [verification dataset](https://huggingface.co/datasets/oriolh/cloud2grid-verification-synthetic-v1). No login is needed:

```bash
uv run hf download oriolh/cloud2grid-e5c-ft-n10000-s2 --revision v1 --include "release/*" --local-dir hf_assets
uv run hf download oriolh/cloud2grid-e5d-l1-s0 --revision v1 --include "release/*" --local-dir hf_assets
uv run hf download oriolh/cloud2grid-verification-synthetic-v1 --type dataset --revision v1 --include "release/*" --local-dir hf_assets
uv run python reproduce/verify_models.py --assets-dir hf_assets/release
```

## What it does

1. **Gets the assets.** It downloads the three release assets of [`cloud2grid-models-v1`](../reproduce/assets.json) into `reproduce/.assets/`, or uses files already there. You can override the source with `--base-url`.
2. **Checks hashes.** Every asset must match its SHA256 in `reproduce/assets.json`. Each checkpoint and normaliser must match the frozen registries committed in this repository (`metadata/e5c_checkpoint_registry.yaml`, `metadata/e5d_checkpoint_registry.yaml`).
3. **Runs the models.** It calls `gridfm_graphkit predict` with each checkpoint and **its own** normaliser on two held-out sets:
   - the E5d test pairs: 1,500 pairs, 3,000 states;
   - the E5c test pool: 2,804 states.
4. **Recomputes the metrics** with [`metrics.py`](metrics.py), a self-contained re-implementation of the published definitions.
5. **Cross-checks three ways:**
   - **(A) The metric code applied to the frozen predictions reproduces** the published tables `reports/tables/e5d_response_probes.csv` and `e5d_seed_results.csv` (relative tolerance 1e-6).
   - **(B) Fresh predictions agree with the frozen ones:**
     - Vm and Va within 1e-3;
     - decoded import: mean ≤ 0.1 MW and max ≤ 1 MW;
     - branch P: max ≤ 1 MW.
   - **(C) Fresh metrics agree with the published values:**
     - within 1 % relative, or within the absolute tolerances in the script;
     - reactive branch-flow responses are reported but not scored.
6. **Evaluates claims C1–C5.** Their thresholds are the pre-registered E5d gates. The script writes `reproduce/output/`: `verification_report.md`, `verification_results.json`, `metric_comparison.csv` and `response_comparison.png`.

## Numerical reproducibility

- **GPU inference is not bit-for-bit deterministic** in GraphKit/PyG. The most likely cause is the varying order of GPU scatter-add reductions; this was not isolated, and the magnitude was measured on one CUDA 12.6 GPU setup, so it may differ on other hardware.
  - Two identical GPU runs differ by up to ~0.2 MW in decoded import and branch flows (mean ~0.03 MW), while Vm and Va agree to ~1e-5.
  - **Why:** the flows over Sundon's near-ideal branches amplify float32 angle rounding.
- **CPU inference is deterministic.**
- **The published values come from one GPU run.** So small response errors carry some numerical noise: E5d's PV import relative error is 0.026 published, against 0.019 on CPU.
- **All claims hold on CPU and GPU.**
- **Tolerances (B) and (C) were set from this measured noise** after the first verification runs, which used tighter, unmeasured tolerances. Claim thresholds were never changed.

## What this does not reproduce

- **Real 2024 Sundon results, which need data not in the release:**
  - the real PV → import slopes (AC −1.02, E5c −0.04, E5d −1.07 MW/MW);
  - E5d's +13 MW import offset;
  - the E5D-D transfer verdict.

  They need the real operating states (UK Power Networks measurements and satellite-derived PV), which are not in this release.
- **Training:** the package verifies the frozen checkpoints; it does not retrain them.

## Licences

See `NOTICE.md` inside each asset. The base model and tools are Apache-2.0; the network-derived data are CC BY 4.0, from UK Power Networks open data, with attribution required.
