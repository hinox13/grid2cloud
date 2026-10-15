# Publishing `cloud2grid-models-v1` (no GitHub CLI needed)

**Nothing here has been run.** Every step needs the maintainer's explicit approval. The existing tag `cloud2grid-submission-v1` (→ `0fee312`) is never moved.

## Prerequisite

The copyright holder named in the build (`--copyright-holder`) is final. It appears in `NOTICE`, the model cards, the datasheet and the release notes.

## Sequence

Paths: `<development-checkout>` is the maintainer's working copy holding the frozen artefacts (`data/interim/`, not public); `<publication-checkout>` is a clone of this repository.

1. **Build the final assets** with the copyright holder (in the development checkout):
   ```bash
   PYTHONPATH=src uv run python release/models-v1/build_release.py --copyright-holder "<Legal name>"
   python3 release/models-v1/check_release.py --strict      # must report READY
   ```
   The build is deterministic. It rewrites `data/release/cloud2grid-models-v1/` and `reproduce/assets.json`.
2. **Re-verify** with the final assets:
   ```bash
   cp data/release/cloud2grid-models-v1/*.tar.gz reproduce/.assets/ && uv run python reproduce/verify_models.py
   ```
3. **Promote** into the publication repository. It writes files only; there is no commit:
   ```bash
   python3 release/models-v1/promote.py --target <publication-checkout>                       # dry run
   python3 release/models-v1/promote.py --target <publication-checkout> --apply --copyright-holder "<Legal name>"
   git -C <publication-checkout> diff --stat && git -C <publication-checkout> status
   ```
4. **Commit** in the publication repository: review the diff first, then
   `git add -A && git commit -m "Add frozen-model release tooling, licences and verification (cloud2grid-models-v1)"`.
5. **Tag and push** (with approval). Push `main` first, then the new tag, which is annotated and points at the new commit:
   ```bash
   git -C <publication-checkout> push origin main
   git -C <publication-checkout> tag -a cloud2grid-models-v1 -m "Cloud2Grid frozen models v1: E5c and E5d baselines"
   git -C <publication-checkout> push origin cloud2grid-models-v1
   ```
6. **Create the release as a DRAFT.** Choose one:
   - **Script (curl, no `gh`):**
     ```bash
     cd <development-checkout>
     DRY_RUN=1 release/models-v1/publish_release.sh                   # preflight only
     GITHUB_TOKEN=<fine-grained PAT> DRY_RUN=0 release/models-v1/publish_release.sh
     ```
   - **Web UI:** open https://github.com/hinox13/grid2cloud/releases/new, then:
     - choose the existing tag `cloud2grid-models-v1`;
     - title: *Cloud2Grid frozen models v1: E5c and E5d baselines*;
     - paste `data/release/cloud2grid-models-v1/RELEASE_NOTES.md` as the description;
     - attach the three `.tar.gz` files and `SHA256SUMS` (the names must not change);
     - tick **Set as a pre-release** off and **Save draft**.
7. **Publish:** review the draft on GitHub, then press **Publish release**.
8. **Verify from the real release** in a fresh clone:
   ```bash
   git clone https://github.com/hinox13/grid2cloud c2g-check && cd c2g-check
   uv sync --extra genco && uv run python reproduce/verify_models.py
   ```
   Expect `All checks pass: True`, with exit code 0.

## Invariants (checked by `check_release.py` and `publish_release.sh`)

- **Names match `reproduce/assets.json` exactly:**
  - tag `cloud2grid-models-v1`;
  - assets `cloud2grid-e5c-ft-n10000-s2.tar.gz`, `cloud2grid-e5d-l1-s0.tar.gz`, `cloud2grid-verification-synthetic-v1.tar.gz`, `SHA256SUMS`;
  - download base URL `https://github.com/hinox13/grid2cloud/releases/download/cloud2grid-models-v1/`.
- **The submission tag stays put:** `cloud2grid-submission-v1` remains at `0fee312`, and no existing release is overwritten.
- **Only the E5c and E5d release files ship:** no E6/E7 checkpoint or development artefact is in any asset or promoted file.
