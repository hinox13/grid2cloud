"""Cloud2Grid Explorer — entry point.

    uv run --group demo streamlit run demo/streamlit_app.py

Reads only the precomputed bundles in data/demo (scripts/build_demo_events.py). CPU only: no AC
power flow, GENCO inference, satellite download or training happens in the app."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

st.set_page_config(
    page_title="Cloud2Grid Explorer",
    page_icon=":material/cloud:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

VIEWS = Path(__file__).resolve().parent / "views"
nav = st.navigation(
    [
        st.Page(
            VIEWS / "explorer.py", title="Explorer", icon=":material/satellite_alt:", default=True
        ),
        st.Page(VIEWS / "pv_response.py", title="PV response", icon=":material/wb_sunny:"),
        st.Page(VIEWS / "evolution.py", title="Model evolution", icon=":material/trending_up:"),
        st.Page(VIEWS / "story.py", title="Scientific story", icon=":material/explore:"),
        st.Page(VIEWS / "data.py", title="Data & attribution", icon=":material/description:"),
    ],
    position="top",
)
nav.run()
