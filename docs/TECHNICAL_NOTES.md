# Cloud2Grid technical notes

Detailed notes behind the [project README](../README.md): running the Explorer locally, what the
frozen-model release does and does not reproduce, and the post-hoc E6 diagnostic. The design
document that configs and reports cite as "README §N" is [`PROJECT_DESIGN.md`](PROJECT_DESIGN.md).

## Automated tests

```bash
uv sync && uv run pytest
```

The suite has 328 tests, including leakage and freeze-before-real checks. Some of them check frozen
research artefacts that exist only in the gitignored `data/raw` and `data/interim` folders
(third-party inputs and intermediate outputs, never redistributed). On a public clone those tests are
reported as **skipped**, each naming the missing file (`tests/conftest.py`); on a fresh clone of this
repository 298 pass and 30 are skipped. Where the local data exist, all of them run.

## Run the Explorer locally

A Streamlit app that replays three frozen hero events: Meteosat imagery → satellite-derived PV
→ AC reference → GENCO zero-shot / E5 / E5b / E5c / E5d. It is CPU-only and reads precomputed bundles
in `data/demo/`. It runs no power flow, GENCO inference, download or training.

```bash
uv sync --group demo                                   # streamlit + plotly
uv run --group demo streamlit run demo/streamlit_app.py
```

Rebuilding the bundles needs the local research outputs (frozen predictions, satellite tables,
E-View frames) and runs offline in about a minute:

```bash
uv run python scripts/build_demo_events.py             # → data/demo/ (≈3 MB)
```

Pages: **Overview** (the question, the fine-tuning steps, the answer and one frozen moment of
the 15 June story),
**Demo** (play the story or the event; switch AC / zero-shot / E5 / E5b / E5c / E5d),
**Scientific story**, **PV response** (the central finding: the PV blind spot and what closed it),
**Model evolution**, **Data & attribution**, and **Cloud Impact** (one event from clouds to grid
to an illustrative value at historical market prices; evidence in
[`reports/economic_impact/`](../reports/economic_impact/verification.md)).
Deployment: [`docs/DEMO.md`](DEMO.md).

![What did we learn? E4 → E5d](../reports/figures/c2g_what_we_learned.png)

**Result in one line.** In our experiments, synthetic-to-real transfer needed not only topology
and operating-envelope coverage, but explicit learning of physically meaningful sensitivities.
- **What E5d achieved:** the response-aware model learns the PV sensitivity from paired synthetic AC
  states, and it transfers to real operation (PV slope −1.07 vs AC −1.02).
- **What still fails:** its import is ~13 MW too high, and the voltage and battery criteria fail
  (verdict E5D-D, partial).
- **Why the level is wrong:** a post-hoc diagnostic (E6, below) explains the import error.
- **The weather question remains unresolved,** because no model passes the full real-transfer gate.

**Licensing.** Cloud2Grid source code: Apache-2.0 ([`LICENSE`](../LICENSE)). Released model weights (`cloud2grid-models-v1`): Apache-2.0 for Cloud2Grid's contribution, fine-tuned from the Apache-2.0 GENCO checkpoint. Synthetic verification dataset: CC BY 4.0. Third-party data, imagery and checkpoints keep their own licences and attribution requirements, and the demo bundles, reports and figures are not relicensed: see [`NOTICE`](../NOTICE) and [`docs/DATA_LICENSES.md`](DATA_LICENSES.md).

**Repository snapshot.** This repository is a single snapshot of the final project state; the development history is not included. Commit IDs cited in reports, registries and bundle metadata (pre-registration, freeze and build commits) refer to that development history.

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
- **Effect on the published values:** they come from one GPU run, so the verifier's tolerances are set from this measured noise ([`reproduce/README.md`](../reproduce/README.md)).
- **Claim thresholds** are the pre-registered E5d gates.

**Licences.**
- **Weights and code:** Apache-2.0.
- **Verification data:** CC BY 4.0.
- **Third-party material keeps its own terms:** see [`NOTICE`](../NOTICE).
- **Where the assets live:** in GitHub Releases, not in Git history.

## Why does GENCO get the response right but the import level wrong? (E6 diagnostic)

> **Diagnostic only.** Post-hoc and not pre-registered. Held-out synthetic data. No model was trained for this diagnostic. Nothing frozen changed. Full analysis: [`reports/e6_feasibility_diagnostic.md`](../reports/e6_feasibility_diagnostic.md).

**Mechanism (an exact identity).**
- GENCO does not predict the grid import directly. GraphKit's decoder computes it from the predicted voltages, as the flow out of the slack bus.
- All other injections are known inputs. So the import error equals the sum of the signed active-power mismatches the predicted state leaves at the 36 other buses, plus a small loss difference.
- This holds within 0.06 MW in every state.

**Synthetic evidence** (frozen E5d, 2,804 held-out states; 500 held-out PV pairs):

| | Value |
|---|---|
| Import MAE / fit | 14.21 MW; predicted = 21.1 + 0.623 × AC (compressed toward the 58 MW training mean; exports detected 22 %) |
| Per-bus mismatch vs their sum | ~0.7 MW per bus, sign-coherent; Σ ≈ 14 MW in absolute value |
| PV pairs: absolute error / error of the change | 11.68 MW / 0.046 MW; paired-error correlation 0.999 |

**Limits of response supervision.**
- The level error is shared by both states of a pair, so it cancels in the change that the response loss supervises.
- The original loss does penalise per-bus residuals, but not explicitly their aggregate signed imbalance.
- The slack branches are near-ideal (30–39 MW per µrad), so the angle errors that set the import are invisible to the Va error term.
- Whether the objective or the architecture is ultimately responsible is untested.

**Analytic balance (not a model improvement).** Summing the known injections gives 0.58 MW import MAE; adding GENCO's own predicted losses gives 0.20 MW. Both bypass GENCO's import, and neither makes its voltage state more consistent.

**E5c encoding caveat.**
- **The issue:** our generator-aware encoding (E5c, inherited by E5d) attaches the Leighton Buzzard generators to PQ buses. GraphKit's internal physics decoder sets their `Pg` to zero, so the model's physics feedback and physics loss omit that known generation.
- **What still holds:** evaluation restores it, so the frozen metrics remain valid evaluations of the implemented models.
- **What is untested:** the effect of correcting it.
- **How to read E5c:** *our generator-aware adaptation remained largely insensitive to PV.* The independent effect of a correctly integrated generator representation remains untested.
- **How to read E5d:** response supervision made the difference within this implementation, against the λ = 0 control. That does not make it universally necessary.

**Lesson.** Accurate electrical states, accurate physical sensitivities and global physical conservation are distinct model properties. Good performance on one does not guarantee the others.

**Follow-up direction: conservation-supervised GENCO.**
- E5d's objective plus an explicit global signed power-balance term.
- The generator encoding corrected, and assessed as a separate arm.
- Confirmation only on an untouched real population.

**Reproducibility.**
- `PYTHONPATH=src uv run python scripts/diagnose_e6_feasibility.py all` regenerates the 11 tables in `reports/tables/e6_*.csv`, the 4 figures in `reports/figures/e6_*.png` and `reports/experiments/e6_feasibility/diagnostic.json`, byte-identically.
- It needs the local frozen synthetic predictions, pair manifest and checkpoints under `data/interim/`. These are **not** in this repository, so the diagnostic cannot be re-run from a clean checkout.
- What a clean checkout can do: `tests/satellite/test_e6_diagnostic.py` checks every quoted number against the published tables.
