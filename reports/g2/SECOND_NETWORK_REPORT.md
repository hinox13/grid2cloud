# Second network: Aylesbury East

_22 October 2026. A consolidated, publishable report of the completed second-network study. It contains no unpublished experiment rows._

**Sources published with this report:**
- [`../g2a_aylesbury_validation.md`](../g2a_aylesbury_validation.md): the real-operation validation, frozen as written on 17 October 2026.
- The frozen evaluation tables in [`s/`](s/) and [`a/`](a/), and the checkpoint registry [`../../metadata/g2a_checkpoint_registry.yaml`](../../metadata/g2a_checkpoint_registry.yaml).
- The pre-registered validation criteria and network configuration in [`../../configs/g2/`](../../configs/g2/).

The second-grid feasibility screen, the full replication report and the replication's pre-registration stay in the development history: they also discuss unpublished experiments. Every number below is computed from the published tables, and was also recomputed from the frozen per-state predictions (see Verification).

## Answer

- **Synthetic replication: REPRODUCED.** The pre-registered classification applies on a second UK Power Networks 33 kV network:
  - Ordinary synthetic fine-tuning stays largely blind to solar: PV slope ratio **0.16 / 0.16 / 0.32** with explicit generators, **0.03–0.10** with generation as negative demand.
  - Response-aware training recovers the AC response in **2 of 3 seeds** (**1.005 and 0.990**).
  - The third seed **failed** (0.378), so the pre-registered stability hypothesis H7 fails.
- **Synthetic only.** The real-operation reconstruction of this network **failed** its pre-registered validation, and the study stopped before any real-state training or evaluation. Nothing here concerns real operation, real transfer or weather.
- **The Sundon E5b/E5d trade-off does not recur in the same form.** On this network's synthetic test, the successful response-aware seeds are also closer on the absolute state than ordinary fine-tuning (import MAE **10.2–10.9 MW** against 20.1–28.4 MW). A substantial, sign-coherent absolute import error remains: the predicted import is compressed toward its mean, and exports are found in only 62–65 % of exporting states.
- **Spatial weather cannot be assessed.** 96 % of the active solar lies in one native satellite pixel.

## 1. The network and its solar

| | Value | Source |
|---|---|---|
| Buses as built (E1 code, public LTDS data) | **56** (55 in the GENCO graph after the Sundon 132 kV coupler fuses) | `a/e1_structural_validation.json`, `s/network.json` |
| Lines / transformers | 53 / 16 | `a/e1_structural_validation.json` |
| Generation represented in the synthetic envelope | **39.5 MW solar + 3.0 MW wind = 42.5 MW** at the three 33 kV busbars (ECR) | `s/network.json` |
| Battery | none | – |
| Active PV in 2024 (satellite chain of the validation) | **41.2 MW**, 10 assets | `a/pv_assets.csv` |
| Largest native LSA SAF pixel | **39.5 MW of 41.2 (96 %)**: three farms within about 1.5 km | `a/pv_assets.csv` |

**For comparison, Sundon:**
- 38 buses as built (37 in the GENCO graph);
- one explicit 6 MW plant varied, plus 2.9 MW inside the metered loads;
- one battery.

**Capacity figures in other reports count different things:**
- the feasibility report's "40.6 MW" counts ≥ 1 MW sites;
- 39.5 MW is the 33 kV solar in the synthetic envelope;
- 41.2 MW is all active PV.

## 2. Real-operation validation: FAIL, study stopped

Pre-registered in `configs/g2/g2a_gate_and_validation.yaml`, before the network was built. 200 stratified half-hours, April–September 2024.

| Criterion | Required | Result | |
|---|---|---|---|
| Structural checks | all pass | all pass | ✓ |
| AC convergence | ≥ 0.99 | 1.00 | ✓ |
| Import NMAE | ≤ 0.25 | 0.154 | ✓ |
| Core circuits with r ≥ 0.8 and NMAE ≤ 0.30 | ≥ 60 % | 17 % (1 of 6) | ✗ |
| Direction agreement, every core circuit | ≥ 0.90 | 0.00 (`lne_AYLE_GT1`) | ✗ |
| \|r(import residual, simulated PV)\| | ≤ 0.50 | 0.659 | ✗ |

**Post-hoc diagnostic** (1,837 daylight half-hours): the measured import falls about **0.51 MW per MW** of satellite-derived PV, against about 1.0 in the model. Public data cannot separate the possible causes:
- export limits or curtailment;
- connection points;
- the solar model.

## 3. Synthetic replication (G2A-S)

**Design (pre-registered):**
- **Arms:** four, with three seeds each and n_train = 10,000, following the official GraphKit recipe from `gridfm/genco-pf-transfer`:
  - **A:** zero-shot.
  - **B:** ordinary fine-tuning, generation as negative demand (E5b-like).
  - **C:** ordinary fine-tuning, explicit generators, GraphKit's corrected decoder (E5c-like).
  - **D:** C plus the E5d response loss, λ = 1, with κ by the E5d rule (κ = 0.016325).
- **Data:** synthetic AC states sampled from static public metadata only (a read guard forbids real series, satellite and validation values).
- **Test sets:** a held-out test pool of 2,838 states, including N-1 and perturbed-admittance states; 374 of them export. Plus 500 PV and 500 load held-out paired states.
- **Selection and freezing:** selection on synthetic validation; checkpoints frozen with SHA256 in `metadata/g2a_checkpoint_registry.yaml` before any test prediction.

