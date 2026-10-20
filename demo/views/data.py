"""Data & attribution: sources, licences, modifications, provenance of the demo bundles."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from c2g import data as D
from c2g import theme as T

T.setup("Data & attribution")
att = D.attribution()
cat = D.catalog()
models = D.models()

st.markdown("## Data & attribution")
st.markdown(
    '<div class="c2g-sub">This demo only redistributes derived and processed data whose licences '
    "allow it. Every source passed the project's licence gate for <i>redistribute_derived</i> "
    "when the bundles were built.</div>",
    unsafe_allow_html=True,
)

st.markdown("### Provenance classes")
st.markdown(
    f"""
| Class | Meaning in this demo |
|---|---|
| {T.PROVENANCE["OBSERVED"]} | Meteosat E-View imagery; UKPN half-hourly operational load data |
| {T.PROVENANCE["DERIVED"]} | Satellite irradiance at PV assets; estimated PV (pvlib); errors |
| {T.PROVENANCE["SIMULATED"]} | AC power flow on the reconstructed Sundon network |
| {T.PROVENANCE["PREDICTED"]} | Frozen GENCO models (off-the-shelf and four tuned variants) |
"""
)

st.markdown("### Sources and credits")
year = "2024"  # every hero event is from 2024
items = []
for src in att["sources"]:
    credit = src["attribution"].replace("[year]", year)
    link = f' · <a href="{src["licence_url"]}">{src["licence"]}</a>' if src["licence_url"] else ""
    items.append(f"<li><code>{src['source_id']}</code> — {credit}{link}</li>")
ci = D.DATA / "cloud_impact" / "provenance.json"
if ci.exists():  # the Cloud Impact page's market prices (licence-gated when its bundle was built)
    lic = "https://www.elexon.co.uk/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/"
    items.append(
        "<li><code>elexon_bmrs_market_index</code>, <code>elexon_bmrs_system_prices</code> — "
        f"Contains BMRS data © Elexon Limited copyright and database right {year} · "
        f'<a href="{lic}">BMRS data licence</a> (Cloud Impact page)</li>'
    )
st.markdown(f'<ul style="line-height:1.55">{"".join(items)}</ul>', unsafe_allow_html=True)
st.markdown(f'<div class="c2g-callout">{att["modified_notice"]}</div>', unsafe_allow_html=True)

st.markdown("### What is in the public bundle")
st.markdown(
    """
- Meteosat E-View frames for the three hero events only (re-encoded as WebP, unchanged extent).
- Satellite irradiance and estimated PV at registered PV assets (asset id, capacity, location;
  no customer fields).
- The reconstructed Sundon network (node names, voltages, published coordinates where known).
- AC and GENCO states for the hero events, and published summary tables.
- **Not included:** raw satellite files, raw UKPN files, model weights, credentials.
"""
)

st.markdown("### Reproducibility")
st.markdown(
    f"""
- Bundle schema `{cat["schema_version"]}`, built from commit `{cat["git_commit"][:10]}`
  {"(working tree had uncommitted changes)" if cat.get("working_tree_dirty") else ""}.
- Rebuild offline with `uv run python scripts/build_demo_events.py`. The app itself runs no power
  flow, no GENCO inference, no downloads and no training.
"""
)
ck = pd.DataFrame(
    [
        {
            "Model": f"{T.NAMES[m['id']]} ({T.EXP[m['id']]})",
            "Run": m.get("selected_run", "—"),
            "Checkpoint": (m["checkpoint_sha256"][:16] + "…")
            if m.get("checkpoint_sha256")
            else m.get("checkpoint_ref", "—"),
            "Registry": m.get("registry") or "—",
        }
        for m in models
    ]
)
T.html_table(ck)
with st.expander("Published tables used (sha256)"):
    T.html_table(
        pd.DataFrame(
            {
                "Table": list(cat["published_tables"]),
                "sha256": list(cat["published_tables"].values()),
            }
        )
    )
with st.expander("Licence-gate decisions"):
    T.html_table(pd.DataFrame(att["gate_decisions"]))
T.footer()
