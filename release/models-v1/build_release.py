# ruff: noqa: E501  (manifest lines kept on one line for auditability)
"""Build the proposed GitHub Release assets `cloud2grid-models-v1` (E5c + E5d frozen models).

    PYTHONPATH=src uv run python release/models-v1/build_release.py

Reads ONLY frozen artifacts and checks each against its registry hash before packaging:
  - E5c selected checkpoint e5c_ft_n10000_s2 and its normaliser (metadata/e5c_checkpoint_registry.yaml)
  - E5d selected checkpoint e5d_l1_s0 and its normaliser + response σ (metadata/e5d_checkpoint_registry.yaml)
  - held-out synthetic verification data: the E5d TEST pair set (3,000 AC-solved states, 1,500
    pairs) and the E5c held-out TEST pool (scenarios 0–2803 of the E5c synthetic pool)
  - the frozen predictions of both models on both sets (secondary cross-check)
Nothing is retrained, re-serialised or modified: weights and normalisers are copied byte-for-byte.

Writes data/release/cloud2grid-models-v1/ (gitignored): three .tar.gz assets, SHA256SUMS,
and reproduce/assets.json (committed; the expected hashes the verifier checks).
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import tarfile
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "data/release/cloud2grid-models-v1"
VERSION = "cloud2grid-models-v1"
NET = "sundon_33kv"
TABLES = ["bus_data", "branch_data", "gen_data", "y_bus_data", "runtime_data"]
PUBLIC_SOURCE = {"repository": "https://github.com/hinox13/grid2cloud", "tag": "cloud2grid-submission-v1", "commit": "0fee312c5976f386dfae9d3b1612da8eef6166d1"}
BASE_MODEL = {"repository": "https://huggingface.co/gridfm/genco-pf-transfer", "file": "pretraining/best_model_state_dict.pt",
              "sha256": "b2c9cf9b1007e24b924c83f440e57d252d500df126c4a4f11fba10c1762f5d41", "revision_at_download": "e7a98e99221ba8241385e491787aedb0940d5130",
              "licence": "Apache-2.0"}  # fmt: skip
MODELS = {
    "e5c_ft_n10000_s2": {"registry": "metadata/e5c_checkpoint_registry.yaml", "dir": "data/interim/e5c/checkpoints/e5c_ft_n10000_s2",
                         "asset": "cloud2grid-e5c-ft-n10000-s2.tar.gz", "extra": [],
                         "frozen_pred": {"e5d_test_pairs": "data/interim/e5d/predictions/e5c_ft_n10000_s2/pairs_test",
                                         "e5c_test": "data/interim/e5c/predictions/e5c_ft_n10000_s2/synthetic_test"}},
    "e5d_l1_s0": {"registry": "metadata/e5d_checkpoint_registry.yaml", "dir": "data/interim/e5d/checkpoints/e5d_l1_s0",
                  "asset": "cloud2grid-e5d-l1-s0.tar.gz", "extra": ["response_sigma.json"],
                  "frozen_pred": {"e5d_test_pairs": "data/interim/e5d/predictions/e5d_l1_s0/pairs_test",
                                  "e5c_test": "data/interim/e5d/predictions/e5d_l1_s0/synthetic_test"}},
}  # fmt: skip
DATA_ASSET = "cloud2grid-verification-synthetic-v1.tar.gz"
PAIRS_SRC = ROOT / "data/interim/e5d/pairs/test"
POOL_SRC = ROOT / "data/interim/e5c/synthetic"
N_E5C_TEST = 2804  # E5c held-out TEST split = scenarios 0..2803 of the pool (verified below)
BUS_COLS = ["scenario", "bus", "PQ", "PV", "REF", "Pd", "Qd", "Vm_pred", "Va_pred", "Pg_pred", "Qg_pred", "Vm_target", "Va_target",
            "Pg_target", "Qg_target", "active res. (MW)", "reactive res. (MVar)", "PBE"]  # fmt: skip
BR_COLS = ["scenario", "from_bus", "to_bus", "Pft", "Qft", "Pft_target", "Qft_target"]
DEPENDENCIES = {"python": "3.11", "gridfm-graphkit": "0.9.0.3 (git f104900245cba26d1380037eea562cf633a97484)", "gridfm-datakit": "1.1.0 (data generation only)",
                "torch": "2.11.0 (cu126 build; CPU inference supported)", "torch-geometric": "2.8.0.post1", "torch-scatter": "2.1.2+pt211cu126",
                "lightning": "2.6.6", "numpy": "2.4.6", "pandas": "2.3.3", "pyarrow": "25.0.1",
                "lockfile": "uv.lock of the public repository (extra `genco`)"}  # fmt: skip


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


PLACEHOLDER = "{{COPYRIGHT_HOLDER}}"
HOLDER: str | None = None  # set by --copyright-holder; None keeps the placeholder (release candidate)


def fill(text: str) -> str:
    return text.replace(PLACEHOLDER, HOLDER) if HOLDER else text


def copy_doc(src: Path, dest: Path) -> None:
    dest.write_text(fill(src.read_text()))


def tar_dir(src: Path, dest: Path) -> None:
    """Deterministic tar.gz (sorted entries, fixed mtime/owner) so the asset hash is reproducible."""
    import gzip

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
        for p in sorted(src.rglob("*")):
            ti = tf.gettarinfo(str(p), arcname=str(p.relative_to(src.parent)))
            ti.mtime, ti.uid, ti.gid, ti.uname, ti.gname = 0, 0, 0, "", ""
            ti.mode = 0o755 if p.is_dir() else 0o644
            if p.is_file():
                with open(p, "rb") as fh:
                    tf.addfile(ti, fh)
            else:
                tf.addfile(ti)
    with open(dest, "wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb", mtime=0, filename="") as gz:
        gz.write(buf.getvalue())


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    pq.write_table(pa.Table.from_pandas(df.reset_index(drop=True), preserve_index=False), path, compression="zstd")


def graphkit_template() -> str:
    """The frozen prediction config (data/interim/e5d/configs/predict_e5d_l1_s0__pairs_test.yaml) with
    the machine-specific split path and scenario count turned into placeholders."""
    c = yaml.safe_load((ROOT / "data/interim/e5d/configs/predict_e5d_l1_s0__pairs_test.yaml").read_text())
    c2 = yaml.safe_load((ROOT / "data/interim/e5d/configs/predict_e5c_ft_n10000_s2__pairs_test.yaml").read_text())
    for k in ("data",):
        c[k].pop("split_from_existing_files"), c2[k].pop("split_from_existing_files")
    assert c == c2, "E5c and E5d prediction configs differ beyond the split path"
    c["data"]["scenarios"] = ["{N_SCENARIOS}"]
    c["data"]["split_from_existing_files"] = "{SPLIT_DIR}"
    return yaml.safe_dump(c, sort_keys=False).replace("'{N_SCENARIOS}'", "{N_SCENARIOS}").replace("'{SPLIT_DIR}'", "{SPLIT_DIR}")


def build_model(run: str, spec: dict, stage: Path) -> dict:
    reg = yaml.safe_load((ROOT / spec["registry"]).read_text())
    assert reg["selected"] == run and reg["frozen"], f"{run} is not the frozen selection"
    entry = reg["checkpoints"][run]
    src = ROOT / spec["dir"]
    pkg = stage / run
    pkg.mkdir(parents=True)
    files = {"best_model_state_dict.pt": entry["checkpoint"]["sha256"], "normalizer_stats.pt": entry["normalizer"]["sha256"]}
    if "response_sigma_sha256" in entry:
        files["response_sigma.json"] = entry["response_sigma_sha256"]
    for f, want in files.items():
        got = sha(src / f)
        assert got == want, f"{run}/{f}: sha256 {got} != registry {want}"
        shutil.copy2(src / f, pkg / f)
        assert sha(pkg / f) == want  # byte-for-byte copy
    (pkg / "graphkit_predict_config.yaml").write_text(graphkit_template())
    copy_doc(HERE / run / "MODEL_CARD.md", pkg / "MODEL_CARD.md")
    for f in ("NOTICE.md", "IO_SCHEMA.md"):
        copy_doc(HERE / f, pkg / f)
    shutil.copy2(HERE / "licenses/Apache-2.0.txt", pkg / "LICENSE")  # canonical text (apache.org)
    keep = {k: entry[k] for k in ("best_epoch", "epochs_run", "normalizer_fitted_on", "training_split_sha256") if k in entry}
    man = {
        "release": VERSION, "run": run, "selected_by": spec["registry"], "selection_flagged": reg["selected_flagged"],
        "checkpoint_sha256": entry["checkpoint"]["sha256"], "normalizer_sha256": entry["normalizer"]["sha256"],
        "normalizer_baseMVA": entry["normalizer"].get("baseMVA"), "training": keep,
        "files_sha256": {p.name: sha(p) for p in sorted(pkg.iterdir())},
        "serialization": "original PyTorch state_dict (torch.save), unchanged; loads with torch.load(weights_only=True)",
        "base_model": BASE_MODEL, "public_source": PUBLIC_SOURCE, "dependencies": DEPENDENCIES,
    }  # fmt: skip
    (pkg / "checkpoint_manifest.json").write_text(json.dumps(man, indent=2))
    return man


def copy_raw(src_root: Path, dest_root: Path, scen_max: int | None) -> None:
    """Copy graphkit raw tables, optionally restricted to scenario < scen_max (no renumbering)."""
    (dest_root / NET / "raw").mkdir(parents=True)
    for t in TABLES:
        df = pd.read_parquet(src_root / NET / "raw" / f"{t}.parquet", filters=[("scenario", "<", scen_max)] if scen_max else None)
        df = df.drop(columns=["scenario_partition"], errors="ignore").sort_values(["scenario"], kind="stable")
        df["scenario_partition"] = df["scenario"] // 1000
        pq.write_to_dataset(pa.Table.from_pandas(df.reset_index(drop=True), preserve_index=False), str(dest_root / NET / "raw" / f"{t}.parquet"),
                            partition_cols=["scenario_partition"], basename_template="part-{i}.parquet")  # fmt: skip  (fixed names: reproducible asset)
    shutil.copy2(next((src_root / NET).glob("*.m")), dest_root / NET / f"{NET}.m")


def build_data(stage: Path) -> dict:
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from cloud2grid.genco import adaptation_e5c as ad5c
    from cloud2grid.genco import adaptation_e5d as ad

    d = stage / "cloud2grid-verification-synthetic-v1"
    # 1. E5d TEST pairs (registered pair manifest hash)
    ad.assert_pair_set(PAIRS_SRC)
    copy_raw(PAIRS_SRC, d / "e5d_test_pairs", None)
    shutil.copy2(PAIRS_SRC / "pairs.parquet", d / "e5d_test_pairs/pairs.parquet")
    reg = yaml.safe_load((ROOT / "metadata/e5d_checkpoint_registry.yaml").read_text())
    # 2. E5c held-out TEST pool = scenarios 0..2803
    man = ad5c.assert_synthetic_dataset(POOL_SRC)
    ids = ad5c.pool_ids(man, "test")
    assert len(ids) == N_E5C_TEST and set(ids.tolist()) == set(range(N_E5C_TEST)), "E5c test ids are not 0..2803"
    copy_raw(POOL_SRC, d / "e5c_test", N_E5C_TEST)
    # 3. frozen predictions (trimmed to the columns the metrics use), with their prediction records
    prov = {}
    for run, spec in MODELS.items():
        for tgt, rel in spec["frozen_pred"].items():
            src = ROOT / rel
            out = d / "frozen_predictions" / run / tgt
            out.mkdir(parents=True)
            write_parquet(pd.read_parquet(src / f"{NET}_predictions.parquet", columns=BUS_COLS), out / "bus.parquet")
            write_parquet(pd.read_parquet(src / f"{NET}_branch_predictions.parquet", columns=BR_COLS), out / "branch.parquet")
            exp = "e5d" if "e5d/predictions" in rel else "e5c"
            rec_name = f"{run}__{'pairs_test' if tgt == 'e5d_test_pairs' else 'synthetic_test'}.json"
            rec = json.loads((ROOT / f"reports/experiments/{exp}/predict" / rec_name).read_text()) if (ROOT / f"reports/experiments/{exp}/predict" / rec_name).exists() else {}
            want = yaml.safe_load((ROOT / spec["registry"]).read_text())["checkpoints"][run]["checkpoint"]["sha256"]
            prov[f"{run}/{tgt}"] = {"weights_sha256_recorded_at_prediction": rec.get("weights_sha256"), "matches_frozen_checkpoint": rec.get("weights_sha256") == want}
            assert rec.get("weights_sha256") == want, f"frozen prediction {run}/{tgt} was not made with the frozen checkpoint"
    copy_doc(HERE / "verification/DATASHEET.md", d / "DATASHEET.md")
    copy_doc(HERE / "NOTICE.md", d / "NOTICE.md")
    shutil.copy2(HERE / "licenses/CC-BY-4.0.txt", d / "LICENSE")  # canonical legal code (creativecommons.org)
    files = {str(p.relative_to(d)): sha(p) for p in sorted(d.rglob("*")) if p.is_file()}
    m = {"release": VERSION, "contents": {
            "e5d_test_pairs": {"states": 3000, "pairs_per_type": 500, "pair_manifest_sha256_registered": reg.get("pair_manifest_sha256")},
            "e5c_test": {"states": N_E5C_TEST, "definition": "E5c held-out TEST split (scenarios 0..2803 of the E5c synthetic pool)"},
            "frozen_predictions": prov},
         "files_sha256": files}  # fmt: skip
    (d / "MANIFEST.json").write_text(json.dumps(m, indent=2))
    return m


def main() -> int:
    import argparse

    global HOLDER
    ap = argparse.ArgumentParser()
    ap.add_argument("--copyright-holder", default=None, help="legal name of the copyright holder (omit: release candidate with placeholder)")
    HOLDER = ap.parse_args().copyright_holder
    if OUT.exists():
        shutil.rmtree(OUT)
    stage = OUT / "_stage"
    stage.mkdir(parents=True)
    mans = {run: build_model(run, spec, stage) for run, spec in MODELS.items()}
    data = build_data(stage)
    assets = {}
    for run, spec in MODELS.items():
        tar_dir(stage / run, OUT / spec["asset"])
        assets[spec["asset"]] = {"kind": "model", "run": run, "checkpoint_sha256": mans[run]["checkpoint_sha256"]}
    tar_dir(stage / "cloud2grid-verification-synthetic-v1", OUT / DATA_ASSET)
    assets[DATA_ASSET] = {"kind": "verification-data"}
    for name, a in assets.items():
        a.update(sha256=sha(OUT / name), bytes=(OUT / name).stat().st_size)
    (OUT / "SHA256SUMS").write_text("".join(f"{a['sha256']}  {n}\n" for n, a in sorted(assets.items())))
    rows = ["| Asset | Contents | Size | SHA256 |", "|---|---|---|---|"]
    what = {"model": "checkpoint (original state_dict) + its own normaliser, GraphKit config, model card, I/O schema, manifest, LICENSE (Apache-2.0), NOTICE",
            "verification-data": "E5d test pairs (3,000 states), E5c test pool (2,804 states), frozen predictions, datasheet, manifest, LICENSE (CC BY 4.0), NOTICE"}  # fmt: skip
    rows += [f"| `{n}` | {what[a['kind']]} | {a['bytes'] / 1e6:.1f} MB | `{a['sha256']}` |" for n, a in sorted(assets.items())]
    rows += ["| `SHA256SUMS` | SHA256 of the three assets | | |"]
    (OUT / "RELEASE_NOTES.md").write_text(fill((HERE / "RELEASE_NOTES.md").read_text()).replace("{{ASSET_TABLE}}", "\n".join(rows)))
    rec = {"release": VERSION, "status": "PROPOSED — not published" if HOLDER else "RELEASE CANDIDATE — copyright holder unresolved; not publishable",
           "copyright_holder": HOLDER,
           "download_base_url": f"https://github.com/hinox13/grid2cloud/releases/download/{VERSION}/", "assets": assets}  # fmt: skip
    (ROOT / "reproduce/assets.json").write_text(json.dumps(rec, indent=2) + "\n")
    shutil.rmtree(stage)
    print(json.dumps({n: {"bytes": a["bytes"], "sha256": a["sha256"][:16]} for n, a in assets.items()}, indent=1))
    print("data files:", len(data["files_sha256"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
