"""Render the repository README from the approved submission text (publication repository only).

    python submission/render_readme.py           # write README.md
    python submission/render_readme.py --check   # exit 1 if README.md is not the current rendering

README.md = the README title line + submission/Cloud2Grid_submission_final.md after its title (the
approved challenge text, unchanged except that figure paths become relative to the repository root)
+ submission/src/root_tail.md (how to run it, repository map). No sentence is edited here.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "submission/Cloud2Grid_submission_final.md"
TAIL = ROOT / "submission/src/root_tail.md"
OUT = ROOT / "README.md"
SRC_TITLE = "# Cloud2Grid: from real clouds to electric grid intelligence"
README_TITLE = "# ☁️⚡ Cloud2Grid: from real clouds to electric grid intelligence"


def render() -> str:
    first, body = SRC.read_text().split("\n", 1)
    assert first == SRC_TITLE, f"unexpected title in {SRC.name}: {first!r}"
    body = body.replace("](figures/", "](submission/figures/")
    assert "](figures/" not in body
    text = README_TITLE + "\n" + body.rstrip() + "\n" + TAIL.read_text()
    assert not re.search(r"(/home/|/tmp/|file://|C:\\\\)", text), "local path in output"
    return text.rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    text = render()
    if a.check:
        ok = OUT.read_text() == text
        print("README.md is current" if ok else "README.md differs from the rendering")
        return 0 if ok else 1
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
