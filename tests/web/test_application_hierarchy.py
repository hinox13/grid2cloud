# ruff: noqa: E501
"""The public hierarchy of Cloud2Grid, wherever it is written: (1) the React website is the official application,
(2) the GitHub repository holds the source and reproducibility material, (3) the Streamlit Explorer is a legacy
alternative, absent from the competition presentation (the written submission and the website). No text may present
Streamlit as the official or production application.

The preview-repository README generator and review gallery (web/deploy) exist in the development repository only;
those checks skip elsewhere.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SITE = "https://hinox13.github.io/grid2cloud/"
STREAMLIT = "https://cloud2grid.streamlit.app/"
DEPLOY = ROOT / "web/deploy"
OBSOLETE = re.compile(
    r"official Cloud2Grid application remains https://cloud2grid\.streamlit\.app"
    r"|Official application: https://cloud2grid\.streamlit\.app"
    r"|Streamlit \(official\)"
    r"|Streamlit, production"
    r"|production Streamlit application"
    r"|\[Scientific Explorer\]\(https://cloud2grid\.streamlit\.app",
    re.I,
)
TEXTS = [p for p in (ROOT / "submission/Cloud2Grid_submission_final.md", ROOT / "submission/hf_v2/Cloud2Grid_submission_v2.md", ROOT / "submission/hf_v2/Cloud2Grid_submission_v2_HF.md") if p.exists()]


@pytest.mark.parametrize("path", TEXTS, ids=lambda p: p.name)
def test_written_submission_leads_with_the_website(path: Path) -> None:
    text = path.read_text()
    assert not OBSOLETE.search(text), OBSOLETE.search(text).group(0)
    links = re.findall(r"\]\((https?://[^)]+)\)", text.split("\n\n![", 1)[0])
    assert links and links[0] == SITE, links[:2]
    # the competition presentation shows one application: the React website; no legacy Streamlit link or screenshot
    assert "streamlit" not in text.lower()
    assert "05_explorer_hero_event.png" not in text and "UPLOAD-" not in text and "[CONTACT" not in text
    assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", text), "no e-mail address in the written submission"
    for repo in ("oriolh/cloud2grid-e5c-ft-n10000-s2", "oriolh/cloud2grid-e5d-l1-s0", "datasets/oriolh/cloud2grid-verification-synthetic-v1"):
        assert f"https://huggingface.co/{repo}" in text, repo
    assert "not components of Cloud2Grid" in text and "none of their data" not in text
    assert "## 12. Explore it yourself\n\n### 👉 [Cloud2Grid: Guided Experience and Scientific Explorer](" + SITE + ")" in text


def test_streamlit_points_to_the_official_website() -> None:
    src = (ROOT / "demo/streamlit_app.py").read_text()
    assert "The official Cloud2Grid application is the website" in src and SITE in src


@pytest.mark.skipif(not (DEPLOY / "stage_preview.py").exists(), reason="preview tooling is development-only")
def test_preview_readmes_and_gallery_state_the_hierarchy(tmp_path: Path) -> None:
    sys.path.insert(0, str(DEPLOY))
    import gallery
    import stage_preview as sp

    sp.readme(tmp_path, "dev test", {})
    for text in (sp.main_readme(), (tmp_path / "README.md").read_text()):
        assert not OBSOLETE.search(text), OBSOLETE.search(text).group(0)
        assert f"**Official Cloud2Grid application:** the React website, {SITE}" in text
        assert f"**Original Streamlit Explorer:** {STREAMLIT}, kept as an optional alternative" in text
        assert text.index(SITE) < text.index(STREAMLIT)
    page = gallery.render("test")
    assert not OBSOLETE.search(page), OBSOLETE.search(page).group(0)
    assert "official Cloud2Grid website" in page
