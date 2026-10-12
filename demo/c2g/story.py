"""Guided story: a fixed sequence of beats over one frozen event, with factual captions.

Script: data/demo/story_jun15.json (from configs/app/story_jun15.yaml). Caption numbers come
only from the bundle (summary, fleet PV, event metrics, S1 inputs) and the published S1
coefficients in catalog.json — the story computes nothing new."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd
import streamlit as st

from c2g import data as D


@dataclass(frozen=True)
class Beat:
    scene: int
    title: str
    watch: str
    t: int
    model: str
    hold: int
    caption: str
    highlight: str = ""  # timeline band label over refs a → b ("" = none)


@st.cache_data(show_spinner=False)
def script() -> dict:
    return json.loads((D.DATA / "story_jun15.json").read_text())


@st.cache_data(show_spinner=False)
def beats() -> list[Beat]:
    out = []
    listed = {"AC", *(m["id"] for m in D.models())}
    scenes = [sc for sc in script()["scenes"] if all(b["model"] in listed for b in sc["beats"])]
    for k, sc in enumerate(scenes):
        for b in sc["beats"]:
            cap = sc.get("caption_by_model", {}).get(b["model"], sc.get("caption", ""))
            out.append(
                Beat(
                    k,
                    sc["title"],
                    sc["watch"],
                    b["t"],
                    b["model"],
                    b["hold"],
                    cap,
                    sc.get("highlight", ""),
                )
            )
    return out


def n_scenes() -> int:
    return beats()[-1].scene + 1


@st.cache_data(show_spinner=False)
def _static_vars() -> dict:
    """Event-level numbers: fixed for the whole story."""
    sc = script()
    ev = D.event(sc["event"])
    cat = D.catalog()
    evo = D.evolution()
    co = cat["ols_coefficients_s1"]
    a, b = (pd.Timestamp(sc["refs"][k]) for k in ("a", "b"))
    s = ev.summary.set_index(["timestamp_utc", "model"])
    first = ev.meta["source_events"][0]
    em = {m["event_id"]: m for m in ev.meta["event_metrics"]}[first]
    hv = ev.summary[ev.summary.model == "AC"].set_index("timestamp_utc").p_hv_injected_mw
    # HV PV injection change between the two grid slots, from the S1 inputs (as on the PV page)
    x = D.pv_response().set_index("scenario")
    ids = dict(
        zip(pd.to_datetime(ev.meta["grid_slots_utc"]), ev.meta["grid_scenarios"], strict=True)
    )
    dhv = x.at[ids[b], "pv_injection_mw"] - x.at[ids[a], "pv_injection_mw"]
    out = {
        "pv_cap": f"{ev.meta['active_pv_capacity_mw']:.1f}",
        "cloudy_start": f"{em['field_frac_cloudy_start']:.0%}".replace("%", " %"),
        "ac_a": f"{s.at[(a, 'AC'), 'import_mw']:.0f}",
        "ac_b": f"{s.at[(b, 'AC'), 'import_mw']:.0f}",
        "hv_a": f"{hv[a]:.1f}",
        "hv_b": f"{hv[b]:.1f}",
        "dhv": f"{dhv:+.1f}",
        "ac_pv_term": f"{co['AC']['pv'] * dhv:+.1f}",
        "s_ac_pv": f"{co['AC']['pv']:+.2f}",
        "s_e5c_pv": f"{co['E5c']['pv']:+.2f}",
        "s_ac_bat": f"{co['AC']['chap31']:+.2f}",
        "s_e5c_bat": f"{co['E5c']['chap31']:+.2f}",
        "pct_e5c_pv": f"{co['E5c']['pv'] / co['AC']['pv']:.0%}".replace("%", " %"),
        "pbe_zs": f"{evo.at['zero_shot', 'PBE_mean']:.1f}",
        "pbe_e5b": f"{evo.at['E5b', 'PBE_mean']:.2f}",
        "pbe_e5c": f"{evo.at['E5c', 'PBE_mean']:.2f}",
        "s_ac_load": f"{co['AC']['load']:+.2f}",
    }
    if "E5d" in co:  # optional model: its scene is skipped when it is not in the bundle
        out["s_e5d_pv"] = f"{co['E5d']['pv']:+.2f}"
        out["s_e5d_load"] = f"{co['E5d']['load']:+.2f}"
        out["bias_e5d"] = f"{evo.at['E5d', 'import_bias_mw']:+.0f}"
    return out


def caption(beat: Beat, t: pd.Timestamp, pv: float, ac: float, model_imp: float) -> str:
    v = dict(_static_vars())
    v.update(
        time=f"{t:%H:%M}",
        pv=f"{pv:.1f}",
        ac=f"{ac:.0f}",
        model=f"{model_imp:.0f}",
        err=f"{model_imp - ac:+.0f}",
    )
    return beat.caption.format(**v)


def band(beat: Beat) -> tuple[pd.Timestamp, pd.Timestamp, str] | None:
    """Timeline band for scenes that point at the refs a → b interval."""
    if not beat.highlight:
        return None
    r = script()["refs"]
    return pd.Timestamp(r["a"]), pd.Timestamp(r["b"]), beat.highlight
