"""Demo bundles: structure, model genericity, provenance and the no-heavy-deps rule for the app.

Skipped when the bundles have not been built (data/demo is produced offline)."""

import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "data/demo"
pytestmark = pytest.mark.skipif(not (DEMO / "catalog.json").exists(), reason="bundles not built")

EVENT_FILES = [
    "metadata.json",
    "attribution.json",
    "satellite/frames.parquet",
    "irradiance.parquet",
    "pv_generation.parquet",
    "pv_by_bus.parquet",
    "fleet_pv.parquet",
    "loads.parquet",
    "ac_reference.parquet",
    "ac_reference_branches.parquet",
    "genco.parquet",
    "genco_branches.parquet",
    "errors.parquet",
    "summary.parquet",
    "network_nodes.parquet",
    "network_edges.parquet",
    "assets.parquet",
]


def catalog() -> dict:
    return json.loads((DEMO / "catalog.json").read_text())


def test_events_are_frozen_heroes_and_complete():
    import yaml

    heroes = set(
        yaml.safe_load((ROOT / "configs/experiments/e5_topology_adaptation.yaml").read_text())[
            "repeat_e4"
        ]["heroes"]
    )
    for ev in catalog()["events"]:
        assert set(ev["source_events"]) <= heroes
        d = DEMO / "events" / ev["event_id"]
        for f in EVENT_FILES:
            assert (d / f).exists(), f"{ev['event_id']}: missing {f}"
        frames = pd.read_parquet(d / "satellite/frames.parquet")
        assert len(frames) == ev["n_frames"] > 0
        assert all((d / f).exists() for f in frames.image_file)


def test_every_listed_model_present_for_every_grid_state():
    models = catalog()["models"]
    assert models == [m["id"] for m in json.loads((DEMO / "models.json").read_text())]
    for ev in catalog()["events"]:
        s = pd.read_parquet(DEMO / "events" / ev["event_id"] / "summary.parquet")
        counts = s.groupby("timestamp_utc").model.apply(set)
        assert all(c == {"AC", *models} for c in counts)
        assert len(counts) == ev["n_grid_slots"]