**Training:** independent network-specific fine-tuning. This is **not** zero-shot transfer of the Sundon model.

| Run | PV slope ratio | PV rel. error | Load ratio | Import MAE (MW) | Bias (MW) | r | PBE (MVA) | Export recall |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| zero-shot (GA) | 0.018 | 0.979 | 0.006 | 36.7 | −31.7 | 0.13 | 24,056 | 0.49 |
| B s0 / s1 / s2 | 0.031 / 0.078 / 0.099 | 0.97 / 0.92 / 0.90 | 0.01 / 0.11 / 0.07 | 28.4 / 26.4 / 27.0 | −4.0 / +0.4 / +1.4 | 0.10 / 0.44 / 0.35 | 0.705 / 0.577 / 0.589 | 0 |
| C s0 / s1 / s2 | 0.159 / 0.162 / 0.324 | 0.84 / 0.84 / 0.68 | 0.20 / 0.20 / 0.37 | 24.3 / 24.2 / 20.1 | +1.0 / +0.3 / +1.4 | 0.66 / 0.67 / 0.88 | 0.514 / 0.513 / 0.473 | 0 |
| **D s0** | **1.005** | 0.012 | 0.84 | **10.9** | −2.2 | 0.95 | 0.473 | 0.62 |
| D s1 (failed) | 0.378 | 0.582 | 0.005 | 27.6 | −5.2 | 0.26 | 1.086 | 0 |
| **D s2** | **0.990** | 0.012 | 0.98 | **10.2** | −2.7 | 0.95 | 0.441 | 0.65 |

**Further results:**
- AC import standard deviation on the test pool: 33.7 MW.
- For D s0/s2, the error of the predicted PV-induced import change is 0.13 MW, against per-state import errors of 10.5 / 2.1 MW on the intact-network pairs.

### Pre-registered hypotheses

| | Hypothesis | Holds |
|---|---|---|
| H1 | zero-shot active residual ≥ 10 × DC power flow | yes |
| H2 | B and C PBE ≤ 0.1 × zero-shot | yes |
| H3 | C PV slope ratio ≤ 0.25 in ≥ 2 of 3 seeds | yes |
| H4 | D PV slope ratio in [0.8, 1.2] and rel. error ≤ 0.25 in ≥ 2 of 3 seeds | yes |
| H5 | D import MAE > 5 MW, and the per-state error is ≥ 10 × the error of the PV-induced change | yes |
| H6 | D nodal mismatches sign-coherent (≥ 0.5) | yes |
| H7 | H4 in all three D seeds (stability) | **no** |

## 4. What this does and does not show

**Shows:**
- On a second, solar-heavier topology, synthetic ordinary fine-tuning leaves GENCO largely PV-insensitive.
- The response-aware loss recovers the physical sensitivity in most seeds.
- An accurate sensitivity coexists with a substantial absolute import error.

**Does not show:**
- **Real operation and weather:** anything about real operation, real transfer or weather, at Aylesbury or elsewhere.
- **Spatial weather:** that cloud structure matters (one pixel dominates).
- **Generalisation:** that the Sundon model generalises (each network was trained separately).
- **Seed reliability:** response learning is less stable here (1 of 3 seeds failed).

**Comparability with Sundon:**
- **Populations:** the Sundon trade-off was measured on 2,829 observation-informed reconstructions of real states. Here only synthetic states exist.
- **Decoders:** arms C and D use the corrected decoder, while Sundon E5c/E5d used the original one.
- **Confounding:** topology, size and solar share change together, so no difference is attributed to any one of them.

**Economic value:** none is computed for this network.

## Verification

**In a public clone** (published tables only):

```bash
uv run python scripts/web/build_research_bundle.py --check      # the site's second-network bundle rebuilds from these tables
uv run pytest tests/web/test_research_claims.py                 # every figure on the site, re-derived from them
uv run python submission/check_post.py                          # every figure in the write-up, re-derived from them
```

**In the development checkout only** (local per-state predictions, checkpoints and pipeline, not redistributed):

```bash
.venv/bin/python scripts/audit/recompute_g2.py /tmp/g2_recomputed.json   # recompute the tables from per-state predictions
PYTHONPATH=src uv run python scripts/g2/s_evaluate.py all                # the frozen evaluation (after data and training)
```

**Reproduction boundary:**
- The test tables (`s/metrics_*.csv`, `s/hypotheses.json`) and the checkpoint registry are frozen.
- The per-state predictions, checkpoints and the G2 pipeline code are local research artifacts, not published; the registry records their SHA256. All 18 G2A weight and normaliser hashes were re-checked against the registry on 22 October 2026, with no mismatch.
- **Pre-registration timing:** `26fbbd5`, before any data or training; amendments `9e6ef2b` (κ) and `4e793ff` (zero-shot normaliser); freeze `4bebc67`. This timing is verifiable in the development history.

**Attribution:** UK Power Networks open data (CC BY 4.0). GENCO `gridfm/genco-pf-transfer` (Apache-2.0). EUMETSAT LSA SAF (CC BY 4.0), used only in the failed validation.
