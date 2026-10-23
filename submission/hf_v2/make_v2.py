# ruff: noqa: E501
"""Render the Hugging Face post from the approved submission text (proposal only; nothing is posted).

    python submission/hf_v2/make_v2.py --ref <commit>     # figures pinned to that commit

    → submission/hf_v2/Cloud2Grid_submission_v2.md     (repository version: relative figures, issues contact)
    → submission/hf_v2/Cloud2Grid_submission_v2_HF.md  (paste version: figures pinned to --ref)

--ref must be a commit of hinox13/grid2cloud that contains submission/figures/ as rendered (every figure,
including the website screenshots 05a–05d and the opening crop 05a_website_home_hero.png); "main" works but is
not stable. When a publication checkout sits next to this one (../grid2cloud), every pinned figure is checked
there first. The Hugging Face model and dataset links come from the approved text itself. No contact placeholder
is added: the post carries the same public contact routes as the repository version; the maintainer may add an
address in the Hugging Face editor.

The opening (chosen 23 Oct 2026, "Option A" of submission/hf_v2/options/) leads with the hook, the website and a
three-point summary; the sentences it replaces are kept where the body discusses them: the overview figure in §2,
the zero-shot numbers in §5, the comparison table and the E5c slope in §8.
"""

import argparse
import re
import subprocess
from pathlib import Path

DEV = Path(__file__).resolve().parents[2]
SRC = DEV / "submission/Cloud2Grid_submission_final.md"
OUT = DEV / "submission/hf_v2"
PUB = DEV.parent / "grid2cloud"  # publication checkout, if present
RAW = "https://raw.githubusercontent.com/hinox13/grid2cloud/{ref}/submission/figures/"
SITE = "https://hinox13.github.io/grid2cloud/"  # the official website (React), the only application presented
HERO = "05a_website_home_hero.png"  # top 960 px of 05a_website_home.png (above its divider at y = 1002), pixel-exact

TITLE = ("# Cloud2Grid: from real clouds to electric grid intelligence\n", "# Cloud2Grid: From Clouds to Grid to Value\n")

HEADLINE = "### A grid foundation model met a real electricity network, and predicted power flowing the wrong way."

HOOK = (
    "On a UK distribution network rebuilt from open data, pretrained GENCO had the network exporting power where the AC "
    "reference has it importing, in 99.9 % of the reconstructed 2024 operating states. Synthetic-only adaptation recovered, for the "
    "best training seed, how the grid responds to solar, and exposed a deeper challenge: **a model can learn the right physical "
    "response while still predicting the wrong absolute electrical state.**\n"
)

CTA = (
    f"> **▶ [Open the interactive application]({SITE})**: one real day, 15 June 2024, from Meteosat clouds → satellite-estimated "
    "solar power → the reconstructed grid's response → adapted GENCO → an illustrative value. Two minutes in the browser, nothing "
    "to install."
)

HERO_IMG = (
    "[![The Cloud2Grid website's opening screen: real Meteosat images of 15 June 2024 at 08:45, 10:00, 11:00, 11:30 and 12:15 UTC; "
    "the satellite-estimated output of the local solar fleet (8.945 MW) rising from 2.38 to 8.86 MW between 11:00 and 11:30 UTC; "
    "the Sundon network with AC flows at 11:30 UTC; the title \"One cloud. One grid. A chain of consequences.\" and the buttons "
    f"\"Experience the story\" and \"Follow the model journey\".](figures/{HERO})]({SITE})\n\n"
    "*The Cloud2Grid website (click to open): observed Meteosat imagery, satellite-estimated solar output and the reconstructed "
    "Sundon network on 15 June 2024.*"
)

SUMMARY = (
    "### In 30 seconds\n\n"
    "- **The problem.** Applied zero-shot to Sundon's reconstructed network, the official `genco-pf-transfer` checkpoint showed a "
    "major transfer gap for this unseen topology: besides reversing the import/export direction, it missed the grid import by "
    "about 260 MW on average (§5).\n"
    "- **The contribution.** With the open GridFM toolkits and synthetic training data only, broader coverage of the operating "
    "envelope cut the real-state power-balance error by 99 %. A **physics-response-aware loss**, which we implemented in GraphKit "
    "and trained on pairs of synthetic AC states, then taught GENCO the grid's sensitivity to solar: **−1.07 MW per MW of PV, "
    "against −1.02 in AC**, for the best of three training seeds; the result is seed-dependent (§6–7).\n"
    "- **The discovery.** Accurate absolute states and accurate physical responses were not achieved together. The response-aware "
    "model's import remains **13.1 MW too high** (pre-registered verdict: *partial transfer*), while the envelope-tuned model, "
    "more accurate on most absolute-state metrics, barely responds to solar. A post-hoc diagnostic identifies a mechanism "
    "consistent with this: the import error is almost identical in both states of a pair, so it cancels in the change that the "
    "response loss supervises (§8–9).\n\n"
    "**Why it matters.** For one 6 MW plant over the evaluated April–September 2024 half-hours, the reconstructed grid import it "
    "displaced is worth an illustrative **£234,226** at historical wholesale prices, and the extra import caused by clouds "
    "**£93,286** net: two separate comparisons, never to be added, and illustrations rather than realised savings (§11). "
    "Once validated, a response-aware grid model could link Earth-observation and weather products, such as Destination Earth's "
    "[Extremes Digital Twin](https://destine.ecmwf.int/weather-induced-extremes-digital-twin/) or "
    "[AI4Clouds](https://predictia.es/en/projects/ai4clouds.html), with renewable-generation forecasts and market data, turning "
    "expected weather into power flows, constraints, storage and flexibility needs, and those into value. Cloud2Grid implements "
    "only the grid-response link; the others are independent examples, not part of this study.\n\n"
    "*Only the cloud imagery is observed: the network is rebuilt from UK Power Networks open data, solar output is satellite-derived, "
    "the operating states are AC reconstructions and the AC reference is simulated. A second network reproduced the response result "
    "in two of three seeds, on synthetic states only: its historical-operation reconstruction failed validation (§10).*\n"
)


