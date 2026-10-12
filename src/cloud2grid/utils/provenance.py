"""Lightweight provenance manifest for externally retrieved data (README §42, Workstream J).

One JSON file, keyed by local path (relative to the repo root), recording where each
downloaded file or directory came from, when, under which licence, its size and a SHA-256.
Directories (e.g. partitioned Parquet datasets) get a single tree hash computed over the
sorted (relative path, file hash) pairs.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from cloud2grid.licensing.registry import REPO_ROOT

DEFAULT_MANIFEST = REPO_ROOT / "metadata" / "provenance.json"
_CHUNK = 1 << 20


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def hash_tree(path: Path) -> tuple[str, int, int]:
    """Return (sha256, total_bytes, n_files) for a file or a directory tree.

    Hidden entries (e.g. `.cache/` written by huggingface_hub) are ignored.
    """
    path = Path(path)
    if path.is_file():
        return sha256_file(path), path.stat().st_size, 1
    digest = hashlib.sha256()
    total = n_files = 0
    for file in sorted(p for p in path.rglob("*") if p.is_file()):
        rel = file.relative_to(path)
        if any(part.startswith(".") for part in rel.parts):
            continue
        digest.update(f"{rel.as_posix()}\0{sha256_file(file)}\n".encode())
        total += file.stat().st_size
        n_files += 1
    return digest.hexdigest(), total, n_files


def _relative(path: Path) -> str:
    path = Path(path).resolve()
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def record(
    local_path: Path,
    *,
    source_id: str,
    url: str,
    licence: str,
    revision: str | None = None,
    extra: dict[str, Any] | None = None,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    """Hash `local_path` and upsert its entry in the provenance manifest."""
    sha256, size, n_files = hash_tree(local_path)
    entry: dict[str, Any] = {
        "source_id": source_id,
        "url": url,
        "revision": revision,
        "licence": licence,
        "retrieved_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "local_path": _relative(local_path),
        "size_bytes": size,
        "n_files": n_files,
        "sha256": sha256,
    }
    if extra:
        entry.update(extra)

    manifest = load(manifest_path)
    manifest[entry["local_path"]] = entry
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(dict(sorted(manifest.items())), indent=2) + "\n")
    return entry


def load(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, dict[str, Any]]:
    if not Path(manifest_path).exists():
        return {}
    return json.loads(Path(manifest_path).read_text())
