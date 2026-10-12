"""Report satellite storage and clean regenerable caches (disk is limited).

    uv run python scripts/satellite_storage.py                     # report only
    uv run python scripts/satellite_storage.py --clean raw-bulk    # delete regenerable items
    uv run python scripts/satellite_storage.py --clean partial frames raw-bulk --yes

Categories
    raw         data/raw/satellite/**            (static geometry + first-file gate file)
    crops       data/interim/satellite/lsasaf/** (reproducible cropped products)
    frames      data/interim/satellite/eumetsat/** (RGB frames; regenerable from WMS)
    processed   data/processed/satellite/**      (final per-asset / per-bus series)
Cleanable (all regenerable from their recorded source URLs):
    partial     *.part files left by interrupted downloads
    raw-bulk    data/raw/satellite/lsasaf/tmp/** (full files kept only transiently)
    frames      RGB frames
    crops       cropped MDSSFTD (re-download required)
Static geometry, the first-file gate file and processed series are never deleted here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cloud2grid.licensing.registry import REPO_ROOT

AREAS = {
    "raw": REPO_ROOT / "data/raw/satellite",
    "crops": REPO_ROOT / "data/interim/satellite/lsasaf",
    "frames": REPO_ROOT / "data/interim/satellite/eumetsat",
    "processed": REPO_ROOT / "data/processed/satellite",
}
CLEANABLE = {
    "partial": lambda: [p for a in AREAS.values() if a.exists() for p in a.rglob("*.part")],
    "raw-bulk": lambda: [p for p in (AREAS["raw"] / "lsasaf/tmp").rglob("*") if p.is_file()],
    "frames": lambda: [p for p in AREAS["frames"].rglob("*") if p.is_file()],
    "crops": lambda: [p for p in AREAS["crops"].rglob("*") if p.is_file()],
}


def size(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    files = [p for p in path.rglob("*") if p.is_file()]
    return sum(p.stat().st_size for p in files), len(files)


def report() -> dict[str, dict[str, int]]:
    return {k: dict(zip(("bytes", "files"), size(p), strict=True)) for k, p in AREAS.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", nargs="*", choices=sorted(CLEANABLE), default=[])
    ap.add_argument("--yes", action="store_true", help="actually delete (default: dry run)")
    args = ap.parse_args()
    rep = report()
    print(json.dumps(rep, indent=1))
    for cat in args.clean:
        files = CLEANABLE[cat]()
        total = sum(p.stat().st_size for p in files)
        action = "deleted" if args.yes else "(dry run)"
        print(f"{cat}: {len(files)} files, {total / 1e6:.1f} MB {action}")
        if args.yes:
            for p in files:
                p.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
