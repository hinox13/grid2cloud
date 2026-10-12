"""E-View frames for the SELECTED candidate events only (no bulk imagery).

    uv run python scripts/fetch_event_frames.py

Reads reports/tables/e3_candidate_events.csv and fetches, for each event window, one cropped
E-View frame per 15-minute slot (context box) from EUMETView WMS: sequential, >= pause_s
between requests. Each frame's served time is read from the server header and paired with the
MDSSFTD slot; pairs beyond configs/data/eumetsat.yaml matching.max_delta_min are rejected and
the frame is not kept. EUMETView re-renders server-side (bytes can differ between fetches), so
the returned frames are preserved locally for the future event bundles.

Outputs
    data/interim/satellite/eumetsat/events/<event_id>/eview_<slot>.png   (gitignored)
    reports/tables/e3_event_frames.csv
    reports/figures/e3_event_<class>.png   (one strip per selected top-ranked event)
"""

from __future__ import annotations

import sys
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402
import yaml  # noqa: E402
from PIL import Image  # noqa: E402

from cloud2grid.licensing import gate  # noqa: E402
from cloud2grid.licensing.registry import REPO_ROOT, Registry  # noqa: E402
from cloud2grid.satellite import eumetsat  # noqa: E402
from cloud2grid.utils import provenance  # noqa: E402

LSA = yaml.safe_load((REPO_ROOT / "configs/data/lsasaf.yaml").read_text())
EUM = yaml.safe_load((REPO_ROOT / "configs/data/eumetsat.yaml").read_text())
TABLES = REPO_ROOT / "reports/tables"
FIGS = REPO_ROOT / "reports/figures"
ACQ_OFFSET_MIN = 11.6467  # native line 306 (Sundon), PUM §6.3
PAUSE_S = 1.0


def main() -> int:
    ev = pd.read_csv(TABLES / "e3_candidate_events.csv", parse_dates=["start", "end"])
    if ev.empty:
        print("no candidate events")
        return 0
    layer = eumetsat.WMSLayer.from_config(EUM, "eview")
    gate.require(layer.source_id, "download", Registry.load())
    bbox = LSA["study_area"]["context_bbox"]
    session = requests.Session()
    rows, last = [], 0.0
    for e in ev.itertuples():
        slots = pd.date_range(e.start, e.end, freq="15min")
        for s in slots:
            wait = PAUSE_S - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            dest = (
                REPO_ROOT
                / EUM["storage"]["frame_dir"]
                / "events"
                / e.event_id
                / f"eview_{s:%Y%m%dT%H%M}.png"
            )
            meta = eumetsat.fetch_frame(
                layer,
                bbox,
                s.to_pydatetime(),
                dest,
                EUM["sample"]["width_px"],
                EUM["sample"]["format"],
                session,
            )
            last = time.monotonic()
            served = pd.Timestamp(meta["served_time"]).to_pydatetime()
            pair = eumetsat.match(
                s.to_pydatetime(),
                s.to_pydatetime(),
                served,
                ACQ_OFFSET_MIN,
                EUM["matching"]["max_delta_min"],
            )
            if not pair["accepted"]:
                dest.unlink(missing_ok=True)
            else:
                provenance.record(
                    dest,
                    source_id=layer.source_id,
                    url=meta["source_url"],
                    licence="CC-BY-4.0",
                    extra={
                        k: meta[k]
                        for k in (
                            "provider",
                            "product",
                            "wms_layer",
                            "requested_time",
                            "served_time",
                            "bbox_wgs84",
                            "crs",
                            "processing_level",
                        )
                    }
                    | {"event_id": e.event_id},
                )
            rows.append(
                {
                    "event_id": e.event_id,
                    "event_class": e.event_class,
                    **pair,
                    "local_path": str(dest.relative_to(REPO_ROOT)) if pair["accepted"] else None,
                    "size_bytes": meta["size_bytes"],
                    "sha256": meta["sha256"],
                }
            )
    tab = pd.DataFrame(rows)
    tab.to_csv(TABLES / "e3_event_frames.csv", index=False)
    # one figure strip per class, top-ranked event: every 3rd frame
    for k, top in ev[ev.rank_in_class == 1].groupby("event_class"):
        e = top.iloc[0]
        fr = tab[(tab.event_id == e.event_id) & tab.accepted].iloc[::3]
        if fr.empty:
            continue
        fig, axes = plt.subplots(1, len(fr), figsize=(3.4 * len(fr), 2.6))
        for ax, r in zip(np.atleast_1d(axes), fr.itertuples(), strict=True):
            ax.imshow(
                Image.open(REPO_ROOT / r.local_path),
                extent=(bbox["lon_min"], bbox["lon_max"], bbox["lat_min"], bbox["lat_max"]),
            )
            ax.plot(-0.60, 51.93, "r+", ms=9)
            ax.set_title(f"{r.rgb_time[11:16]} UTC", fontsize=8)
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_aspect(1 / np.cos(np.radians(52)))
        fig.suptitle(f"{e.event_id} ({e.class_name}) — E-View; + Sundon", fontsize=9)
        fig.text(
            0.01,
            0.01,
            "Contains modified EUMETSAT Meteosat data 2024 (EUMETView WMS; CC BY 4.0).",
            fontsize=6,
        )
        fig.tight_layout(rect=(0, 0.05, 1, 0.92))
        fig.savefig(FIGS / f"e3_event_{k}.png", dpi=110)
        plt.close(fig)
    print(
        tab.groupby("event_class").agg(
            frames=("accepted", "size"),
            accepted=("accepted", "sum"),
            max_delta=("time_delta_min", lambda s: s.abs().max()),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
