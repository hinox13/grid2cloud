# ruff: noqa: E501
"""Build the three Hugging Face repositories of the frozen Cloud2Grid release (nothing is uploaded).

    .venv/bin/python release/hf/build_hf_repos.py [--namespace hinox13] [--out data/release/hf]

Source of truth: the GitHub Release `cloud2grid-models-v1` (its three archives and SHA256SUMS, kept locally in
data/release/cloud2grid-models-v1/ and byte-identical to the published assets). Every archive is checked against
SHA256SUMS before use. Each repository gets:
- the archive's files, extracted unchanged (their hashes are the ones in checkpoint_manifest.json / MANIFEST.json);
- the original archive under `release/`, so `reproduce/verify_models.py --assets-dir` runs on it unchanged;
- a Hugging Face card (`README.md`): metadata, a short header (what it is, files, load, verify), then the released
  model card or datasheet verbatim;
- `SHA256SUMS` over every file in the repository.
Upload is a separate, explicit step (release/hf/upload_hf_repos.py).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REL = ROOT / "data/release/cloud2grid-models-v1"
GH_RELEASE = "https://github.com/hinox13/grid2cloud/releases/tag/cloud2grid-models-v1"
REPO = "https://github.com/hinox13/grid2cloud"
SITE = "https://hinox13.github.io/grid2cloud/"
REPRO = "https://github.com/hinox13/grid2cloud/blob/cloud2grid-models-v1/reproduce/README.md"
PAPER = "https://arxiv.org/abs/2608.09921"
GENCO = "https://huggingface.co/gridfm/genco-pf-transfer"

REPOS = {
    "cloud2grid-e5c-ft-n10000-s2": {
        "type": "model",
        "archive": "cloud2grid-e5c-ft-n10000-s2.tar.gz",
        "card": "MODEL_CARD.md",
        "title": "Cloud2Grid E5c: ordinary generator-aware adaptation of GENCO (`e5c_ft_n10000_s2`)",
        "summary": (
            "GENCO (`gridfm/genco-pf-transfer`) fine-tuned on 10,000 synthetic AC power-flow states of the reconstructed "
            "Sundon 33 kV network (UK Power Networks), with the local solar and wind represented as explicit generators and "
            "the original GraphKit loss. **It is the baseline for the response-aware E5d model:** it fits the absolute "
            "grid state well on synthetic states, but in the evaluated experiments it responds only weakly to changes in solar "
            "generation (import response 0.014 of the AC reference on held-out synthetic pairs; fitted slope −0.04 MW per MW "
            "against −1.02 on 2,829 reconstructed 2024 states)."
        ),
        "tags": ["power-systems", "power-flow", "graph-neural-network", "gridfm", "genco", "solar", "fine-tuned"],
    },
    "cloud2grid-e5d-l1-s0": {
        "type": "model",
        "archive": "cloud2grid-e5d-l1-s0.tar.gz",
        "card": "MODEL_CARD.md",
        "title": "Cloud2Grid E5d: physics-response-aware adaptation of GENCO (`e5d_l1_s0`)",
        "summary": (
            "GENCO (`gridfm/genco-pf-transfer`) fine-tuned like E5c, plus a **paired-response loss**: pairs of AC-solved "
            "synthetic states that differ in one input (solar, battery or one load) teach the model the AC *change* in grid "
            "import, branch flows and voltages, normalised per MW of perturbation. Total loss L_E5c + λ·κ·L_response, λ = 1, "
            "seed 0. On held-out synthetic pairs it recovers the AC solar response (import slope ratio 0.997, against 0.014 "
            "for E5c and 0.001 for the λ = 0 control); on 2,829 reconstructed 2024 states its fitted solar slope is −1.07 MW "
            "per MW against −1.02 for the AC reference, **but its import carries a near-constant +13.1 MW offset, and only "
            "this seed of three learned the response this well.** A research model, not an operational one."
        ),
        "tags": ["power-systems", "power-flow", "graph-neural-network", "gridfm", "genco", "solar", "physics-informed", "fine-tuned"],
    },
    "cloud2grid-verification-synthetic-v1": {
        "type": "dataset",
        "archive": "cloud2grid-verification-synthetic-v1.tar.gz",
        "card": "DATASHEET.md",
        "title": "Cloud2Grid synthetic verification data v1",
        "summary": (
            "Held-out synthetic AC power-flow states of the reconstructed Sundon 33 kV network, used by "
            "`reproduce/verify_models.py` to re-run the E5c and E5d checkpoints with real GraphKit inference: 2,804 held-out "
            "states and 1,500 AC-solved response pairs (solar, battery and load). Synthetic only: no measured time series and "
            "no satellite data."
        ),
        "tags": ["power-systems", "power-flow", "synthetic", "gridfm", "verification"],
    },
}


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def frontmatter(kind: str, tags: list[str], ns: str) -> str:
    lines = ["---", "license: apache-2.0" if kind == "model" else "license: cc-by-4.0"]
    if kind == "model":
        lines += ["base_model: gridfm/genco-pf-transfer", "library_name: pytorch", "pipeline_tag: graph-ml"]
        lines += [f"datasets:\n- {ns}/cloud2grid-verification-synthetic-v1"]
    else:
        lines += ["pretty_name: Cloud2Grid synthetic verification data v1", "size_categories:\n- 1K<n<10K"]
    lines += ["tags:"] + [f"- {t}" for t in tags] + ["---", ""]
    return "\n".join(lines)


def card(name: str, spec: dict, ns: str, released: str) -> str:
    kind = spec["type"]
    files = {
        "model": "| `best_model_state_dict.pt` | the frozen checkpoint (original `torch.save` state_dict) |\n"
        "| `normalizer_stats.pt` | the exact normaliser fitted with it; use only with this checkpoint |\n"
        "| `graphkit_predict_config.yaml` | GraphKit configuration used for prediction |\n"
        "| `IO_SCHEMA.md` | model architecture, inputs and outputs |\n"
        "| `checkpoint_manifest.json` | file hashes, frozen registry entry, base-model and dependency provenance |\n"
        + ("| `response_sigma.json` | training-time response-loss scale (transparency only; not needed for inference) |\n" if "e5d" in name else "")
        + "| `MODEL_CARD.md` | the released model card (also reproduced below) |\n",
        "dataset": "| `cloud2grid-verification-synthetic-v1/` | the held-out states and response pairs (Parquet) |\n"
        "| `MANIFEST.json` | file hashes and provenance |\n"
        "| `DATASHEET.md` | the released datasheet (also reproduced below) |\n",
    }[kind]
    load = (
        "```python\nimport torch\nfrom huggingface_hub import hf_hub_download\n\n"
        f'repo = "{ns}/{name}"\n'
        'state = torch.load(hf_hub_download(repo, "best_model_state_dict.pt"), map_location="cpu", weights_only=True)\n'
        'norm = torch.load(hf_hub_download(repo, "normalizer_stats.pt"), map_location="cpu", weights_only=True)\n'
        "# build GraphKit's GNS_heterogeneous model with graphkit_predict_config.yaml and load `state` (see IO_SCHEMA.md)\n```\n"
        if kind == "model"
        else "```python\nfrom huggingface_hub import snapshot_download\n\n"
        f'path = snapshot_download("{ns}/{name}", repo_type="dataset")\n```\n'
    )
    verify = (
        "```bash\n"
        f"git clone {REPO} && cd grid2cloud\n"
        "uv sync --extra genco\n"
        f"uv run hf download {ns}/cloud2grid-e5c-ft-n10000-s2 --revision v1 --include \"release/*\" --local-dir hf_assets\n"
        f"uv run hf download {ns}/cloud2grid-e5d-l1-s0 --revision v1 --include \"release/*\" --local-dir hf_assets\n"
        f"uv run hf download {ns}/cloud2grid-verification-synthetic-v1 --type dataset --revision v1 --include \"release/*\" --local-dir hf_assets\n"
        "uv run python reproduce/verify_models.py --assets-dir hf_assets/release   # CPU, about 2-3 minutes\n```\n"
        "\nNo login is needed. Expected: `All checks pass: True`, claims C1-C5 reproduced, 44/44 scored metrics within tolerance "
        "(run anonymously from a fresh clone on 23 Oct 2026).\n"
    )
    return (
        frontmatter(kind, spec["tags"], ns)
        + f"# {spec['title']}\n\n{spec['summary']}\n\n"
        f"Part of **Cloud2Grid** ([website]({SITE}) · [code]({REPO}) · [GitHub Release]({GH_RELEASE}) · [reproduction]({REPRO})), "
        f"a study of adapting the GENCO grid foundation model ([`gridfm/genco-pf-transfer`]({GENCO}); [Puech et al., 2026]({PAPER})) to a real UK distribution network driven by satellite-derived solar.\n\n"
        "## Files\n\n| File | What it is |\n|---|---|\n" + files
        + f"| `release/{spec['archive']}` | the GitHub Release archive, byte-identical (sha256 in `SHA256SUMS`) |\n"
        "| `SHA256SUMS` | checksums of every file in this repository |\n\n"
        "These are the files of the GitHub Release `cloud2grid-models-v1`, unchanged; the release archive's own SHA256 is the published one.\n\n"
        "## Load\n\n" + load + "\n## Verify\n\nRe-run the synthetic claims with real inference from these Hugging Face copies (the verifier checks every archive's SHA256 first):\n\n"
        + verify
        + "\nThe real-state (2024) results need operating data that are not distributed, so they are documented but not independently reproducible from this repository.\n\n"
        "## Licence and attribution\n\n"
        + (
            "Cloud2Grid's fine-tuned weights, configuration and cards: Apache-2.0 (`LICENSE`). Fine-tuned from `gridfm/genco-pf-transfer` (Apache-2.0); "
            "all its weights were modified, the architecture is unchanged. Training data: synthetic states from gridfm-datakit (Apache-2.0) on a network "
            "derived from UK Power Networks open data (CC BY 4.0); attribution in `NOTICE.md`.\n\n"
            if kind == "model"
            else "This dataset: CC BY 4.0 (`LICENSE`). Synthetic states generated with gridfm-datakit (Apache-2.0) on a network model derived from "
            "UK Power Networks open data (CC BY 4.0). When reusing, credit Cloud2Grid and UK Power Networks as set out in `NOTICE.md`.\n\n"
        )
        + "---\n\n## The released "
        + ("model card" if kind == "model" else "datasheet")
        + " (verbatim)\n\n"
        + released
    )


def build(ns: str, out: Path) -> dict:
    sums = {line.split()[1]: line.split()[0] for line in (REL / "SHA256SUMS").read_text().splitlines() if line.strip()}
    report = {}
    for name, spec in REPOS.items():
        arc = REL / spec["archive"]
        assert sha(arc) == sums[spec["archive"]], f"{arc.name}: SHA256 differs from the release"
        d = out / name
        if d.exists():
            shutil.rmtree(d)
        (d / "release").mkdir(parents=True)
        shutil.copy2(arc, d / "release" / arc.name)
        with tarfile.open(arc) as t:
            top = t.getnames()[0].split("/")[0]
            t.extractall(d / "_x", filter="data")
        src = d / "_x" / top
        if spec["type"] == "model":
            for f in src.iterdir():
                shutil.move(str(f), d / f.name)
            manifest = json.loads((d / "checkpoint_manifest.json").read_text())
            for f, h in manifest["files_sha256"].items():
                assert sha(d / f) == h, f"{name}/{f}: hash differs from checkpoint_manifest.json"
        else:
            for f in ("DATASHEET.md", "LICENSE", "NOTICE.md", "MANIFEST.json"):
                shutil.move(str(src / f), d / f)
            shutil.move(str(src), d / top)
        shutil.rmtree(d / "_x")
        (d / "README.md").write_text(card(name, spec, ns, (d / spec["card"]).read_text()))
        files = sorted(p for p in d.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
        (d / "SHA256SUMS").write_text("".join(f"{sha(p)}  {p.relative_to(d)}\n" for p in files))
        report[name] = {"type": spec["type"], "files": len(files) + 1, "bytes": sum(p.stat().st_size for p in files), "archive_sha256": sums[spec["archive"]]}
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--namespace", default="oriolh", help="Hugging Face user (the maintainer's account is oriolh; the GitHub account is hinox13)")
    ap.add_argument("--out", type=Path, default=ROOT / "data/release/hf")
    a = ap.parse_args()
    print(json.dumps(build(a.namespace, a.out), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
