# ruff: noqa: E501
"""Render the Hugging Face post from the approved submission text (proposal only; nothing is posted).

    python submission/hf_v2/make_v2.py --ref <commit>     # figures pinned to that commit

    → submission/hf_v2/Cloud2Grid_submission_v2.md     (repository version: relative figures, issues contact)
    → submission/hf_v2/Cloud2Grid_submission_v2_HF.md  (paste version: figures pinned to --ref)

--ref must be a commit of hinox13/grid2cloud that contains submission/figures/ as rendered (every figure,
including the website screenshots 05a–05d); "main" works but is not stable. The Hugging Face model and dataset
links come from the approved text itself. No contact placeholder is added: the post carries the same public
contact routes as the repository version; the maintainer may add an address in the Hugging Face editor.
"""

import argparse
import re
from pathlib import Path

DEV = Path(__file__).resolve().parents[2]
SRC = DEV / "submission/Cloud2Grid_submission_final.md"
OUT = DEV / "submission/hf_v2"
RAW = "https://raw.githubusercontent.com/hinox13/grid2cloud/{ref}/submission/figures/"
SITE = "https://hinox13.github.io/grid2cloud/"  # the official website (React), the only application presented

EDITS = [
    # E1: title
    ("# Cloud2Grid: from real clouds to electric grid intelligence\n",
     "# Cloud2Grid: From Clouds to Grid to Value\n"),
    # E2: the interactive walkthrough first
    ("[Reproduce in one command](https://github.com/hinox13/grid2cloud/blob/cloud2grid-models-v1/reproduce/README.md)**\n",
     "[Reproduce in one command](https://github.com/hinox13/grid2cloud/blob/cloud2grid-models-v1/reproduce/README.md)**\n\n"
     f"> **▶ Start here: [From Clouds to Grid to Value]({SITE})**, a guided experience of one real day, "
     "15 June 2024, and a Scientific Explorer. A Meteosat cloud deck clears over the Sundon network; satellite-derived solar output across the area rises by "
     "6.49 MW in 30 minutes; the AC-reconstructed grid imports less power; response-aware GENCO reproduces the import change caused by one 6 MW plant alone; and "
     "historical market prices give it an illustrative value. About two minutes in the browser, nothing to install.\n"),
    # E3: one concise bullet in "In 30 seconds"
    ("so this is not a second real-world transfer.\n",
     "so this is not a second real-world transfer.\n"
     "- **From grid physics to illustrative value.** Combining the satellite-derived PV, the AC-reconstructed states and historical "
     "half-hourly market prices, we estimate the extra grid import caused by clouds at one 6 MW plant: on 15 June 2024, **16.9 MWh** "
     "across 24 evaluated half-hourly intervals, an illustrative **£1,661** at that day's prices. This is not a realised cost, saving "
     "or forecast.\n"),
    # the economic section, its limitation and the Elexon attribution are part of the canonical text since 22 Oct 2026
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", required=True, help="hinox13/grid2cloud commit holding submission/figures/")
    a = ap.parse_args()
    t = SRC.read_text()
    for x, y in EDITS:
        assert t.count(x) == 1, x[:70]
        t = t.replace(x, y)
    (OUT / "Cloud2Grid_submission_v2.md").write_text(t)
    pin = RAW.format(ref=a.ref)
    n_fig = t.count("](figures/")
    hf = t.replace("](figures/", "](" + pin)
    assert "](figures/" not in hf and hf.count(pin) == n_fig == 9, n_fig
    assert "UPLOAD-" not in hf and "streamlit" not in hf.lower() and "[CONTACT" not in hf
    assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", hf), "an e-mail address in the post"
    (OUT / "Cloud2Grid_submission_v2_HF.md").write_text(hf)
    print("written", len(t.split()), "words; figures pinned to", a.ref)


if __name__ == "__main__":
    main()
