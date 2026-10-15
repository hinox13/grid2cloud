# ruff: noqa: E501  (plan lines kept on one line)
"""Selective promotion of the model release from the maintainer's development checkout to this publication repository.

    python release/models-v1/promote.py --target <publication-checkout>                     # DRY RUN (default): print the plan
    python release/models-v1/promote.py --target <clone> --apply --copyright-holder "Name"  # write the files (no commit, no push)

Safety:
- refuses unless the target is the expected publication commit (EXPECTED_HEAD) with a clean tree;
- writes ONLY the files listed in PLAN; never commits, tags or pushes;
- refuses `--apply` without `--copyright-holder` (use `--allow-placeholder` only on a scratch clone, for testing);
- copies no binary and nothing from E6/E7.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEV = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
EXPECTED_HEAD = "48c4bc5a302be10fc38f2a02c920b3216981bb64"  # publication repo HEAD this plan was prepared against
PLACEHOLDER = "{{COPYRIGHT_HOLDER}}"

COPY = [  # (source in the development checkout, destination in the publication repository) — copied verbatim
    ("reproduce/verify_models.py", "reproduce/verify_models.py"),
    ("reproduce/metrics.py", "reproduce/metrics.py"),
    ("reproduce/README.md", "reproduce/README.md"),
    ("reproduce/assets.json", "reproduce/assets.json"),
    ("release/models-v1/build_release.py", "release/models-v1/build_release.py"),
    ("release/models-v1/promote.py", "release/models-v1/promote.py"),
    ("release/models-v1/check_release.py", "release/models-v1/check_release.py"),
    ("release/models-v1/publish_release.sh", "release/models-v1/publish_release.sh"),
    ("release/models-v1/PUBLISHING.md", "release/models-v1/PUBLISHING.md"),
    ("release/models-v1/RELEASE_NOTES.md", "release/models-v1/RELEASE_NOTES.md"),
    ("release/models-v1/NOTICE.md", "release/models-v1/NOTICE.md"),
    ("release/models-v1/IO_SCHEMA.md", "release/models-v1/IO_SCHEMA.md"),
    ("release/models-v1/e5c_ft_n10000_s2/MODEL_CARD.md", "release/models-v1/e5c_ft_n10000_s2/MODEL_CARD.md"),
    ("release/models-v1/e5d_l1_s0/MODEL_CARD.md", "release/models-v1/e5d_l1_s0/MODEL_CARD.md"),
    ("release/models-v1/verification/DATASHEET.md", "release/models-v1/verification/DATASHEET.md"),
    ("release/models-v1/licenses/Apache-2.0.txt", "release/models-v1/licenses/Apache-2.0.txt"),
    ("release/models-v1/licenses/CC-BY-4.0.txt", "release/models-v1/licenses/CC-BY-4.0.txt"),
    ("release/models-v1/promotion/README_section.md", "release/models-v1/promotion/README_section.md"),
    ("release/models-v1/promotion/NOTICE", "release/models-v1/promotion/NOTICE"),
]
NEW_TOP = [  # generated top-level files
    ("release/models-v1/licenses/Apache-2.0.txt", "LICENSE"),
    ("release/models-v1/promotion/NOTICE", "NOTICE"),  # placeholder filled with the copyright holder
]
README_OLD_LICENSING = "**Licensing.** Third-party data, imagery and checkpoints keep their own licences and attribution requirements: see [`docs/DATA_LICENSES.md`](docs/DATA_LICENSES.md) and [`NOTICE`](NOTICE). No project-level software licence has been selected yet."
README_NEW_LICENSING = "**Licensing.** Cloud2Grid source code: Apache-2.0 ([`LICENSE`](LICENSE)). Released model weights (`cloud2grid-models-v1`): Apache-2.0 for Cloud2Grid's contribution, fine-tuned from the Apache-2.0 GENCO checkpoint. Synthetic verification dataset: CC BY 4.0. Third-party data, imagery and checkpoints keep their own licences and attribution requirements, and the demo bundles, reports and figures are not relicensed: see [`NOTICE`](NOTICE) and [`docs/DATA_LICENSES.md`](docs/DATA_LICENSES.md)."
README_FIXES = [  # outdated status statements (true on 13 Oct 2026), corrected exactly; the dated E6 report is unchanged
    ("No model was trained and no E6 checkpoint exists.", "No model was trained for this diagnostic."),
    ("**Future work (not started): conservation-supervised GENCO.**", "**Follow-up direction: conservation-supervised GENCO.**"),
]
README_ANCHOR = "## Why does GENCO get the response right but the import level wrong? (E6 diagnostic)"
DL_OLD = "6. **The project's own software licence does not cover third-party material.** No project-level software licence has been selected yet (see [`NOTICE`](../NOTICE)). Whatever licence is later chosen applies to Cloud2Grid's own source code only; the datasets, imagery, checkpoints and derived assets listed here stay under their own licences."
DL_NEW = "6. **The project's own licences do not cover third-party material.** Cloud2Grid source code and released model weights are Apache-2.0 and the synthetic verification dataset is CC BY 4.0 (see [`LICENSE`](../LICENSE) and [`NOTICE`](../NOTICE)); these apply to Cloud2Grid's own contribution only. The datasets, imagery, checkpoints and derived assets listed here stay under their own licences."
ENV_OLD = re.compile(r"^# Example on this machine: .*julia\n", re.M)  # machine-specific example line (matched, not spelled out)
ENV_NEW = "# Example: /path/to/julia-1.10.4/bin/julia (tested with Julia 1.10.4)\n"
GITIGNORE_ADD = "\n# --- Model release (cloud2grid-models-v1): large assets live in GitHub Releases, not Git\ndata/release/*\nreproduce/.assets/\nreproduce/.work/\nreproduce/output/\n"


def git(target: Path, *a: str) -> str:
    return subprocess.check_output(["git", "-C", str(target), *a], text=True).strip()


def plan(target: Path) -> list[str]:
    lines = [f"COPY   {d}" for _, d in COPY] + [f"{'REPLACE' if (target / d).exists() else 'CREATE '} {d}" for _, d in NEW_TOP]
    lines += ["EDIT   README.md: replace the 'Licensing.' paragraph; insert the 'Frozen models and independent verification' section before the E6 diagnostic heading",
              "EDIT   README.md: correct two outdated status statements in the E6 diagnostic section (exact replacements)",
              "EDIT   docs/DATA_LICENSES.md: replace point 6 (project licence)",
              "EDIT   .gitignore: append the release / verifier output paths",
              "EDIT   .env.example: replace a machine-specific example path with a generic one"]  # fmt: skip
    return lines


def apply(target: Path, holder: str | None) -> None:
    for s, d in COPY:
        (target / d).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(DEV / s, target / d)
    shutil.copy2(DEV / NEW_TOP[0][0], target / "LICENSE")
    notice = (DEV / NEW_TOP[1][0]).read_text()
    (target / "NOTICE").write_text(notice.replace(PLACEHOLDER, holder) if holder else notice)
    rd = (target / "README.md").read_text()
    assert rd.count(README_OLD_LICENSING) == 1 and rd.count(README_ANCHOR) == 1, "README.md is not the expected version"
    section = (HERE / "promotion/README_section.md").read_text()
    rd = rd.replace(README_OLD_LICENSING, README_NEW_LICENSING).replace(README_ANCHOR, section + "\n" + README_ANCHOR)
    for old, new in README_FIXES:
        assert rd.count(old) == 1, f"README.md: expected exactly one '{old}'"
        rd = rd.replace(old, new)
    (target / "README.md").write_text(rd)
    dl = (target / "docs/DATA_LICENSES.md").read_text()
    assert dl.count(DL_OLD) == 1, "docs/DATA_LICENSES.md is not the expected version"
    (target / "docs/DATA_LICENSES.md").write_text(dl.replace(DL_OLD, DL_NEW))
    env = (target / ".env.example").read_text()
    assert len(ENV_OLD.findall(env)) == 1, ".env.example is not the expected version"
    (target / ".env.example").write_text(ENV_OLD.sub(ENV_NEW, env))
    gi = (target / ".gitignore").read_text()
    if "reproduce/.assets/" not in gi:
        (target / ".gitignore").write_text(gi.rstrip("\n") + "\n" + GITIGNORE_ADD)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=Path, required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--copyright-holder", default=None)
    ap.add_argument("--allow-placeholder", action="store_true", help="testing on a scratch clone only")
    a = ap.parse_args()
    t = a.target.expanduser().resolve()
    head = git(t, "rev-parse", "HEAD")
    if head != EXPECTED_HEAD:
        sys.exit(f"target HEAD {head[:7]} is not the expected publication commit {EXPECTED_HEAD[:7]}: refusing")
    if git(t, "status", "--porcelain"):
        sys.exit("target working tree is not clean: refusing")
    tag = git(t, "rev-parse", "cloud2grid-submission-v1^{commit}")
    print(f"target {t} @ {head[:7]}; submission tag -> {tag[:7]} (never modified by this script)")
    for line in plan(t):
        print(" ", line)
    if not a.apply:
        print("DRY RUN: nothing written. Re-run with --apply --copyright-holder 'Name' after approval.")
        return 0
    if not a.copyright_holder and not a.allow_placeholder:
        sys.exit("--apply needs --copyright-holder (or --allow-placeholder on a scratch clone)")
    apply(t, a.copyright_holder)
    assert git(t, "rev-parse", "cloud2grid-submission-v1^{commit}") == tag
    print("files written; NOT committed. Review with `git -C <target> diff --stat` and `git status`.")
    print("sha256 of written files:")
    for _, d in COPY + NEW_TOP:
        print(f"  {hashlib.sha256((t / d).read_bytes()).hexdigest()[:16]}  {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
