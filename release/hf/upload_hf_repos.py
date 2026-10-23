# ruff: noqa: E501
"""Upload the three prepared repositories (data/release/hf/) to Hugging Face. Run only with the maintainer's approval.

    hf auth login                                                             # once, with a write token
    .venv/bin/python release/hf/upload_hf_repos.py --namespace <user>                     # dry run: lists what would be sent
    .venv/bin/python release/hf/upload_hf_repos.py --namespace <user> --yes               # create PRIVATE repos and upload
    .venv/bin/python release/hf/upload_hf_repos.py --namespace <user> --yes --public      # create PUBLIC repos and upload

Rebuild first with the same namespace (`build_hf_repos.py --namespace <user>`): the cards embed it. Before uploading,
every file is re-checked against the repository's SHA256SUMS. Existing repositories are not overwritten unless
--allow-existing is given.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPOS = {
    "cloud2grid-e5c-ft-n10000-s2": "model",
    "cloud2grid-e5d-l1-s0": "model",
    "cloud2grid-verification-synthetic-v1": "dataset",
}


def check(d: Path, ns: str) -> int:
    lines = (d / "SHA256SUMS").read_text().splitlines()
    for line in lines:
        h, rel = line.split("  ", 1)
        assert hashlib.sha256((d / rel).read_bytes()).hexdigest() == h, f"{d.name}/{rel}: checksum mismatch"
    assert f"{ns}/" in (d / "README.md").read_text(), f"{d.name}: card was built for another namespace; rebuild with --namespace {ns}"
    return len(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--namespace", required=True)
    ap.add_argument("--src", type=Path, default=ROOT / "data/release/hf")
    ap.add_argument("--yes", action="store_true", help="actually create the repositories and upload")
    ap.add_argument("--public", action="store_true", help="create public repositories (default: private)")
    ap.add_argument("--allow-existing", action="store_true")
    a = ap.parse_args()
    for name, kind in REPOS.items():
        n = check(a.src / name, a.namespace)
        print(f"{kind:8s} {a.namespace}/{name}: {n} files verified{'' if a.yes else ' (dry run)'}")
    if not a.yes:
        print("dry run: nothing uploaded")
        return 0
    from huggingface_hub import HfApi

    api = HfApi()
    for name, kind in REPOS.items():
        repo = f"{a.namespace}/{name}"
        if api.repo_exists(repo, repo_type=kind) and not a.allow_existing:
            sys.exit(f"{repo} already exists; pass --allow-existing to upload into it")
        api.create_repo(repo, repo_type=kind, private=not a.public, exist_ok=a.allow_existing)
        api.upload_folder(repo_id=repo, repo_type=kind, folder_path=str(a.src / name), commit_message="Cloud2Grid frozen release cloud2grid-models-v1 (files unchanged from the GitHub Release)")
        print(f"uploaded {repo} ({'public' if a.public else 'private'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
