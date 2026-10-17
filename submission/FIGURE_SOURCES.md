# Figure sources

All six figures are drawn by [`make_figures.py`](make_figures.py) from **frozen** Cloud2Grid outputs only. Nothing is re-fitted, re-simulated or predicted.

```bash
# optional: C2G_FONT_DIR=<dir with static Source Sans TTFs> for the Explorer's typeface
uv run python submission/make_figures.py   # → submission/figures/0*.png
```

- **Colours:** the Explorer's light palette (`demo/c2g/theme.py`).
- **Typeface:** Source Sans, the Explorer's font, cut from the variable font shipped with Streamlit into static instances in a scratch folder (SIL Open Font License; not committed). Without it the script falls back to DejaVu Sans.
- **Repository state:** tag `cloud2grid-submission-v1` (data and tables). On 15 Oct 2026 two figure texts were corrected and figures 3 and 6 regenerated from the same inputs: figure 3 title "The PV breakthrough" → "PV response on real states" (file renamed from `03_pv_response_breakthrough.png`), and figure 6 subtitle "no E6 model was trained" → "no model was trained for this diagnostic". The rebuild reproduced the other four figures pixel-for-pixel, and figures 3 and 6 changed only in those text lines.

## 01 — Cloud2Grid overview (`01_cloud2grid_overview.png`)

| Element | Source | Class |
|---|---|---|
| Satellite images, 09:00 and 11:30 UTC | `data/demo/events/jun15_cloud_clearing/satellite/frame_001.webp`, `frame_011.webp` (Meteosat E-View, EPSG:4326 as served; `frames.parquet` holds timestamp, bbox and sha256) | Observed |
| Study-area box, town markers | `demo/c2g/satellite.py` `STUDY_BOX`; town coordinates as in the app | Overlay |
| PV time series, 2024 capacity line | `…/fleet_pv.parquet`; capacity 8.945 MW from `…/metadata.json` `active_pv_capacity_mw` | Derived |
| Network schematic, AC state at 11:30 | `…/network_nodes.parquet`, `network_edges.parquet`, `ac_reference_branches.parquet` (loading %, P); layout `data/demo/network_layout.json`. Electrical schematic, **not a map** | Simulated |
| Grid import: AC, E5c, E5d | `…/summary.parquet` `import_mw` at the 7 half-hourly grid states | Simulated / Predicted |

## 02 — Transfer-learning journey (`02_transfer_learning_journey.png`)

| Value | Source |
|---|---|
| E4 active residual 33.7 MW vs DC 0.225 MW (149×), conventional synthetic Sundon S0 (2,297 states) | `reports/tables/e4_family_summary.csv` row `S0_STANDARD_SYNTHETIC`; `reports/e4_zero_shot.md` §5 |
| E5 held-out synthetic PBE 44.8 → 0.47 MVA | `reports/e5_topology_adaptation.md` §1 (E5 held-out test) |
| Real-state PBE (49.0 / 33.2 / 0.338 / 0.442 / 0.676 MVA), PV slopes, import r, battery and load slopes, import bias, Vm MAE | `reports/tables/e5d_real_transfer.csv` (identical to the E5c tables for zero-shot, E5, E5b and E5c) |
| E5b −99.0 % vs E5 | `reports/e5b_real_transfer.md` (paired difference −99.0 % [−99.1, −98.9]) |
| E5d partial verdict (E5D-D) | `reports/experiments/e5d/real_transfer.json`; `reports/e5d_real_transfer.md` |
| E5 slope "not a usable response" (import r 0.11) | `reports/e5b_real_transfer.md` §3; `e5d_real_transfer.csv` |

## 03 — PV response on real states (`03_pv_response_real_states.png`)

| Value | Source |
|---|---|
| Scatter points: import with load and battery effects removed, against HV PV injection (2,829 states) | `data/demo/pv_response_s1.parquet` `partial_AC`, `partial_E5c`, `partial_E5d`, `pv_injection_mw` (published S1 regression; the bundle builder checks the slopes equal the published ones to 1e-6) |
| Slopes −1.02 / −0.04 / −1.07 | `data/demo/catalog.json` `ols_coefficients_s1`; `reports/tables/e5d_response_transfer.csv` |
| PV-attributed import error 2.77 → 0.14 MW | `e5d_real_transfer.csv` / `e5d_response_transfer.csv` `pv_response_error_mw` |
| Load slope 0.61 → 0.93 (AC 0.93) | `e5d_real_transfer.csv` `genco_slope_load`, `ac_slope_load` |
| Import bias +13.1 MW, verdict E5D-D | `e5d_real_transfer.csv` `import_bias_mw`; `reports/experiments/e5d/real_transfer.json` |
| "N states beyond the axis" | computed from the plotted data (y clipped to [−12, 8] as in the app) |