def edit(t: str, old: str, new: str) -> str:
    assert t.count(old) == 1, old[:70]
    return t.replace(old, new)


def opening(t: str) -> str:
    """Replace everything above §1 with the chosen opening; move what it displaces into the body."""
    head, body = t.split("\n---\n\n## 1. ", 1)
    lines = head.split("\n")
    one = lambda p: next(x for x in lines if x.startswith(p))  # noqa: E731
    bar, overview, overview_cap = one("**🌐 ["), one("![Cloud2Grid overview."), one("*Real clouds → solar power")
    table, table_cap = "\n".join(x for x in lines if x.startswith("|")), one("*Same 2,829 AC-reconstructed")
    head = "\n\n".join([lines[0], HEADLINE, HOOK + "\n" + CTA, HERO_IMG, bar, SUMMARY])
    b = "\n---\n\n## 1. " + body
    # the overview: the satellite-to-grid chain, where the approach is described
    b = edit(b, "\n\n## 3. ", f"\n\n{overview}\n\n{overview_cap}\n\n## 3. ")
    # the zero-shot numbers on the 2024 states
    b = edit(b, "Since the topology gap appears before weather enters, adapting to the network came first.\n",
             "Since the topology gap appears before weather enters, adapting to the network came first.\n\n"
             "The gap is just as clear on the 2,829 observation-informed, AC-reconstructed 2024 operating states. Under our evaluation "
             "conditions, the checkpoint predicts that Sundon exports about 211 MW, where the AC reference imports about 49 MW: an "
             "import bias of −260 MW, with the import/export direction reversed in 99.9 % of states.\n")
    # the comparison table, at the head of the results section, and the E5c slope beside E5d's
    b = edit(b, "## 8. Transfer to the 2024 operating states: what improved and what remains open\n\n",
             f"## 8. Transfer to the 2024 operating states: what improved and what remains open\n\n{table}\n\n{table_cap}\n\n")
    b = edit(b, "that sensitivity transferred to unseen 2024 operating states.",
             "that sensitivity transferred to unseen 2024 operating states, whereas ordinary generator-aware adaptation (E5c) "
             "achieved only −0.04 MW per MW.")
    return head + b


def missing_at(ref: str, names: list[str]) -> list[str] | None:
    """Figures absent from `ref` in the publication checkout; None when there is no checkout to ask."""
    if not (PUB / ".git").exists():
        return None
    return [n for n in names if subprocess.run(["git", "-C", str(PUB), "cat-file", "-e", f"{ref}:submission/figures/{n}"],
                                               capture_output=True).returncode]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", required=True, help="hinox13/grid2cloud commit holding submission/figures/")
    a = ap.parse_args()
    t = opening(edit(SRC.read_text(), *TITLE))
    (OUT / "Cloud2Grid_submission_v2.md").write_text(t)
    print("written", len(t.split()), "words to Cloud2Grid_submission_v2.md")
    names = re.findall(r"\]\(figures/([^)]+)\)", t)
    assert len(names) == len(set(names)) == 10, names
    gone = missing_at(a.ref, names)
    if gone:
        raise SystemExit(f"not at {a.ref} in {PUB}: {', '.join(gone)}; publish them first (Cloud2Grid_submission_v2_HF.md not written)")
    pin = RAW.format(ref=a.ref)
    hf = t.replace("](figures/", "](" + pin)
    assert "](figures/" not in hf and hf.count(pin) == 10
    assert "UPLOAD-" not in hf and "streamlit" not in hf.lower() and "[CONTACT" not in hf
    assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", hf), "an e-mail address in the post"
    (OUT / "Cloud2Grid_submission_v2_HF.md").write_text(hf)
    print("written Cloud2Grid_submission_v2_HF.md; figures pinned to", a.ref, "" if gone is not None else "(not checked: no publication checkout)")


if __name__ == "__main__":
    main()
