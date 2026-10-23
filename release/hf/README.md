# Hugging Face publication of `cloud2grid-models-v1`

**Published 23 Oct 2026**, under the maintainer's Hugging Face account `oriolh` (the GitHub account is `hinox13`). Every file is unchanged from the GitHub Release.

| Repository | Type | Licence | `v1` revision |
|---|---|---|---|
| [`oriolh/cloud2grid-e5c-ft-n10000-s2`](https://huggingface.co/oriolh/cloud2grid-e5c-ft-n10000-s2) | model | Apache-2.0 | `c7f5910b00241cb5cae78c6866c0dda0aff1f578` |
| [`oriolh/cloud2grid-e5d-l1-s0`](https://huggingface.co/oriolh/cloud2grid-e5d-l1-s0) | model | Apache-2.0 | `a9caa72ac2ead696761691cc31847ed29caba25e` |
| [`oriolh/cloud2grid-verification-synthetic-v1`](https://huggingface.co/datasets/oriolh/cloud2grid-verification-synthetic-v1) | dataset | CC BY 4.0 | `dbe1c1eac06c2e760c15af2e5aa93a0f9534ada5` |

The archive SHA256s are the published release values:

| Archive | SHA256 |
|---|---|
| E5c | `195815e2…ba5f6b` |
| E5d | `8ba6c712…0845b7` |
| verification data | `13b3b4f7…72ffec0` |

**Verified on 23 Oct 2026:**
- **Download check:** each repository, downloaded fresh, matched its `SHA256SUMS`; there are no extra files except Hugging Face's `.gitattributes`.
- **Public access:** anonymous access to the repositories and their pages returns 200.
- **Real inference:** from a fresh GitHub clone with no login, `reproduce/verify_models.py --assets-dir hf_assets/release` on the `v1` archives gave `All checks pass: True`. Claims C1–C5 reproduced and 44/44 scored metrics were within tolerance, on CPU in about 2 minutes.

**Rebuilding or re-uploading:**
- `build_hf_repos.py --namespace oriolh` rebuilds `data/release/hf/` (git-ignored).
- `upload_hf_repos.py --namespace oriolh --yes [--public]` uploads it, but refuses existing repositories unless given `--allow-existing`.
