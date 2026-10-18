# Cloud2Grid: from real clouds to electric grid intelligence

*What does it take to adapt GENCO, a grid foundation model pretrained on synthetic networks, to a real UK distribution grid as real clouds pass over it?*

**🖥️ [Interactive Explorer](https://cloud2grid.streamlit.app/) · 💻 [Code](https://github.com/hinox13/grid2cloud) · 📦 [Frozen models + verification data](https://github.com/hinox13/grid2cloud/releases/tag/cloud2grid-models-v1) · 🔁 [Reproduce in one command](https://github.com/hinox13/grid2cloud/blob/cloud2grid-models-v1/reproduce/README.md)**

![Cloud2Grid overview. Four panels from left to right: real Meteosat E-View images of the Sundon area at 09:00 and 11:30 UTC on 15 June 2024, showing a cloud deck clearing; satellite-derived PV output rising from about 2 to 9 MW; the Sundon network schematic coloured by AC line loading; and grid import over the morning for the AC reference, the generator-aware and the response-aware GENCO models.](figures/01_cloud2grid_overview.png)

*Real clouds → solar power → a real power grid → GENCO. Each panel is labelled with its provenance: observed imagery, derived PV, simulated AC power flow, predicted GENCO output.*

### In 30 seconds

Using the open GENCO checkpoint and the GridFM toolkits, Cloud2Grid adapts a grid foundation model to a reconstructed real distribution network and evaluates it on satellite-informed 2024 operating states.

- **Zero-shot predictions on Sundon highlight a substantial transfer gap for this unseen topology.** On 2,829 observation-informed, AC-reconstructed 2024 operating states of the Sundon network (UK Power Networks), the official `genco-pf-transfer` checkpoint, under our evaluation conditions, predicts that Sundon exports about 211 MW, where the AC reference imports about 49 MW: an import bias of −260 MW, with the import/export direction reversed in 99.9 % of states.
- **Synthetic-only adaptation closes most of the gap, and response-aware training recovers the solar sensitivity.** Broader synthetic coverage of the operating envelope cuts the real-state power-balance error by 99 %. A **physics-response-aware loss**, which we implemented in GraphKit and trained on pairs of synthetic AC states, brings GENCO's grid-import response to solar in line with the physics: **−1.07 MW per MW of PV, against −1.02 in AC** (−0.04 without it).
- **Accurate sensitivities and an accurate absolute state proved to be separate targets.** The response-aware model's import remains **13.1 MW too high**, so its pre-registered verdict is *partial transfer*. A post-hoc diagnostic identifies a mechanism consistent with this: in the examined held-out PV pairs, the two states carry nearly identical absolute import errors, which largely cancel in the difference that the response loss supervises.

| | Pretrained checkpoint (zero-shot) | Best state accuracy (E5b) | Response-aware (E5d) | AC reference |
|---|---:|---:|---:|---:|
| Real-state power-balance error (MVA) ↓ | 49.0 | **0.338** | 0.676 | 0 |
| Grid-import response to PV (MW per MW) | −0.06 | −0.06 | **−1.07** | −1.02 |
| Grid-import bias (MW) | −260 | +4.4 | +13.1 | 0 |

*Same 2,829 AC-reconstructed half-hourly 2024 operating states for every model. AC values are simulated physical references, not measurements.*

---

## 1. The question: adapting a grid foundation model to a real distribution network

Grid foundation models such as GENCO are pretrained and benchmarked on synthetic networks and operating states, and the open GridFM ecosystem provides the tooling to fine-tune them (gridfm-graphkit) and to generate new AC-solved training data (gridfm-datakit). Real distribution grids add three demanding conditions at once: an idiosyncratic topology, states shaped by real demand and storage, and renewable output that follows the weather. We asked what it takes to adapt the pretrained checkpoint to such a grid with synthetic training data only, and how to tell whether the adapted model has learned the right physical responses as well as accurate states.

## 2. The approach: Earth observation, open grid data and the GridFM toolkits

Cloud2Grid connects three open sources end to end, and keeps every layer's provenance explicit:

| Layer | Source | Class |
|---|---|---|
| Cloud imagery | EUMETSAT Meteosat E-View, every 15 minutes | Observed |
| Solar power | EUMETSAT LSA SAF surface radiation at every registered PV plant, converted with pvlib | Derived |
| Grid states | AC power flow on the network rebuilt from UK Power Networks open data | Simulated |
| GENCO output | the official `gridfm/genco-pf-transfer` checkpoint, then our fine-tuned versions | Predicted |

GENCO is only ever **trained** on synthetic states generated with gridfm-datakit on the rebuilt network, with the official gridfm-graphkit fine-tuning loop. Real 2024 states are used for evaluation only, after each model is frozen.

**2024 operating states** ("real states" for short) are observation-informed AC reconstructions: AC power-flow solutions driven by UK Power Networks' metered half-hourly demand and storage data and by the satellite-derived PV estimate. They are not measurements of the full electrical state.

## 3. A real network, rebuilt from open data and validated against meters

- **Sundon**, a 132/33/11 kV UK Power Networks area in Bedfordshire, rebuilt from published network data: **38 nodes, 44 branches**, every parameter traced to a published UKPN identifier.
- **Two independent AC solvers agree:** pandapower and gridfm-datakit's PowerModels.
- **Validated against metered circuits never used as inputs** (200 timestamps over 18 months): 100 % AC convergence, total grid-import NMAE **0.084**, power-flow direction correct **99–100 %** of the time. Pre-registered verdict: *usable with limitations*.

→ *Validation details:* [`reports/e2_operational_validation.md`](https://github.com/hinox13/grid2cloud/blob/main/reports/e2_operational_validation.md)

## 4. From satellite to solar power

- **Historical capacity, not today's:** only **8.945 MW** of Sundon's PV was connected in 2024 (against 43.9 MW today), verified from connection dates in the Embedded Capacity Register and published network statements.
- **Every 15 minutes, April–September 2024:** LSA SAF surface radiation is sampled at each plant and converted to output with a fixed, documented pvlib chain (Hay–Davies transposition, Faiman cell temperature, PVWatts). 9,040 slots, of which 8,308 are usable.
- **An estimate, never a measurement.** The PV model was configured before any radiation data were available, and it is never fitted to grid data.

## 5. Zero-shot baseline: the unseen topology comes first

We first applied the official `gridfm/genco-pf-transfer` checkpoint (pretrained on 100 subgrids) without adaptation, as the GENCO paper does on an unseen grid; our environment reproduces that paper's IEEE 118 zero-shot evaluation to within 0.03 % on every metric. Sundon is a demanding target: a radial-meshed distribution network with very short, near-zero-impedance 33 kV connections, tee junctions and a single slack supply. On conventional synthetic Sundon states, with no weather at all, the checkpoint leaves an active-power residual of **33.7 MW, against 0.225 MW for a simple DC power flow (149×)**. DC power flow is a linearised solve of the exact network model, used here as a reference scale, not as a like-for-like competitor to a learned model applied zero-shot. These results characterise this specific checkpoint under our evaluation conditions, not GENCO's capabilities in general. Since the topology gap appears before weather enters, adapting to the network came first.

## 6. Progressive adaptation: from topology transfer to physical-response learning

![Progressive adaptation from E4 to E5d. One card per stage, each with its key result and its remaining limitation, plus two dot plots: real-state power-balance error on a log scale, and the PV-to-import response against the AC value of -1.02.](figures/02_transfer_learning_journey.png)

Every experiment was pre-registered: gates, selection rules and verdict rules were committed before its data or training existed. Checkpoints were selected on synthetic data only, then frozen and SHA256-hashed before any real state was opened; failed gates are kept, not relaxed. Each step addressed one limitation and revealed the next requirement:

1. **Zero-shot (E4):** a substantial transfer gap for the unseen topology (above).
2. **Standard synthetic fine-tuning (E5):** held-out synthetic error falls from 44.8 to 0.47 MVA, but real states stay at 33.2 MVA. This gap between held-out synthetic and 2024 accuracy is consistent with a mismatch between the initial synthetic training distribution and the target operating conditions.
3. **A broader operating envelope (E5b): −99.0 % real-state error.** Synthetic states spanning the physically plausible range, built from published metadata only, bring the real-state error to 0.338 MVA.
4. **Generator-aware adaptation (E5c):** import correlation reaches 0.96 and the battery response 0.94 (AC 1.00), but the import responds only weakly to PV.
5. **Physics-response-aware training (E5d):** the PV sensitivity is learned and transfers to real states; the absolute import level remains biased.

| Stage | PBE (MVA) ↓ | Active res. (MW) ↓ | Import MAE (MW) ↓ | Import r ↑ | PV slope (AC −1.02) |
|---|---:|---:|---:|---:|---:|
| E4 Pretrained, zero-shot | 49.0 | 28.9 | 260 | 0.05 | −0.06 |
| E5 Grid-tuned | 33.2 | 28.8 | 70.7 | 0.11 | −0.66¹ |
| E5b Envelope-tuned | **0.338** | **0.270** | **7.30** | 0.87 | −0.06 |
| E5c Generator-aware | 0.442 | 0.342 | 7.74 | 0.96 | −0.04 |
| E5d Response-aware | 0.676 | 0.567 | 13.2 | **0.994** | **−1.07** |

*2024 operating states, same 2,829 for every model. PBE = mean nodal power-balance error. DC power-flow active residual: 0.098 MW. ¹ E5's slope comes with an import 17.7× too dispersed (r 0.11), so it cannot be read as a physical response.*

## 7. Response-aware adaptation: learning how the grid responds to solar

**What we measured.** The generator-aware model (E5c) tracked the variation of the grid import closely (r 0.96), but on held-out synthetic pairs its import response to PV was 1.4 % of the AC one.

**A plausible mechanism, not isolated by intervention.** A PV change of a few MW moves the import by about the same few MW. In a state importing about 50 MW, that is a small share of the per-state error the ordinary objective penalises, so a model can fit absolute states well while giving the change little weight.

**Our extension: supervise the response as well as the state.** Sensitivity supervision has precedents in scientific machine learning; our contribution is a concrete implementation for GENCO, evaluated on a real network:
- **Paired synthetic AC states.** Each pair is identical except for one input: the PV output, the battery or one load. Both states are solved with full AC power flow.
- **Supervise the change.** The loss penalises the gap between GENCO's predicted change, ŷ(B) − ŷ(A), and the AC change, for grid import, branch flows, voltage magnitudes and angles. It is normalised per MW of perturbation, so a 0.05 MW PV step counts as much as a 5 MW one.
- **Keep the original objective.** The total loss is L_original + λ·κ·L_response. It runs as a plugin task inside the official gridfm-graphkit fine-tuning loop and adds no parameters.

Only synthetic states and static network metadata were used for training, normalisation and checkpoint selection. No real state, satellite value or real slope was used.

![PV response on real states. Three scatter panels of grid import, with load and battery effects removed, against PV injection for 2,829 real states. The AC reference has slope -1.02 MW per MW, the generator-aware model -0.04, and the response-aware model -1.07, close to the AC line. Summary boxes: PV slope -0.04 to -1.07; PV-attributed import error 2.77 to 0.14 MW; load slope 0.61 to 0.93; and a note that physical sensitivity is recovered but full real-grid calibration is incomplete.](figures/03_pv_response_real_states.png)

- **Held-out synthetic pairs:** the PV import-response ratio rises from **0.014 (E5c) to ≈ 1.0 (E5d)** (0.997 published; 0.999 in our fresh-clone CPU re-run). Battery, load and the distributed branch-flow and voltage responses are also recovered. An identical run **without** the response loss remains insensitive to PV (0.001).
- **2024 operating states the model never saw:** the PV-to-import slope moves from −0.04 to **−1.07** (AC −1.02); the PV-attributed import error falls from 2.77 to **0.14 MW**; the load response is **0.93**, matching AC's 0.93.

**How to read this comparison.** The matched control (identical code, data and seed, without the response loss) isolates the benefit of response supervision within our evaluated implementation. E5c, E5d and the control share a limitation in our generator representation: because we placed the Leighton Buzzard PV and wind generators on PQ buses, their generation was omitted from the model's internal physics feedback. Evaluation uses the correct generation values, so the reported results remain valid. This limits conclusions about ordinary GENCO fine-tuning beyond our implementation.

## 8. Transfer to the 2024 operating states: what improved and what remains open

![Real-state transfer for the five stages, as four bar-chart panels: power-balance error and active-power residual on log scales with the DC power-flow reference, grid-import error on a log scale with the 5 MW gate, and grid-import correlation with the 0.9 gate.](figures/04_real_transfer_performance.png)

**What the results support:**
- **Response supervision was the decisive change for the PV sensitivity in our setting.** It taught GENCO a renewable-generation sensitivity entirely from synthetic AC solutions, and that sensitivity transferred to unseen 2024 operating states. An identical run without it remained insensitive to PV on held-out synthetic pairs.
- **Coverage matters.** Broader synthetic operating-envelope coverage substantially improved real-state accuracy in our experiments: −99 % error from E5 to E5b.

**What the results do not support:**
- **Full transfer.** The response-aware model's import is biased by **+13.1 MW** (MAE 13.2 MW), its voltage error (**0.0109 pu**) misses the 0.010 pu criterion, and its battery response overshoots (**1.17** MW per MW, against 1.00). Its pre-registered verdict is **E5D-D: partial**.
- **A single best model.** States and sensitivities did not improve together: E5b has the lowest power-balance error, E5c the best battery response, E5d the only physical PV and load sensitivity.
- **An operational model.** E5d is a research model, not a validated operational one.

## 9. Why the absolute import remains biased: a post-hoc diagnostic

E5d reproduces the *change* in grid import closely but not its *level*. A post-hoc diagnostic (E6) on held-out synthetic states examines where the level error comes from. It is not pre-registered, no model was trained for it, and no real data were used.

- **Power-balance accounting links the import error to accumulated nodal mismatches and network-loss differences.** GENCO does not predict the import directly: GraphKit's power-flow decoder computes it from the predicted voltages, as the power flowing out of the substation. The import error therefore equals the difference in network losses plus the sum of the small power imbalances that the predicted voltages leave at the other 36 buses. This accounting is exact when every injection and loss term is included; recomputed from the frozen predictions, it closes within 0.06 MW in every state. The loss difference is small, so the import error is essentially the accumulated nodal mismatch. These imbalances share a sign and accumulate: predicted import ≈ 21.1 + 0.62 × true import, a 14.2 MW mean error.
- **Paired supervision carries almost no signal about this error (observed).** The two states of a pair carry almost the same error (r = 0.999 for PV pairs), so it cancels in their difference, which is the quantity the response loss supervises: 11.7 MW error in each state, 0.05 MW in the PV-induced change. The ordinary objective penalises the mismatch at each bus, but not explicitly their sum.
- **Interpretation.** This mechanism helps explain why response supervision improved the sensitivity without calibrating the level; establishing it as the complete cause would need an intervention.

![Why response supervision is not enough. Panel A: GENCO-predicted against AC grid import for 2,804 held-out synthetic states, with the identity line and a fitted line predicted = 21.1 + 0.623 × AC, showing predictions compressed toward about 56 MW and export states over-predicted. Panel B: for 500 held-out pairs differing only in PV, the import errors of the two states lie on the diagonal (r = 0.999), and a log-scale bar chart compares the 11.68 MW absolute error per state, the 1.76 MW typical PV-induced change and the 0.046 MW error of the predicted change. A bottom strip states the power-balance identity and that accurate states, sensitivities and global conservation are distinct properties.](figures/06_why_response_is_not_enough.png)

**The lesson: in our experiments, accurate electrical states, accurate physical sensitivities and global physical conservation behaved as distinct model properties.** Good performance on one did not guarantee the others. A simple sum of the known injections reproduces the import within 0.6 MW, but that bypasses the learned model rather than improving it.

→ *Diagnostic details:* [`reports/e6_feasibility_diagnostic.md`](https://github.com/hinox13/grid2cloud/blob/main/reports/e6_feasibility_diagnostic.md)

## 10. Explore it yourself

### 👉 [Open the Cloud2Grid Explorer](https://cloud2grid.streamlit.app/)

![The Cloud2Grid Explorer as deployed. A: the last slide of the guided tour at 11:30 UTC on 15 June 2024, with the story caption, four linked readouts from clouds to GENCO, the Meteosat image zoomed to Sundon, the network schematic and the timeline. B: the Overview page with the question and the four fine-tuning steps as cards. C: the Scientific story page with step cards and a bar chart of the solar response by step against the physics.](figures/05_explorer_hero_event.png)

1. **Overview:** the question, the four fine-tuning steps and the answer, on one page.
2. **Take the guided tour:** six captioned slides over the 15 June 2024 cloud clearing, advanced with **Next**. A real cloud deck clears over Bedfordshire, satellite-derived PV jumps, the AC grid import falls, and each GENCO stage responds to a different degree.
3. **Explore freely:** switch "Grid shown" between the AC reference and each GENCO stage on three real events: a cloud clearing, broken cumulus and a clear-sky control.
4. **Scientific story, PV response, Model evolution:** the full argument and every number behind it.

Imagery and PV are 15-minute; grid states are the frozen half-hourly 2024 operating states behind every published metric, never interpolated. The app is a lightweight CPU-only replay: no power flow, inference or download runs in it.

## 11. Frozen models and independent verification

The frozen checkpoints and a held-out verification set are published as a GitHub Release, **[`cloud2grid-models-v1`](https://github.com/hinox13/grid2cloud/releases/tag/cloud2grid-models-v1)**. Anyone can re-run the main synthetic finding with real inference:

```bash
git clone https://github.com/hinox13/grid2cloud
cd grid2cloud
uv sync --extra genco
uv run python reproduce/verify_models.py
```

- **Released:** the E5c and E5d checkpoints, each with its own normaliser, a model card and its SHA256; and public held-out synthetic verification data (1,500 AC-solved response pairs and 2,804 held-out states).
- **What the script does:** it runs real GraphKit inference with both checkpoints (no replay of stored predictions), cross-checks the results against the frozen predictions and the published tables, and reports which claims reproduce.
- **Our fresh-clone checks passed on CPU and GPU:** all **five synthetic claims** reproduced (E5c's weak PV response; E5d's PV recovery; E5d's battery and load responses; E5d's distributed responses; both models' remaining absolute import error), and **44/44 scored metrics** within the stated tolerances. CPU inference is deterministic; GPU inference varies slightly between runs, and the tolerances account for it.
- **Scope:** this verifies the **synthetic** findings. The 2024 operating-state results above need operating data that are not in the release, so they are documented but cannot yet be independently recomputed.

→ *Reproducibility and open-science details:* [`docs/TECHNICAL_NOTES.md`](https://github.com/hinox13/grid2cloud/blob/main/docs/TECHNICAL_NOTES.md)

## 12. Conclusions and research directions

The open GENCO checkpoint and the GridFM toolkits made it possible to run a complete, pre-registered adaptation study on a real network with synthetic training data only.

> **In our experiments, synthetic-only transfer of GENCO to a real distribution grid needed more than exposure to the target topology: synthetic data covering realistic operating regimes, and an objective that explicitly teaches physically meaningful sensitivities. Even then, accurate states, accurate sensitivities and global physical conservation behaved as distinct properties, which suggests reporting them as separate metrics and, potentially, giving each its own training signal.**

**Limitations, stated plainly:**
- **Full transfer is not achieved.** No stage passes the complete pre-registered real-transfer gate. E5d is not a validated operational model.
- **The 2024 results are not independently reproducible yet.** The release reproduces the synthetic findings only.
- **Seed stability.** Response-aware training varied strongly across seeds, and the findings are not consistently reproduced across training seeds. Selection used synthetic criteria only.
- **The weather question is unresolved.** The pre-registered weather test runs only after full transfer succeeds, so we make no claim either way about weather's effect on GENCO.
- **One network, one satellite pixel.** Sundon's 2024 PV of 1 MW and above sits in one satellite pixel, so spatial weather structure could not be tested.
- **Generator encoding.** From E5c on, our representation places the Leighton Buzzard generators on PQ buses, so their generation is omitted from the model's internal physics feedback (§7). Evaluation uses the correct generation values, so the reported metrics stand, but the effect of correcting it is not assessed in the results reported here.

**Research directions these results point to:**
- **Joint physical consistency:** approaches that improve nodal and network-wide power balance while preserving accurate renewable-generation responses and absolute-state predictions, with our generator representation corrected and assessed separately, and any gain confirmed on an untouched real evaluation period.
- **Calibration of the absolute import:** on held-out synthetic states the adapted import is compressed toward about 56 MW, so the representation and conditioning of the slack injection are concrete levers.
- **Replication:** a second network with metered solar circuits and plants spanning several independent satellite pixels, to test whether the findings replicate and whether spatial weather structure matters.

## Team, acknowledgements, contact and licences

- 👤 **Team:** Oriol Hinojo
- ✉️ **Contact:** [open an issue](https://github.com/hinox13/grid2cloud/issues)
- 🙏 **Acknowledgements:** Cloud2Grid builds on GENCO ([Puech et al., 2026](https://arxiv.org/abs/2608.09921)) and the open GridFM ecosystem: the [`gridfm/genco-pf-transfer`](https://huggingface.co/gridfm/genco-pf-transfer) checkpoint, [gridfm-graphkit](https://github.com/gridfm/gridfm-graphkit) for fine-tuning and inference, and [gridfm-datakit](https://github.com/gridfm/gridfm-datakit) for synthetic AC data. Every adaptation step here used them. We also thank UK Power Networks and EUMETSAT / LSA SAF for their open data, and the pandapower, PowerModels and pvlib projects.
- 🖥️ [Explorer](https://cloud2grid.streamlit.app/) · 💻 [Code](https://github.com/hinox13/grid2cloud) · 📦 [Models](https://github.com/hinox13/grid2cloud/releases/tag/cloud2grid-models-v1) · 🔁 [Reproduction](https://github.com/hinox13/grid2cloud/blob/cloud2grid-models-v1/reproduce/README.md)

*Contains modified EUMETSAT Meteosat and LSA SAF data (CC BY 4.0) and UK Power Networks data (CC BY 4.0), which include ONS data (OGL v3.0) and OS data © Crown copyright. GENCO / gridfm: Apache-2.0. Cloud2Grid code and released weights © 2026 Oriol Hinojo, Apache-2.0; verification data CC BY 4.0. Third-party data keep their own licences and are not redistributed; per-source attribution: [`docs/DATA_LICENSES.md`](https://github.com/hinox13/grid2cloud/blob/main/docs/DATA_LICENSES.md) and [`NOTICE`](https://github.com/hinox13/grid2cloud/blob/main/NOTICE).*
