# ruff: noqa: E501
"""The public hierarchy of Cloud2Grid, wherever it is written: (1) the React website is the official application,
(2) the GitHub repository holds the source and reproducibility material, (3) the Streamlit Explorer is the optional
original. No text may present Streamlit as the official or production application.

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
    assert "The website above is the official Cloud2Grid application." in text
    for line in text.splitlines():
        if STREAMLIT in line and "official" in line.lower():
            assert "website" in line.lower() and "optional" in line.lower(), line[:160]


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
