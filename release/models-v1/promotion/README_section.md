## Frozen models and independent verification (`cloud2grid-models-v1`)

The frozen **E5c** and **E5d** checkpoints are published as GitHub Release assets, with a held-out synthetic verification set. One command re-runs both models and checks the main synthetic finding:

```bash
uv sync --extra genco                      # Linux x86-64
uv run python reproduce/verify_models.py   # CPU by default; --device gpu optional
```

**What is independently reproducible** (synthetic, held-out data, actual inference):
- E5c's PV blindness (import slope ratio 0.014);
- E5d's recovery of the PV, battery and load responses, including branch flows and voltages;
- both models' remaining ~14 MW absolute import error.

**What is not:**
- **The real 2024 results:** PV slopes AC −1.02 / E5c −0.04 / E5d −1.07, E5d's +13 MW offset, and the **E5D-D partial-transfer verdict**. They need real operating data that are not published.
- **Training.**

**Known limitations, stated in the model cards:**
- **E5c generator-encoding caveat:** see below.
- **E5d is partial:** the E5D-D verdict.
- **Scope:** single network, synthetic training, flagged selections.

**Numerical determinism.**
- **GPU inference is not bit-for-bit deterministic** (most likely the order of GPU scatter-add reductions; not isolated). In our CUDA 12.6 setup, identical GPU runs differed by up to ~0.2 MW in decoded import and branch flows, while Vm and Va agree to ~1e-5. CPU inference is deterministic.
- **Effect on the published values:** they come from one GPU run, so the verifier's tolerances are set from this measured noise ([`reproduce/README.md`](reproduce/README.md)).
- **Claim thresholds** are the pre-registered E5d gates.

**Licences.**
- **Weights and code:** Apache-2.0.
- **Verification data:** CC BY 4.0.
- **Third-party material keeps its own terms:** see [`NOTICE`](NOTICE).
- **Where the assets live:** in GitHub Releases, not in Git history.
