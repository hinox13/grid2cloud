"""Render the Cloud2Grid write-up from one source (src/post.md) into its three published forms.

    python submission/build_post.py                       # all variants, image URLs on `main`
    python submission/build_post.py --ref <commit-sha>    # pin the Hugging Face image URLs
    python submission/build_post.py --contact a@b.c --affiliation "Independent researcher"

Outputs (all deterministic):
- submission/README.md                      GitHub presentation, relative images (figures/…)
- submission/Cloud2Grid_HuggingFace_READY.md paste-ready Community post, absolute HTTPS images
- submission/promotion/README.md            root README for the publication repository
                                            (images under submission/figures/)

Source markers in src/post.md:
- {{IMG}}name.png        image reference; prefix chosen per variant
- <!--DETAILS summary="…" link="…"--> … <!--/DETAILS-->
                         collapsible <details> on GitHub; on Hugging Face one "More" link line
- {{AFFILIATION}}, {{CONTACT}}  filled from the command line; on Hugging Face left as visible
                         placeholders until given, so an unfinished post cannot look finished
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "src/post.md"
TAIL = HERE / "src/root_tail.md"
REPO = "hinox13/grid2cloud"
PUB_FIG_DIR = "submission/figures"  # same path in the publication repository
FIGURES = sorted(p.name for p in (HERE / "figures").glob("0*.png"))

DETAILS = re.compile(
    r'<!--DETAILS summary="(?P<summary>[^"]+)" link="(?P<link>[^"]+)"-->\n(?P<body>.*?)\n<!--/DETAILS-->',
    re.S,
)


def short(url: str) -> str:
    """Display text for a repository link: the path after blob/<ref>/."""
    return re.sub(r"^https://github.com/[^/]+/[^/]+/blob/[^/]+/", "", url)


def raw_url(ref: str, name: str) -> str:
    return f"https://raw.githubusercontent.com/{REPO}/{ref}/{PUB_FIG_DIR}/{name}"


def render(variant: str, ref: str, contact: str | None, affiliation: str | None) -> str:
    text = SRC.read_text()
    if variant == "hf":
        text = DETAILS.sub(lambda m: f"→ *{m['summary']}:* [`{short(m['link'])}`]({m['link']})", text)
        prefix = None
    else:
        text = DETAILS.sub(
            lambda m: f"<details>\n<summary><b>{m['summary']}</b></summary>\n\n{m['body']}\n\n</details>",
            text,
        )
        prefix = "figures/" if variant == "readme" else f"{PUB_FIG_DIR}/"
    text = re.sub(
        r"\{\{IMG\}\}([\w.-]+\.png)",
        lambda m: raw_url(ref, m[1]) if prefix is None else prefix + m[1],
        text,
    )
    if variant == "hf":
        todo = " [AFFILIATION, or delete this bracket]"
        text = text.replace("{{AFFILIATION}}", f" ({affiliation})" if affiliation else todo)
        text = text.replace("{{CONTACT}}", contact or "[CONTACT EMAIL]")
    else:  # the repository never carries a personal email
        text = text.replace("{{AFFILIATION}}", f" ({affiliation})" if affiliation else "")
        text = text.replace("{{CONTACT}}", f"[open an issue](https://github.com/{REPO}/issues)")
    if variant == "root":
        text = text.rstrip() + "\n" + TAIL.read_text()
    assert "{{" not in text and "<!--DETAILS" not in text, "unrendered marker"
    assert not re.search(r"(/home/|/tmp/|file://|C:\\\\)", text), "local path in output"
    return text.rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", default="main", help="Git ref of the Hugging Face image URLs (branch/commit)")
    ap.add_argument("--contact")
    ap.add_argument("--affiliation")
    a = ap.parse_args()
    used = set(re.findall(r"\{\{IMG\}\}([\w.-]+\.png)", SRC.read_text()))
    assert used == set(FIGURES), f"figures used {sorted(used)} != on disk {FIGURES}"
    out = {
        "readme": HERE / "README.md",
        "hf": HERE / "Cloud2Grid_HuggingFace_READY.md",
        "root": HERE / "promotion/README.md",
    }
    out["root"].parent.mkdir(exist_ok=True)
    for variant, path in out.items():
        path.write_text(render(variant, a.ref, a.contact, a.affiliation))
        print(f"{variant:6s} → {path.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
