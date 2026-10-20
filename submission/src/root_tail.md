
---

## Run it locally

```bash
git clone https://github.com/hinox13/grid2cloud && cd grid2cloud
uv sync --group demo
uv run --group demo streamlit run demo/streamlit_app.py   # the Explorer, CPU only
uv sync --extra genco
uv run python reproduce/verify_models.py                  # verify the frozen models
uv sync && uv run pytest                                  # the test suite
```

## Repository map

| Path | Contents |
|---|---|
| [`demo/`](demo/) | the Cloud2Grid Explorer (Streamlit) and its frozen bundles in [`data/demo/`](data/demo/) |
| [`reproduce/`](reproduce/) | one-command verification of the released checkpoints |
| [`release/models-v1/`](release/models-v1/) | model cards, checksums and build records of `cloud2grid-models-v1` |
| [`reports/`](reports/) | one report per experiment (E0–E6), with tables and figures; clean-room verification records in [`reports/model_release_v1/`](reports/model_release_v1/) |
| [`configs/`](configs/), [`metadata/`](metadata/) | pre-registrations, frozen protocols, checkpoint registries, licence manifest |
| [`src/cloud2grid/`](src/cloud2grid/), [`scripts/`](scripts/) | the pipeline: network reconstruction, satellite PV, scenarios, GENCO adaptation, evaluation |
| [`tests/`](tests/) | 257 automated tests ([why some skip on a clone](docs/TECHNICAL_NOTES.md#automated-tests)) |
| [`docs/`](docs/) | [technical notes](docs/TECHNICAL_NOTES.md), [data licences](docs/DATA_LICENSES.md), [Explorer deployment](docs/DEMO.md), [project design document](docs/PROJECT_DESIGN.md) |
| [`submission/`](submission/) | the challenge write-up, its figures, screenshots, [figure manifest](submission/FIGURE_MANIFEST.md) and the scripts that build and check them |

**Design document.** The original project design (source registry, hypotheses, data philosophy, study-area selection and the experiment plan) is kept unchanged in [`docs/PROJECT_DESIGN.md`](docs/PROJECT_DESIGN.md). Configs and reports cite it as "README §N".

**Repository snapshot.** This repository is a single snapshot of the final project state; the development history is not included. Commit IDs cited in reports, registries and bundle metadata (pre-registration, freeze and build commits) refer to that development history.
