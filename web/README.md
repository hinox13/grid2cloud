# Cloud2Grid website

**https://hinox13.github.io/grid2cloud/**

The Cloud2Grid website is one React application with two parts:
- **The Experience** (`#/experience`): a guided story of 15 June 2024 through five steps, Clouds → Energy → Grid → GENCO → Value.
- **Explore the Science** (`#/explore/...`): the model journey, grid events, PV response, model metrics, the economic case study, methods, and data and credits.

The Streamlit Scientific Explorer in [`demo/`](../demo/) remains available at
https://cloud2grid.streamlit.app/.

## How it works

- **Static only.** There is no server and no runtime API call, and no science is computed in the browser. Fonts are self-hosted and nothing is loaded from another origin.
- **Data.** `public/data/` is written by [`scripts/web/export_web_data.py`](../scripts/web/export_web_data.py) from the frozen Explorer bundles in [`data/demo/`](../data/demo/). The export covers:
  - satellite frames, copied byte for byte;
  - network, events, model metrics and the economic study.

  Every figure the site states is a claim in `claims.json`, with its value, unit, display string, provenance class and source. Components render those strings through `<Claim id=…>`. [`tests/web/`](../tests/web/) re-derives the claims independently from `data/demo/`.
- **Evaluation scopes.** Every figure carries one of three labels:
  - **one moment**: the 15 June event, or its controlled 11:00 counterfactual;
  - **average**: the GENCO evaluation over 2,829 half-hours;
  - **economic case study**: one 6 MW plant.
- **Routing.** Routes are hash-based (`#/…`), so a refresh never returns a 404 on GitHub Pages. The base path is `/grid2cloud/`; set `C2G_BASE=/` to serve from a root.

## Commands

From the repository root:

```bash
uv sync --group demo
uv run python scripts/web/export_web_data.py --check   # web/public/data matches data/demo, byte for byte
uv run pytest tests/web                                 # claims re-derived from data/demo
```

From `web/`:

```bash
npm ci
npm run dev            # http://localhost:5173/grid2cloud/
npm run build          # type check + production build into dist/
node pages.mjs         # licence files, .nojekyll and static guards for GitHub Pages
npx playwright test    # browser tests against the built site (Chromium, desktop and phone)
C2G_BROWSERS=firefox npx playwright test --project firefox
C2G_URL=https://hinox13.github.io/grid2cloud/ npx playwright test   # against the live site
```

## Deployment

[`.github/workflows/website.yml`](../.github/workflows/website.yml) runs on every push to `main` that touches the site or its data, and can also be started by hand. It:
1. checks the exported data and claims;
2. builds the site;
3. runs the browser tests;
4. publishes `dist/` as the `gh-pages` branch, which GitHub Pages serves from `/ (root)`.

## Layout

| Path | What |
|---|---|
| `src/scenes/` | the home page, the Experience (beats, words, chapter visuals) and the finale |
| `src/explorer/` | the Explorer pages, loaded as a separate chunk |
| `src/components/` | satellite view, 2D network schematic, time ruler, SVG charts, scope labels, theme |
| `src/data/` | types of the exported JSON, cached loader, `<Claim>`, formatting |
| `src/styles/` | design tokens (dark and light), layout and visualisation CSS |
| `public/data/` | the exported data (generated; do not edit by hand) |
| `tests/e2e/` | Playwright tests: every story step, the brief's figures, the Explorer, phones, offline |
