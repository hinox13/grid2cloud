# ruff: noqa: E501  (check lines kept on one line)
"""Release-readiness checks for `cloud2grid-models-v1` (read-only; standard library only).

    python3 release/models-v1/check_release.py            # report
    python3 release/models-v1/check_release.py --strict   # exit 1 unless READY

Checks: tag / asset names / assets.json / SHA256SUMS / release notes agree; every archive holds the
right LICENSE (canonical text), NOTICE, card or datasheet and manifest; checkpoints match the frozen
registries; no E6/E7 artefact; disclosures present; no local paths; copyright holder resolved;
the submission tag is unchanged and no release / tag `cloud2grid-models-v1` exists yet.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TAG = "cloud2grid-models-v1"
URL = f"https://github.com/hinox13/grid2cloud/releases/download/{TAG}/"
ASSETS = {"cloud2grid-e5c-ft-n10000-s2.tar.gz": ("model", "e5c_ft_n10000_s2"), "cloud2grid-e5d-l1-s0.tar.gz": ("model", "e5d_l1_s0"),
          "cloud2grid-verification-synthetic-v1.tar.gz": ("data", "cloud2grid-verification-synthetic-v1")}  # fmt: skip
FROZEN = {"e5c_ft_n10000_s2": ("31b824241880ffc6807f2dad478c34c5c211ee31c7f403092e586c6373ab4d8a", "bb34d0b741d4715e1a4a9c133e291fbe1962237d1eaa4e855d7dc420c35d3f3e"),
          "e5d_l1_s0": ("45ab82525da00844a82a9526bc814de9290efc776159f0d8818703d5e9647435", "9ae23c469edd4fe5cf894e2e02264d801013015fe5dcd170c7d35d18f69f5cec")}  # fmt: skip
SUBMISSION = ("cloud2grid-submission-v1", "0fee312c5976f386dfae9d3b1612da8eef6166d1")
PLACEHOLDER = "{{COPYRIGHT_HOLDER}}"
DISCLOSURES = {  # phrase that must appear -> where
    "generator-encoding": ("e5c card", "e5d card", "README section"),
    "E5D-D": ("e5d card", "release notes", "README section"),
    "synthetic-only": ("e5c card", "e5d card"),
    "not bit-for-bit deterministic": ("e5c card", "e5d card", "release notes", "README section", "reproduce README"),
}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--dist", type=Path, default=ROOT / "data/release" / TAG)
    ap.add_argument("--offline", action="store_true", help="skip the GitHub API / remote checks")
    ap.add_argument("--stage", choices=["pre-tag", "pre-release"], default="pre-tag",
                    help="pre-tag: the tag must not exist yet; pre-release: the tag must exist on GitHub (pushed) and no release yet")
    a = ap.parse_args()
    fails, blockers, ok = [], [], []

    def check(cond: bool, msg: str, blocker: bool = False) -> None:
        (ok if cond else (blockers if blocker else fails)).append(msg)

    spec = json.loads((ROOT / "reproduce/assets.json").read_text())
    check(spec["release"] == TAG, f"assets.json release == {TAG}")
    check(spec["download_base_url"] == URL, "assets.json download URL matches the tag")
    check(set(spec["assets"]) == set(ASSETS), "assets.json lists exactly the three assets")
    sums = dict(reversed(line.split("  ")) for line in (a.dist / "SHA256SUMS").read_text().splitlines())
    check(set(sums) == set(ASSETS), "SHA256SUMS lists exactly the three assets")
    notes = (a.dist / "RELEASE_NOTES.md").read_text()
    licence_sha = {"model": sha((HERE / "licenses/Apache-2.0.txt").read_bytes()), "data": sha((HERE / "licenses/CC-BY-4.0.txt").read_bytes())}
    texts = {"release notes": notes, "reproduce README": (ROOT / "reproduce/README.md").read_text(),
             "README section": (HERE / "promotion/README_section.md").read_text()}  # fmt: skip
    for name, (kind, top) in ASSETS.items():
        blob = (a.dist / name).read_bytes()
        h = sha(blob)
        check(h == spec["assets"][name]["sha256"] == sums[name], f"{name}: file == assets.json == SHA256SUMS")
        check(spec["assets"][name]["bytes"] == len(blob), f"{name}: size matches assets.json")
        check(name in notes and h in notes, f"{name}: name and hash in RELEASE_NOTES.md")
        with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
            members = {m.name: m for m in tf.getmembers() if m.isfile()}
            read = lambda p, tf=tf, members=members, top=top: tf.extractfile(members[f"{top}/{p}"]).read()  # noqa: E731
            need = ["LICENSE", "NOTICE.md"] + (["MODEL_CARD.md", "IO_SCHEMA.md", "checkpoint_manifest.json", "best_model_state_dict.pt", "normalizer_stats.pt", "graphkit_predict_config.yaml"]
                                               if kind == "model" else ["DATASHEET.md", "MANIFEST.json"])  # fmt: skip
            missing = [p for p in need if f"{top}/{p}" not in members]
            check(not missing, f"{name}: contains {', '.join(need)}" + (f" (missing {missing})" if missing else ""))
            if missing:
                continue
            check(sha(read("LICENSE")) == licence_sha[kind], f"{name}: LICENSE is the canonical {'Apache-2.0' if kind == 'model' else 'CC BY 4.0'} text")
            if kind == "model":
                ck, nz = FROZEN[top]
                check(sha(read("best_model_state_dict.pt")) == ck and sha(read("normalizer_stats.pt")) == nz, f"{name}: checkpoint + normaliser == frozen registry")
                texts[f"{top[:3]} card"] = read("MODEL_CARD.md").decode()
            check(not any(re.search(r"(^|/)e[67]_", n) for n in members), f"{name}: no E6/E7 file")
            docs = [p for p in members if p.endswith((".md", ".json", ".yaml"))]
            body = "\n".join(tf.extractfile(members[p]).read().decode(errors="replace") for p in docs)
            check(not re.search(r"/home/|/Users/|_dev/", body), f"{name}: no local paths in text files")
            check(PLACEHOLDER not in body, f"{name}: copyright holder filled in", blocker=True)
    texts["e5c card"], texts["e5d card"] = texts.pop("e5c card"), texts.pop("e5d card")
    for phrase, where in DISCLOSURES.items():
        missing = [w for w in where if phrase.lower() not in texts[w].lower()]
        check(not missing, f"disclosure '{phrase}' in {', '.join(where)}" + (f" (missing in {missing})" if missing else ""))
    check(PLACEHOLDER not in notes and PLACEHOLDER not in (ROOT / "reproduce/assets.json").read_text(), "release notes / assets.json: copyright holder filled in", blocker=True)
    check(spec.get("copyright_holder") not in (None, ""), "assets.json records the copyright holder", blocker=True)
    if not a.offline:
        out = subprocess.run(["git", "ls-remote", "--tags", "https://github.com/hinox13/grid2cloud.git"], capture_output=True, text=True, timeout=60).stdout
        refs = dict(line.split("\t")[::-1] for line in out.splitlines() if "\t" in line)
        check(refs.get(f"refs/tags/{SUBMISSION[0]}^{{}}") == SUBMISSION[1], f"GitHub: {SUBMISSION[0]} still -> {SUBMISSION[1][:7]}")
        if a.stage == "pre-tag":
            check(f"refs/tags/{TAG}" not in refs, f"GitHub: tag {TAG} not created yet")
        else:
            check(f"refs/tags/{TAG}" in refs, f"GitHub: tag {TAG} pushed (-> {refs.get(f'refs/tags/{TAG}^{{}}', refs.get(f'refs/tags/{TAG}', '?'))[:7]})")
        try:
            with urllib.request.urlopen(f"https://api.github.com/repos/hinox13/grid2cloud/releases/tags/{TAG}", timeout=30) as r:
                check(False, f"GitHub: no release for {TAG} yet (HTTP {r.status})")
        except urllib.error.HTTPError as e:
            check(e.code == 404, f"GitHub: no release for {TAG} yet")
    status = "READY" if not fails and not blockers else ("BLOCKED" if not fails else "FAILED")
    for m in ok:
        print(f"  PASS     {m}")
    for m in blockers:
        print(f"  BLOCKER  {m}")
    for m in fails:
        print(f"  FAIL     {m}")
    print(f"\nRelease readiness: {status} ({len(ok)} pass, {len(blockers)} blockers, {len(fails)} failures)")
    return 0 if (status == "READY" or not a.strict) else 1


if __name__ == "__main__":
    sys.exit(main())