## 04 — Real transfer performance (`04_real_transfer_performance.png`)

| Value | Source |
|---|---|
| PBE, active residual, import MAE, import correlation, five stages | `reports/tables/e5d_real_transfer.csv` `PBE_mean`, `P_residual`, `import_mae_mw`, `import_corr` |
| DC power-flow reference 0.098 MW | same table, `dc_P_residual` |
| Gate lines (import MAE ≤ 5 MW; r ≥ 0.9) | pre-registered R3: `configs/experiments/e5d_selection.yaml` (identical to E5b and E5c) |
| "No stage passes the full gate" | `reports/e5b_real_transfer.md`, `reports/experiments/e5c/real_transfer.json`, `reports/e5d_real_transfer.md` |

## 05 — Explorer (`05_explorer_hero_event.png`)

Rebuilt on 16 Oct 2026 for the redesigned Explorer (the earlier version showed the old story mode).
Three screenshots, composed without drawing any data:

| Panel | File (`submission/screenshots/`) | What it shows |
|---|---|---|
| A | `explorer_guided_tour_slide6.png` | Guided tour, slide 6 of 6 ("Learning the response", 11:30 UTC) |
| B | `explorer_overview_top.png` | Overview: question, short answer and the four fine-tuning steps |
| C | `explorer_story_steps.png` | Scientific story: step cards and the solar-response-by-step chart |

Captured from the Explorer code at publication commit `41ab219` (identical to dev `018a4b5`), light
theme, 1440 px viewport at 2× pixel density, Streamlit header hidden, then cropped. The app replays the
frozen bundles in `data/demo/`; every number visible in it is a frozen result.

## 06 — Why response supervision is not enough (`06_why_response_is_not_enough.png`)

**Post-hoc E6 diagnostic, held-out synthetic data only. No E6 model was trained.** Built with `make_figures.py 6` from published tables only; every annotation is computed from them, and `tests/satellite/test_e6_diagnostic.py` pins the values.

| Element | Source | Class |
|---|---|---|
| Panel A scatter: AC vs GENCO import, 2,804 states | `reports/tables/e6_import_states_e5d.csv` (frozen E5d λ1 s0 predictions on the E5c held-out synthetic test) | Simulated / Predicted |
| Fit 21.1 + 0.623 × AC; fixed point ≈ 56 MW | least squares on the same table | Derived |
| Training mean 58 MW | `reports/experiments/e6_feasibility/diagnostic.json` `train_coverage.import_mean_mw` | Derived |
| Import MAE 14.2 MW; exports detected 22 % | same table; `reports/tables/e6_model_comparison.csv` `export_recall` | Derived |
| Panel B scatter and r = 0.999 (500 PV pairs) | `reports/tables/e6_pv_pairs_e5d.csv` | Predicted |
| Bars 11.68 / 1.76 / 0.046 MW | `reports/tables/e6_pair_level_cancellation.csv` (E5d λ1 s0, pv) | Derived |
| Identity "within 0.06 MW" | `e6_model_comparison.csv` `identity_max_abs_dev_mw` | Derived |

Full analysis: `reports/e6_feasibility_diagnostic.md`.

## Tables in the submission text

Every value in the results table comes from `reports/tables/e5d_real_transfer.csv`. Validation figures (import NMAE 0.084, 100 % convergence, direction agreement 0.99–1.00) come from `reports/e2_operational_validation.md`. The paper reproduction (within 0.03 %) is from `reports/e4_zero_shot.md` §2. The synthetic response ratios (0.014 → 0.997; control 0.001) come from `reports/e5d_synthetic_response.md` §4 and `reports/tables/e5d_response_probes.csv`. The diagnostic numbers in "Why the import is still wrong" (0.06 MW identity, 21.1 + 0.62 × AC, 14.2 MW, 0.999, 11.7 vs 0.05 MW, 0.6 MW injection sum) come from `reports/tables/e6_model_comparison.csv`, `e6_pair_level_cancellation.csv` and `e6_physical_baselines.csv`.
