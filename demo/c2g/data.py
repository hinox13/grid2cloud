"""Bundle loading for the Cloud2Grid Explorer. Reads ONLY precomputed files under data/demo
(built offline by scripts/build_demo_events.py). No power flow, inference or download here."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

DATA = Path(os.environ.get("C2G_DEMO_DATA", Path(__file__).resolve().parents[2] / "data/demo"))


@st.cache_data(show_spinner=False)
def catalog() -> dict:
    return json.loads((DATA / "catalog.json").read_text())


@st.cache_data(show_spinner=False)
def models() -> list[dict]:
    return json.loads((DATA / "models.json").read_text())


@st.cache_data(show_spinner=False)
def attribution() -> dict:
    return json.loads((DATA / "attribution.json").read_text())


@st.cache_data(show_spinner=False)
def evolution() -> pd.DataFrame:
    return pd.read_csv(DATA / "model_evolution.csv").set_index("model")


@st.cache_data(show_spinner=False)
def network_layout() -> dict:
    return json.loads((DATA / "network_layout.json").read_text())


@st.cache_data(show_spinner=False)
def pv_response() -> pd.DataFrame:
    return pd.read_parquet(DATA / "pv_response_s1.parquet")


@dataclass(frozen=True)
class Event:
    meta: dict
    frames: pd.DataFrame  # 15-min satellite frames (+ base64 image)
    fleet_pv: pd.DataFrame  # 15-min satellite-derived fleet PV
    irradiance: pd.DataFrame  # per asset, 15-min
    pv_generation: pd.DataFrame  # per asset, 15-min
    summary: pd.DataFrame  # per grid slot × model
    bus: pd.DataFrame  # per grid slot × model × bus (AC + models)
    branch: pd.DataFrame  # per grid slot × model × branch (AC + models)
    nodes: pd.DataFrame
    edges: pd.DataFrame
    assets: pd.DataFrame
    loads: pd.DataFrame

    @property
    def steps(self) -> list[pd.Timestamp]:
        return list(self.frames.timestamp_utc)

    @property
    def grid_slots(self) -> list[pd.Timestamp]:
        return sorted(self.summary.timestamp_utc.unique())

    def grid_slot_for(self, t: pd.Timestamp) -> pd.Timestamp:
        """Latest half-hourly grid state at or before t (never interpolated); before the first
        grid state, the first one (the UI labels which state is shown)."""
        past = [s for s in self.grid_slots if s <= t]
        return past[-1] if past else self.grid_slots[0]


@st.cache_data(show_spinner=False)
def event(bundle_id: str) -> Event:
    d = DATA / "events" / bundle_id
    rd = lambda n: pd.read_parquet(d / n)  # noqa: E731
    frames = rd("satellite/frames.parquet")
    frames["data_uri"] = [
        "data:image/webp;base64," + base64.b64encode((d / f).read_bytes()).decode()
        for f in frames.image_file
    ]
    return Event(
        meta=json.loads((d / "metadata.json").read_text()),
        frames=frames,
        fleet_pv=rd("fleet_pv.parquet"),
        irradiance=rd("irradiance.parquet"),
        pv_generation=rd("pv_generation.parquet"),
        summary=rd("summary.parquet"),
        bus=pd.concat([rd("ac_reference.parquet"), rd("genco.parquet")], ignore_index=True),
        branch=pd.concat(
            [rd("ac_reference_branches.parquet"), rd("genco_branches.parquet")], ignore_index=True
        ),
        nodes=rd("network_nodes.parquet"),
        edges=rd("network_edges.parquet"),
        assets=rd("assets.parquet"),
        loads=rd("loads.parquet"),
    )
