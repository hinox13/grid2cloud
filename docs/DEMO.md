# Cloud2Grid Explorer: run and deploy

The Explorer replays **frozen** research results. It opens on an **Overview** (the question,
the finding and one frozen moment of the story); the interactive replay is the **Demo** page.
It never runs an AC power flow, GENCO inference, satellite download or training. Everything it
shows is precomputed in `data/demo/` by `scripts/build_demo_events.py`.

## Run locally

```bash
uv sync --group demo
uv run --group demo streamlit run demo/streamlit_app.py
# → http://localhost:8501
```

Without uv, use `pip install -r demo/requirements.txt` and then
`streamlit run demo/streamlit_app.py`. The app looks for bundles in `data/demo/`; set
`C2G_DEMO_DATA=/path/to/bundles` to point it elsewhere.

## Rebuild the bundles (offline, research machine only)

```bash
uv run python scripts/build_demo_events.py
```

The build needs these local research outputs:
- frozen predictions under `data/interim/{e4,e5,e5b,e5c}/predictions`;
- the S1 dataset and gates;
- the E3 satellite tables in `data/processed/satellite/sundon`;
- the cached E-View frames.

The build:
- checks every source in `configs/app/demo_events.yaml` against the licence gate for
  `redistribute_derived` and stops if any is refused;
- uses only the frozen hero events and the frozen checkpoint registries;
- checks that the AC reference is identical across all prediction sets;
- checks that the S1 PV slopes it recomputes equal the published ones.

| Output | Content |
|---|---|
| `data/demo/catalog.json` | events, models, S1 regression coefficients, build commit, sha256 of the published tables |
| `data/demo/models.json` | model registry: label, frozen run, checkpoint sha256, finding |
| `data/demo/model_evolution.csv` | published real-transfer metrics, copied verbatim |
| `data/demo/pv_response_s1.parquet` | per S1 state: inputs, imports, partial residuals |
| `data/demo/attribution.json` | sources, licences, gate decisions, modification notice |
| `data/demo/events/<id>/` | one bundle per hero event (schema `metadata/event_bundle_schema.yaml` v0.3) |

The whole set is about 3 MB.

## Hero events

| Bundle | Frozen source events | Satellite frames | Grid states |
|---|---|---|---|
| `jun15_cloud_clearing` | B02_20240615T0845, D01_20240615T0930 | 15 (08:45–12:15 UTC) | 7 |
| `apr15_broken_cumulus` | C01_20240415T1215 | 12 (12:15–15:00 UTC) | 6 |
| `aug23_clear_control` | A02_20240823T1045 | 12 (10:45–13:30 UTC) | 6 |

Grid states are the half-hourly real 2024 states (S1) behind every published metric. All five
models already have frozen predictions on them. The response-aware model (E5d) is replayed from
its frozen real-transfer predictions; no 15-minute, ramp or weather prediction was made for it
(its pre-registered rule stopped after the transfer verdict, E5D-D). Satellite and PV are 15-minute; between grid
states the app holds the last state and labels it.

## Story mode

**Play the 15 June story** (on the Overview or the Demo page) runs a fixed, captioned sequence
over the frozen B02/D01 clearing in six scenes, shown like slides. Within a scene, image steps
advance every second and a change of model keeps its authored hold; at the end of each scene the
story waits for **Next** (**Back** returns to the previous scene, **Exit** leaves it). With
**Auto-play** on, it continues to the next scene after the authored hold:

1. **A real cloud field over Sundon**: observed E-View imagery.
2. **Satellite observations become PV forcing**: LSA SAF radiation → estimated PV.
3. **The physical grid responds**: AC import at 11:00 → 11:30, and the PV share of that change.
4. **GENCO transfer**: zero-shot failure, then E5b and E5c.
5. **The blind spot**: AC versus E5c PV slopes.
6. **Learning the response**: E5d's PV and load slopes, and its +13 MW import bias, ending with a
   link to the PV page. Skipped automatically if E5d is not in the bundle.

The script is `configs/app/story_jun15.yaml`, shipped as `data/demo/story_jun15.json`. Its
captions are templates. Every number is filled from the frozen bundle or the published S1
coefficients, and a test checks that every caption resolves.

## Playback

The satellite panel is plain HTML (`demo/c2g/satellite.py`): the previous frame sits underneath
and the current frame fades in on top, so consecutive real 15-minute images dissolve into each
other during Play and when scrubbing. The cross-fade is a display transition between two real
frames; no intermediate image is synthesised or stored. The overlay (study area, substations,
PV assets, reference towns) is an SVG image, because `st.html` strips inline SVG; it therefore
has no hover tooltips. In story mode the Demo page switches to a two-panel "cinema" layout, and
scenes 3 and 5 shade the 11:00–11:30 interval on the timeline.

## Themes

Light ("daylight sky") is the default. The **Dark** switch at the top right of every page flips
the session to the "night sky" palette; it persists while navigating between pages, and a link
with `?theme=dark` (e.g. `http://localhost:8501/?theme=dark`) starts a session in dark mode for
presenting in a dark room. Palettes live in `demo/c2g/theme.py`: the dataviz LIGHT- and
DARK-mode series steps; E5 and E5b fall below 3:1 on white, so their charts always carry
legends, direct labels or a table. E5d is a plum (light `#751e5f`, dark `#e39ecc`), the hue that
stays furthest from every other series in both modes under simulated colour-vision deficiency. The satellite panel keeps a dark frame and white overlay in
both modes. Tables are HTML (Streamlit's canvas grid cannot follow the switch).

## Network schematic

`configs/app/network_layout.yaml` fixes the position of every GENCO bus. The rows follow the
voltage hierarchy: 132 kV supply, grid transformers, the Sundon 33 kV busbar, the 33 kV feeder
row, then the 11 kV primary busbars. SUND11 and SUND31 are drawn as busbars with vertical
drops. The real 33 kV ring through GFSF, MRFM and Leighton Buzzard is drawn as a rectangle. The
layout is an electrical schematic, not a map; real coordinates are used only on the satellite
panel.

## Adding a model

Models are generic. To add one, append an entry under `models:` in
`configs/app/demo_events.yaml` with its frozen registry and prediction template, add a colour
in `demo/c2g/theme.py` (`MODEL_COLOURS`, `NAMES`, `EXP`, `ABOUT`, `VERDICT`), and rebuild.
The pages iterate over `models.json`. E5d is optional: remove its entry and the PV page falls
back to the E5c blind spot, the "What did we learn?" ladder shows four stages and the story
skips its sixth scene (tested with a bundle stripped of E5d).

## Deploy to Streamlit Community Cloud

1. Commit `demo/`, `.streamlit/config.toml` and `data/demo/`. `.gitignore` un-ignores
   `data/demo/` because the bundles are derived and licence-gated.
2. On share.streamlit.io choose **New app**, then select the repository and branch.
3. Set **Main file path** to `demo/streamlit_app.py`. Streamlit Cloud installs
   `demo/requirements.txt` (streamlit, plotly, pandas, pyarrow, numpy), which it finds in the
   entry-point folder before the root `uv.lock`. No torch, pandapower or GENCO is installed.
4. Python 3.11. No secrets are needed: the app reads no credentials and makes no external
   requests.

Resource use: the app holds about 3 MB of data in memory; each Play step re-renders three small
Plotly figures. It fits the free tier.

## Attribution obligations

The **Data & attribution** page and the footer of every page carry the registry attribution
text, the licence links and the "modified" notice (CC BY 4.0 for EUMETSAT, LSA SAF and UKPN;
Apache-2.0 for GENCO and gridfm). Keep both if you restyle the app.
