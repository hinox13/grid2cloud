#!/usr/bin/env bash
# Create the GitHub Release `cloud2grid-models-v1` as a DRAFT and upload its assets, without the
# GitHub CLI (curl + the GitHub REST API). The draft stays private until you press "Publish
# release" in the web UI. Nothing here pushes code or tags.
#
#   DRY RUN (default):  release/models-v1/publish_release.sh
#   Create the draft:   GITHUB_TOKEN=... DRY_RUN=0 release/models-v1/publish_release.sh
#
# Requirements: the commit with the promoted files and the tag `cloud2grid-models-v1` are already
# pushed (see PUBLISHING.md); the assets are built in data/release/cloud2grid-models-v1/ with the
# final copyright holder; `release/models-v1/check_release.py --strict` passes.
# Token: a fine-grained personal access token for hinox13/grid2cloud with "Contents: read and write".
set -euo pipefail

OWNER=hinox13
REPO=grid2cloud
TAG=cloud2grid-models-v1
TITLE="Cloud2Grid frozen models v1: E5c and E5d baselines"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIST="$ROOT/data/release/$TAG"
ASSETS=(cloud2grid-e5c-ft-n10000-s2.tar.gz cloud2grid-e5d-l1-s0.tar.gz cloud2grid-verification-synthetic-v1.tar.gz SHA256SUMS)
API="https://api.github.com/repos/$OWNER/$REPO"
DRY_RUN="${DRY_RUN:-1}"

say() { printf '%s\n' "$*"; }

say "== preflight"
python3 "$ROOT/release/models-v1/check_release.py" --strict --stage pre-release
for a in "${ASSETS[@]}"; do [ -f "$DIST/$a" ] || { say "missing asset $DIST/$a"; exit 1; }; done
(cd "$DIST" && sha256sum -c SHA256SUMS)
# the tag must exist on GitHub and carry the same reproduce/assets.json as this checkout
REMOTE_TAG=$(git -C "$ROOT" ls-remote --tags origin "refs/tags/$TAG^{}" | cut -f1)
[ -z "$REMOTE_TAG" ] && REMOTE_TAG=$(git -C "$ROOT" ls-remote --tags origin "refs/tags/$TAG" | cut -f1)
if [ -z "$REMOTE_TAG" ]; then say "tag $TAG is not on GitHub yet: push it first (PUBLISHING.md step 5)"; exit 1; fi
TAGGED=$(curl -sS --fail "https://raw.githubusercontent.com/$OWNER/$REPO/$TAG/reproduce/assets.json") || { say "cannot read reproduce/assets.json at $TAG"; exit 1; }
if [ "$TAGGED" != "$(cat "$ROOT/reproduce/assets.json")" ]; then say "reproduce/assets.json differs from the tagged version: refusing"; exit 1; fi
SUB=$(git -C "$ROOT" ls-remote --tags origin "refs/tags/cloud2grid-submission-v1^{}" | cut -f1)
[ "$SUB" = "0fee312c5976f386dfae9d3b1612da8eef6166d1" ] || { say "submission tag moved or missing on GitHub ($SUB): refusing"; exit 1; }
say "tag $TAG -> ${REMOTE_TAG:0:7}; cloud2grid-submission-v1 unchanged (0fee312)"

if [ "$DRY_RUN" != "0" ]; then
  say "DRY RUN: would create a DRAFT release '$TITLE' for $TAG and upload: ${ASSETS[*]}"
  exit 0
fi
: "${GITHUB_TOKEN:?set GITHUB_TOKEN (fine-grained PAT, Contents: read and write)}"
AUTH=(-H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28")

say "== refuse if a release for $TAG already exists"
CODE=$(curl -sS -o /dev/null -w '%{http_code}' "${AUTH[@]}" "$API/releases/tags/$TAG")
[ "$CODE" = "404" ] || { say "a release for $TAG already exists (HTTP $CODE): refusing to overwrite"; exit 1; }

say "== create draft release"
BODY=$(python3 -c 'import json,sys; print(json.dumps({"tag_name": sys.argv[1], "name": sys.argv[2], "body": open(sys.argv[3]).read(), "draft": True, "prerelease": False}))' "$TAG" "$TITLE" "$DIST/RELEASE_NOTES.md")
RESP=$(curl -sS --fail-with-body "${AUTH[@]}" -X POST "$API/releases" -d "$BODY")
RID=$(printf '%s' "$RESP" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
UPLOAD="https://uploads.github.com/repos/$OWNER/$REPO/releases/$RID/assets"
say "draft release id $RID"

for a in "${ASSETS[@]}"; do
  case "$a" in *.tar.gz) CT=application/gzip ;; *) CT=text/plain ;; esac
  say "== upload $a"
  curl -sS --fail-with-body "${AUTH[@]}" -H "Content-Type: $CT" --data-binary "@$DIST/$a" "$UPLOAD?name=$a" > /dev/null
done

say "== verify uploaded sizes"
curl -sS --fail-with-body "${AUTH[@]}" "$API/releases/$RID/assets" | python3 -c '
import json, os, sys
dist = sys.argv[1]
got = {a["name"]: a["size"] for a in json.load(sys.stdin)}
ok = True
for n in sys.argv[2:]:
    want = os.path.getsize(os.path.join(dist, n))
    print(f"  {n}: uploaded {got.get(n)} bytes, local {want}")
    ok &= got.get(n) == want
sys.exit(0 if ok else 1)' "$DIST" "${ASSETS[@]}"
say "DRAFT created. Review it on GitHub, then press 'Publish release'. After publishing, run the"
say "fresh-clone verification in PUBLISHING.md (step 8) against the real download URL."