def test_published_tables_and_slopes_unchanged():
    import hashlib

    cat = catalog()
    for path, sha in cat["published_tables"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == sha
    evo = pd.read_csv(DEMO / "model_evolution.csv").set_index("model")
    for m in cat["models"]:
        assert abs(cat["ols_coefficients_s1"][m]["pv"] - evo.at[m, "genco_slope_pv"]) < 1e-6


def test_licence_gate_recorded_and_no_secrets():
    att = json.loads((DEMO / "attribution.json").read_text())
    assert att["gate_decisions"] and all(d["allowed"] for d in att["gate_decisions"])
    assert all(s["attribution"] for s in att["sources"])
    blob = "".join(p.read_text(errors="ignore") for p in DEMO.rglob("*.json"))
    for word in ("password", "token", "secret", "api_key", "consumer_key"):
        assert word not in blob.lower()


def test_assets_carry_no_customer_fields():
    cols = set(pd.read_parquet(DEMO / "events/jun15_cloud_clearing/assets.parquet").columns)
    assert cols <= {
        "asset_id",
        "technology",
        "capacity_mw",
        "connection_voltage_kv",
        "attributed_nodes",
        "lat",
        "lon",
    }


def test_app_imports_no_research_stack():
    banned = ("cloud2grid", "torch", "pandapower", "gridfm", "xarray", "pvlib")
    for f in (ROOT / "demo").rglob("*.py"):
        src = f.read_text()
        for b in banned:
            assert f"import {b}" not in src and f"from {b}" not in src, f"{f} imports {b}"


def test_network_layout_is_manual_and_complete():
    import yaml

    lay = yaml.safe_load((ROOT / "configs/app/network_layout.yaml").read_text())
    nodes = pd.read_parquet(DEMO / "network_nodes.parquet")
    assert set(lay["nodes"]) == set(nodes.node_key)
    xy = nodes.set_index("node_key")[["schematic_x", "schematic_y"]]
    for k, (x, y) in lay["nodes"].items():
        assert (xy.at[k, "schematic_x"], xy.at[k, "schematic_y"]) == (x, y)
    assert len({tuple(v) for v in lay["nodes"].values()}) == len(lay["nodes"])  # no overlaps
    # voltage hierarchy: every 132 kV node above every 33 kV node above every 11 kV node
    by_kv = nodes.groupby("vn_kv").schematic_y
    assert by_kv.min()[132.0] > by_kv.max()[33.0] > by_kv.max()[11.0]


def test_story_beats_valid_and_captions_resolve():
    import sys

    story = json.loads((DEMO / "story_jun15.json").read_text())
    cat = catalog()
    ev = next(e for e in cat["events"] if e["event_id"] == story["event"])
    assert {"B02_20240615T0845", "D01_20240615T0930"} == set(ev["source_events"])
    models = {"AC", *cat["models"]}
    for sc in story["scenes"]:
        for b in sc["beats"]:
            assert 0 <= b["t"] < ev["n_frames"] and b["model"] in models
    sys.path.insert(0, str(ROOT / "demo"))
    from c2g import story as S

    for beat in S.beats():  # every caption template fills from bundle values only
        text = S.caption(beat, pd.Timestamp("2024-06-15T11:30Z"), 8.9, 34.0, 47.9)
        assert "{" not in text and "}" not in text


def test_satellite_crossfade_only_between_real_frames():
    import sys

    sys.path.insert(0, str(ROOT / "demo"))
    from c2g import data as D
    from c2g import satellite as SAT

    ev = D.event("jun15_cloud_clearing")
    f0, f1 = ev.frames.iloc[0], ev.frames.iloc[1]
    args = (ev.nodes, ev.edges, ev.assets, None, False)
    moving = SAT.render(f1, f0, *args)
    still = SAT.render(f1, f1, *args)
    assert "c2gfade" in moving and "c2gfade" not in still
    # exactly the two real frames (previous under, current on top) + the overlay image
    assert moving.count(f0.data_uri) == 1 and moving.count(f1.data_uri) == 1
    assert "<svg" not in moving  # st.html strips inline SVG: overlay must be an image
    assert "scale(" in SAT.render(f1, f0, ev.nodes, ev.edges, ev.assets, None, True)


def test_timeline_band_keeps_time_axis():
    """Regression: the band label must not be moved to x=0 (1970) by the title alignment."""
    import sys

    sys.path.insert(0, str(ROOT / "demo"))
    from c2g import data as D
    from c2g import figures as F
    from c2g import story as S

    ev = D.event("jun15_cloud_clearing")
    band = S.band(next(b for b in S.beats() if b.highlight))
    t = ev.steps[9]
    fig = F.timeline(ev.fleet_pv, ev.summary, "E5c", t, ev.grid_slot_for(t), band=band)
    on_axis = [a for a in fig.layout.annotations if a.xref not in ("paper",)]
    assert on_axis and all(pd.Timestamp(a.x) == band[0] + (band[1] - band[0]) / 2 for a in on_axis)


def test_both_palettes_readable_and_tokens_resolve():
    import sys

    sys.path.insert(0, str(ROOT / "demo"))
    from c2g import theme as T

    def lum(h: str) -> float:
        c = [int(h.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    def cr(a: str, b: str) -> float:
        la, lb = sorted((lum(a), lum(b)), reverse=True)
        return (la + 0.05) / (lb + 0.05)

    for p in (T.LIGHT, T.DARK):
        for k in ("INK", "INK_2", "MUTED", "ACCENT_TEXT"):
            assert cr(p[k], p["SURFACE"]) >= 4.5, (p["MODE"], k)
        assert cr(p["ACCENT_INK"], p["ACCENT"]) >= 4.5
        assert set(p["MODEL_COLOURS"]) == {"zero_shot", "E5", "E5b", "E5c", "E5d"}
        assert cr(p["MODEL_COLOURS"]["E5d"], p["SURFACE"]) >= 3.0  # E5/E5b light: relief rule
    assert T.LIGHT["SURFACE"] == T.SURFACE and T.LIGHT["INK"] == T.AC  # no session: light
