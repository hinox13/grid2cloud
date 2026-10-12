"""E5 topology-only adaptation: isolation rule, fixed pools/subsets, provenance, gate.

GENCO is never reimplemented: training is `gridfm_graphkit finetune|train` (official CLI) on a
dataset under `ALLOWED_ROOT`, with explicit split files written here. This module only enforces
the pre-registered rules of configs/experiments/e5_topology_adaptation.yaml:

- isolation: training/validation/normalizer data may come ONLY from the datakit synthetic pools;
  any path or scenario that touches an E4 weather family raises `LeakageError`;
- deterministic training subsets (nested within a seed) and validation subsets (ceil(N/8));
- provenance hashes of weights / normalizer / split files;
- REF-import diagnostics and the adaptation gate.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
import yaml

from cloud2grid.licensing.registry import REPO_ROOT

CFG = yaml.safe_load((REPO_ROOT / "configs/experiments/e5_topology_adaptation.yaml").read_text())
NETWORK = "sundon_33kv"
WORK = REPO_ROOT / "data/interim/e5"
ALLOWED_ROOT = REPO_ROOT / CFG["isolation"]["allowed_training_root"]
POOLS = ("test", "val", "train")
FORBIDDEN_FAMILIES = (
    "S0_STANDARD_SYNTHETIC",  # E4's S0 states are evaluation-only (independence)
    "S1_WEATHER_ALIGNED",
    "S2_MATCHED_PV_CONTROL",
    "E4D_TIMELINE",
)
WEATHER_COLUMNS = ("slot", "p_hv_injected_mw", "fleet_pv_mw", "fleet_cf", "mean_kc", "donor_slot")
VAL_RNG_SEED = 20261007


class LeakageError(RuntimeError):
    """A non-synthetic (weather / E4) source reached a training, validation or normalizer input."""


def _seed_range(spec: Any) -> list[int]:
    if isinstance(spec, list):
        return [int(s) for s in spec]
    lo, hi = (int(x) for x in str(spec).replace("–", "-").split("-"))
    return list(range(lo, hi + 1))


def pool_seeds(pool: str, extra: int = 0) -> list[int]:
    seeds = _seed_range(CFG["synthetic_data"]["pools"][pool]["datakit_seeds"])
    if pool == "train" and extra:
        seeds += list(range(seeds[-1] + 1, seeds[-1] + 1 + extra))
    return seeds


def all_datakit_seeds() -> set[int]:
    return {s for p in POOLS for s in pool_seeds(p)}


# ---------------------------------------------------------------- isolation
def assert_synthetic_dataset(dataset_root: Path) -> pd.DataFrame:
    """Raise LeakageError unless `dataset_root` is a datakit synthetic pool dataset.

    Checks: location under ALLOWED_ROOT's parent family (synthetic[_merged]), no E4 family name in
    the path, a manifest whose every scenario comes from gridfm-datakit with a pool and a
    pre-registered datakit seed, no E4 S0 seed, and no weather column anywhere in the raw tables.
    """
    root = Path(dataset_root).resolve()
    allowed = {ALLOWED_ROOT.resolve(), (ALLOWED_ROOT.parent / "synthetic_merged").resolve()}
    if root not in allowed:
        raise LeakageError(f"training data must be one of {sorted(map(str, allowed))}, got {root}")
    if any(f in str(root) for f in FORBIDDEN_FAMILIES) or "/e4/" in str(root):
        raise LeakageError(f"E4 family path in training data: {root}")
    man_path = root / "manifest.parquet"
    if not man_path.exists():
        raise LeakageError(f"no synthetic manifest at {man_path}")
    man = pd.read_parquet(man_path)
    if not (man["source"] == "gridfm-datakit").all():
        raise LeakageError("manifest contains non-datakit scenarios")
    if not set(man["pool"]).issubset(POOLS):
        raise LeakageError(f"unknown pools {set(man['pool']) - set(POOLS)}")
    e4_seeds = set(
        yaml.safe_load((REPO_ROOT / "configs/experiments/e4_zero_shot.yaml").read_text())[
            "s0_standard_synthetic"
        ]["seeds"]
    )
    seeds = set(man["datakit_seed"].astype(int))
    if seeds & e4_seeds:
        raise LeakageError(f"E4 S0 datakit seeds in training data: {seeds & e4_seeds}")
    known = all_datakit_seeds() | set(pool_seeds("train", extra=100))
    if not seeds.issubset(known):
        raise LeakageError(f"unregistered datakit seeds: {sorted(seeds - known)[:5]}")
    if man["scenario"].duplicated().any():
        raise LeakageError("duplicate scenario ids in manifest")
    for t in ("bus_data", "branch_data", "gen_data"):
        p = root / NETWORK / "raw" / f"{t}.parquet"
        if p.exists():
            cols = set(pq_columns(p))
            bad = cols & set(WEATHER_COLUMNS)
            if bad:
                raise LeakageError(f"weather columns {bad} in {t}")
    return man


def pq_columns(path: Path) -> list[str]:
    import pyarrow.dataset as ds

    return list(ds.dataset(str(path), partitioning="hive").schema.names)


def assert_split_ids(man: pd.DataFrame, train: list[int], val: list[int], test: list[int]) -> None:
    """Split integrity: disjoint, each id in its declared pool, no load block crossing splits."""
    pool = man.set_index("scenario")["pool"]
    for name, ids, want in (("train", train, "train"), ("val", val, "val"), ("test", test, "test")):
        got = pool.reindex(ids)
        if got.isna().any():
            raise LeakageError(f"{name} split has ids outside the manifest")
        if not (got == want).all():
            raise LeakageError(f"{name} split contains ids from pool(s) {set(got) - {want}}")
    if set(train) & set(val) or set(train) & set(test) or set(val) & set(test):
        raise LeakageError("splits overlap")
    blocks = man.set_index("scenario")["load_block"]
    tb, vb, sb = (set(blocks.reindex(x)) for x in (train, val, test))
    if tb & vb or tb & sb or vb & sb:
        raise LeakageError("a datakit load scenario crosses splits")


# ---------------------------------------------------------------- subsets
def pool_ids(man: pd.DataFrame, pool: str) -> np.ndarray:
    return np.sort(man.loc[man["pool"] == pool, "scenario"].astype(int).to_numpy())


def training_subset(train_ids: np.ndarray, n: int, seed: int) -> list[int]:
    """First n of a seed-specific permutation: nested in n within a seed, different across seeds."""
    if n > len(train_ids):
        raise ValueError(f"requested {n} training states, pool has {len(train_ids)}")
    perm = np.random.default_rng(seed).permutation(np.sort(train_ids))
    return sorted(int(x) for x in perm[:n])


def validation_subset(val_ids: np.ndarray, n_train: int) -> list[int]:
    """First ceil(n/8) of ONE fixed permutation (paper train:val = 8:1), same for every seed."""
    k = math.ceil(n_train / 8)
    if k > len(val_ids):
        raise ValueError(f"requested {k} validation states, pool has {len(val_ids)}")
    perm = np.random.default_rng(VAL_RNG_SEED).permutation(np.sort(val_ids))
    return sorted(int(x) for x in perm[:k])


def write_splits(dest: Path, train: list[int], val: list[int], test: list[int]) -> dict[str, str]:
    dest.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, ids in (("train", train), ("val", val), ("test", test)):
        p = dest / f"{name}.pt"
        torch.save(torch.tensor(ids, dtype=torch.long), p)
        out[name] = sha256_ids(ids)
    return out


def sha256_ids(ids: list[int]) -> str:
    return hashlib.sha256(np.asarray(sorted(ids), dtype=np.int64).tobytes()).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def normalizer_summary(stats_path: Path) -> dict[str, Any]:
    s = torch.load(stats_path, map_location="cpu", weights_only=True)
    net = s.get(NETWORK, s)
    return {
        "path": str(Path(stats_path).relative_to(REPO_ROOT)),
        "sha256": sha256_file(stats_path),
        **{k: float(v) for k, v in net.items()},
    }


def run_name(n: int, seed: int, init: str = "pretrained", rep: str = "SUNDON_ORIGINAL") -> str:
    tag = "ft" if init == "pretrained" else "scratch"
    r = "" if rep == "SUNDON_ORIGINAL" else "_merged"
    return f"{tag}_n{n}_s{seed}{r}"


# ---------------------------------------------------------------- diagnostics and gate
def ref_import(bus: pd.DataFrame) -> pd.DataFrame:
    """Per scenario: AC and GENCO grid import (REF-bus Pg, MW)."""
    r = bus[bus["REF"] == 1][["scenario", "Pg_target", "Pg_pred"]]
    return r.rename(columns={"Pg_target": "ac_import_mw", "Pg_pred": "genco_import_mw"}).set_index(
        "scenario"
    )


def import_diagnostic(imp: pd.DataFrame) -> dict[str, float]:
    a, p = imp["ac_import_mw"].to_numpy(), imp["genco_import_mw"].to_numpy()
    sa = float(np.std(a))
    return {
        "import_sign_accuracy": float(np.mean(np.sign(a) == np.sign(p))),
        "import_mae_mw": float(np.mean(np.abs(p - a))),
        "import_corr": float(np.corrcoef(a, p)[0, 1]) if sa > 0 and np.std(p) > 0 else float("nan"),
        "import_dynamic_range": float(np.std(p) / sa) if sa > 0 else float("nan"),
        "ac_import_mean_mw": float(a.mean()),
        "genco_import_mean_mw": float(p.mean()),
    }


def voltage_tracking(bus: pd.DataFrame) -> float:
    """Median over non-REF buses of the per-bus Pearson r(Vm_pred, Vm_AC) across states."""
    b = bus[bus["REF"] == 0]
    r = []
    for _, g in b.groupby("bus"):
        if g["Vm_target"].std() > 0 and g["Vm_pred"].std() > 0:
            r.append(np.corrcoef(g["Vm_target"], g["Vm_pred"])[0, 1])
    return float(np.median(r)) if r else float("nan")


def gate(row: dict[str, float], zero_shot: dict[str, float]) -> dict[str, Any]:
    """Pre-registered adaptation gate on held-out synthetic test summaries."""
    g = {
        "G1_pbe": row["PBE_mean"] <= 0.10 * zero_shot["PBE_mean"],
        "G2_active": row["P_residual"] <= 0.10 * zero_shot["P_residual"],
        "G3_import_sign": row["import_sign_accuracy"] >= 0.99,
        "G4_vs_dc": row["P_residual"] <= 5.0 * row["dc_P_residual"],
    }
    g["pass"] = all(g.values())
    g["dc_parity"] = bool(row["P_residual"] <= row["dc_P_residual"])
    return g


def explicit_checks(row: dict[str, float]) -> dict[str, bool]:
    return {
        "wrong_import_sign": row["import_sign_accuracy"] < 0.99,
        "near_constant_import": row["import_dynamic_range"] < 0.2,
        "weak_voltage_tracking": row["vm_tracking_median_r"] < 0.9,
    }
