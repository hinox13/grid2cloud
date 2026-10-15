# Cloud2Grid frozen models v1: E5c and E5d baselines (`cloud2grid-models-v1`)

**What's in it:** the frozen E5c and E5d GENCO checkpoints from Cloud2Grid, a held-out synthetic verification set, and a one-command check that re-runs both models.
- **No new model or result:** the checkpoints are the frozen, registered ones, byte-identical.
- **The submission is unchanged:** tag `cloud2grid-submission-v1` is not modified.

## Assets

{{ASSET_TABLE}}

- **Checkpoint SHA256s,** identical to the frozen registries in the repository:
  - E5c `31b824241880ffc6807f2dad478c34c5c211ee31c7f403092e586c6373ab4d8a`
  - E5d `45ab82525da00844a82a9526bc814de9290efc776159f0d8818703d5e9647435`
- **Where the asset hashes live:** the same hashes are committed in `reproduce/assets.json`.

## Verify

```bash
git clone https://github.com/hinox13/grid2cloud && cd grid2cloud
uv sync --extra genco                      # Linux x86-64
uv run python reproduce/verify_models.py   # CPU by default, ~2–3 min after download; --device gpu optional
```

The script downloads the assets, checks every hash, runs both models with their own normalisers, recomputes the metrics, cross-checks them against the frozen predictions and the published tables, and reports which claims are independently reproduced.

**Reproducible from this release (synthetic, held-out data only):**
- **C1:** E5c is blind to PV (import slope ratio 0.014).
- **C2:** E5d recovers the PV import response (≈ 1.0).
- **C3:** E5d reproduces the battery and load responses.
- **C4:** E5d reproduces the distributed branch-flow and voltage responses.
- **C5:** both models keep an absolute import error of about 14 MW.

**Not reproducible from this release:**
- **The real 2024 results:** PV → import slope AC −1.02 / E5c −0.04 / E5d −1.07 MW/MW, E5d's +13 MW import offset, and the E5D-D partial-transfer verdict. They need real operating data that are not published here.
- **Training.**

## Numerical determinism

- **GPU inference is not bit-for-bit deterministic.** In our CUDA 12.6 setup, two identical GPU runs differed by up to ~0.2 MW in decoded import and branch flow; Vm and Va agreed to ~1e-5. The magnitude may differ on other GPUs.
- **CPU inference is deterministic.**
- **The published values come from one GPU run,** so the verifier compares with tolerances set from this measured noise (`reproduce/README.md`).
- **Claim thresholds are the pre-registered E5d gates.**

## Limitations

See the model cards.
- **E5c:** blind to PV.
- **Generator encoding:** a known decoder inconsistency with the generator-aware encoding affects both models.
- **E5d:** partial transfer to real states (verdict E5D-D: +13 MW import offset; voltage and battery criteria fail), and not seed-robust.
- **Both:** synthetic training on one network (Sundon 33 kV), flagged selections.
- **Research artefacts,** not validated for operational use.

## Licences

Copyright 2026 {{COPYRIGHT_HOLDER}}.
- **Model weights, configs and code:** Apache-2.0.
- **Synthetic verification dataset:** CC BY 4.0.
- **Third-party material keeps its own terms:**
  - base model `gridfm/genco-pf-transfer` (Apache-2.0);
  - gridfm-graphkit and gridfm-datakit (Apache-2.0);
  - UK Power Networks open data (CC BY 4.0, attribution in each asset's `NOTICE.md`).
