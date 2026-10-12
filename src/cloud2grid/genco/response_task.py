"""E5d — graphkit plugin task `PowerFlowResponse`: graphkit PowerFlow task + response loss.

Loaded by the OFFICIAL CLI:
    python -m gridfm_graphkit finetune --plugins cloud2grid.genco.response_task
with `task.task_name: PowerFlowResponse` and a `response:` config section (scripts/train_e5d.py).

    L_total = L_original + λ · κ · L_response          (cloud2grid.genco.response_loss)

- L_original: graphkit's own loss on graphkit's own ordinary batch (unchanged).
- L_response: every training step also draws one STRATIFIED batch of response pairs (8 pv +
  8 battery + 8 load), runs the model on both members (gradients through both), and compares
  ΔGENCO with ΔAC on REF import, branch P/Q (graphkit ComputeBranchFlow on the clamped prediction,
  as in graphkit test/predict), Vm (PQ buses) and Va (non-REF buses).
- σ (per type × family) is computed once at fit start from the TRAINING pairs' AC solutions, in
  the run's normalised units, and written next to the run's normalizer stats.
- "Validation total loss" = graphkit's Validation loss + λκ · L_response over the FULL validation
  pair set: the monitor of best checkpoint, early stopping and LR plateau.

No parameter or buffer is added: the state_dict is identical in structure to PowerFlowTask's, so
checkpoints load into the unchanged `PowerFlow` task for `predict`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import numpy as np
import pandas as pd
import torch
from gridfm_graphkit.datasets.globals import PG_OUT, VA_OUT, VM_OUT
from gridfm_graphkit.datasets.powergrid_hetero_dataset import HeteroGridDatasetDisk
from gridfm_graphkit.datasets.task_transforms import PowerFlowTransforms
from gridfm_graphkit.io.param_handler import get_task_transforms
from gridfm_graphkit.io.registries import (
    PHYSICS_DECODER_REGISTRY,
    TASK_REGISTRY,
    TRANSFORM_REGISTRY,
)
from gridfm_graphkit.models.utils import ComputeBranchFlow, PhysicsDecoderPF
from gridfm_graphkit.tasks.pf_task import (
    PowerFlowTask,
    _build_bus_target,
    _clamp_known_to_ground_truth,
)
from lightning.pytorch.loggers import MLFlowLogger
from torch.utils.data import DataLoader, Dataset, Sampler
from torch_geometric.data import Batch

from cloud2grid.genco import response_loss as rl

TASK_NAME = "PowerFlowResponse"
# same transforms and physics decoder as graphkit's PowerFlow task
if TASK_NAME not in TRANSFORM_REGISTRY:
    TRANSFORM_REGISTRY.register(TASK_NAME)(PowerFlowTransforms)
if TASK_NAME not in PHYSICS_DECODER_REGISTRY:
    PHYSICS_DECODER_REGISTRY.register(TASK_NAME)(PhysicsDecoderPF)


# ------------------------------------------------------------------ pair data
def read_pairs(root: str) -> pd.DataFrame:
    """Complete pairs of an E5d pair set: probe_id, type, class, x_mw, scenario_a/b."""
    man = pd.read_parquet(os.path.join(root, "pairs.parquet"))
    m = man[man.complete]
    a = m[m.member == "A"].set_index("probe_id")
    b = m[m.member == "B"].set_index("probe_id").reindex(a.index)
    return pd.DataFrame(
        {
            "probe_type": a.probe_type,
            "magnitude_class": a.magnitude_class,
            "x_mw": a.x_mw.astype(float),
            "scenario_a": a.scenario.astype(int),
            "scenario_b": b.scenario.astype(int),
        }
    ).reset_index()


class PairDataset(Dataset):
    def __init__(self, ds: HeteroGridDatasetDisk, pairs: pd.DataFrame) -> None:
        self.ds, self.pairs = ds, pairs.reset_index(drop=True)

    def __len__(self) -> int:
        return len(self.pairs)

    def __getitem__(self, i: int) -> tuple[Any, Any, str, float]:
        r = self.pairs.iloc[i]
        return self.ds[int(r.scenario_a)], self.ds[int(r.scenario_b)], r.probe_type, float(r.x_mw)


def collate(items: list[tuple]) -> tuple[Batch, Batch, list[str], torch.Tensor]:
    a, b, t, x = zip(*items, strict=True)
    return Batch.from_data_list(list(a)), Batch.from_data_list(list(b)), list(t), torch.tensor(x)


class StratifiedPairSampler(Sampler):
    """Infinite: each batch = `per_type` pairs of each type, cycling seeded permutations."""

    def __init__(self, pairs: pd.DataFrame, per_type: int, seed: int) -> None:
        self.idx = {k: np.flatnonzero(pairs.probe_type.to_numpy() == k) for k in rl.TYPES}
        self.per_type, self.rng = per_type, np.random.default_rng([seed, 5_550_001])

    def __iter__(self) -> Iterator[list[int]]:
        perm = {k: self.rng.permutation(v) for k, v in self.idx.items()}
        pos = dict.fromkeys(self.idx, 0)
        while True:
            out = []
            for k in rl.TYPES:
                if pos[k] + self.per_type > len(perm[k]):
                    perm[k], pos[k] = self.rng.permutation(self.idx[k]), 0
                out += perm[k][pos[k] : pos[k] + self.per_type].tolist()
                pos[k] += self.per_type
            yield out


# ------------------------------------------------------------------ graph → family values
def family_values(eval_bus: torch.Tensor, target: torch.Tensor, batch: Any) -> tuple[dict, dict]:
    """(prediction, AC) per family as [n_graphs, n_elements] in normalised units."""
    G = batch.num_graphs
    nb = eval_bus.shape[0] // G
    ei = batch.edge_index_dict[("bus", "connects", "bus")]
    ea = batch.edge_attr_dict[("bus", "connects", "bus")]
    ne = ei.shape[1] // G
    if nb * G != eval_bus.shape[0] or ne * G != ei.shape[1]:
        raise ValueError("response pairs must share one topology (equal bus / edge counts)")
    flow = ComputeBranchFlow()
    p_hat, q_hat = flow(eval_bus, ei, ea)
    p_ac, q_ac = flow(target, ei, ea)
    ref = batch.mask_dict["REF"].view(G, nb)
    pq = batch.mask_dict["PQ"].view(G, nb)[0]
    nonref = ~ref[0]
    if not (ref == ref[0]).all() or int(ref[0].sum()) != 1:
        raise ValueError("exactly one REF bus, identical in every graph, is required")

    def fam(bus: torch.Tensor, pf: torch.Tensor, qf: torch.Tensor) -> dict:
        b = bus.view(G, nb, -1)
        return {
            "import": b[:, :, PG_OUT][ref].view(G, 1),
            "branch_P": pf.view(G, ne),
            "branch_Q": qf.view(G, ne),
            "Vm": b[:, pq, VM_OUT],
            "Va": b[:, nonref, VA_OUT],
        }

    return fam(eval_bus, p_hat, q_hat), fam(target, p_ac, q_ac)


@TASK_REGISTRY.register(TASK_NAME)
class PowerFlowResponseTask(PowerFlowTask):
    def __init__(self, args: Any, data_normalizers: list) -> None:
        super().__init__(args, data_normalizers)
        r = args.response
        self.lam = float(r.lam)
        self.kappa = float(r.kappa)
        self.delta = float(r.huber_delta)
        self.per_type = int(r.pairs_per_type)
        self.train_root, self.val_root = str(r.train_pairs), str(r.val_pairs)
        self.pair_workers = int(getattr(r, "workers", 4))
        self.sigma: dict | None = None
        self._train_iter = None
        self._val_sum, self._val_n = 0.0, 0

    # ---------------- setup (normalizer is fitted by the datamodule before on_fit_start)
    def _dataset(self, root: str) -> HeteroGridDatasetDisk:
        return HeteroGridDatasetDisk(
            root=os.path.join(root, self.args.data.networks[0]),
            data_normalizer=self.data_normalizers[0],
            transform=get_task_transforms(args=self.args),
        )

    def _loader(self, root: str, **kw: Any) -> tuple[DataLoader, pd.DataFrame]:
        pairs = read_pairs(root)
        return DataLoader(
            PairDataset(self._dataset(root), pairs),
            collate_fn=collate,
            num_workers=self.pair_workers,
            persistent_workers=self.pair_workers > 0,
            pin_memory=torch.cuda.is_available(),
            **kw,
        ), pairs

    def on_fit_start(self) -> None:
        super().on_fit_start()
        tr, pairs = self._loader(self.train_root, batch_size=256, shuffle=False)
        acc: dict = {}
        with torch.no_grad():
            for ba, bb, types, x in tr:
                fa = self._ac_values(ba)
                fb = self._ac_values(bb)
                rl.sigma_accumulate(acc, rl.deltas(fa, fb), x.double(), types)
        self.sigma = rl.sigma_finalise(acc)
        self._write_artifact(
            "response_sigma.json",
            {
                "sigma": self.sigma,
                "n_train_pairs": {k: int((pairs.probe_type == k).sum()) for k in rl.TYPES},
                "lam": self.lam,
                "kappa": self.kappa,
                "huber_delta": self.delta,
                "pairs_per_type": self.per_type,
                "baseMVA": float(self.data_normalizers[0].baseMVA),
            },
        )
        train_loader, _ = self._loader(
            self.train_root,
            batch_sampler=StratifiedPairSampler(pairs, self.per_type, self.args.seed),
        )
        self._train_iter = iter(train_loader)
        self._val_loader, self._val_pairs = self._loader(
            self.val_root, batch_size=128, shuffle=False
        )

    def _write_artifact(self, name: str, obj: dict) -> None:
        if isinstance(self.logger, MLFlowLogger):
            d = os.path.join(
                self.logger.save_dir,
                self.logger.experiment_id,
                self.logger.run_id,
                "artifacts",
                "stats",
            )
        else:
            d = os.path.join(self.logger.save_dir, "stats")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "w") as fh:
            json.dump(obj, fh, indent=2)

    # ---------------- forward helpers
    @staticmethod
    def _ac_values(batch: Any) -> dict:
        num_bus = batch.x_dict["bus"].size(0)
        target, _, _ = _build_bus_target(batch, num_bus)
        return family_values(target, target, batch)[1]

    def _pair_values(self, batch: Any) -> tuple[dict, dict]:
        out = self.model(batch)
        num_bus = batch.x_dict["bus"].size(0)
        target, g2b, _ = _build_bus_target(batch, num_bus)
        eval_bus = _clamp_known_to_ground_truth(out["bus"], target, batch, g2b, num_bus)
        return family_values(eval_bus, target, batch)

    def _pair_components(
        self, ba: Any, bb: Any, types: list[str], x: torch.Tensor
    ) -> tuple[dict, tuple]:
        pa, aa = self._pair_values(ba)
        pb, ab = self._pair_values(bb)
        r = rl.residuals(rl.deltas(pa, pb), rl.deltas(aa, ab), x, types, self.sigma)
        return rl.component_sums(r, types, self.delta), (pa, pb, aa, ab)

    # ---------------- training
    def training_step(self, batch: Any) -> torch.Tensor:
        _, loss_dict = self.shared_step(batch)
        l_orig = loss_dict["loss"]
        ba, bb, types, x = next(self._train_iter)
        ba, bb, x = ba.to(self.device), bb.to(self.device), x.to(self.device, torch.float32)
        comp, _ = self._pair_components(ba, bb, types, x)
        l_resp = rl.combine(comp)
        loss = l_orig + self.lam * self.kappa * l_resp
        lr = self.optimizer.param_groups[0]["lr"]
        for k, v in {
            "Training Loss": loss.detach(),
            "Training original loss": l_orig.detach(),
            "Training response loss": l_resp.detach(),
            "Learning Rate": lr,
        }.items():
            self.log(k, v, batch_size=batch.num_graphs, on_step=True, on_epoch=False, logger=True)
        return loss

    # ---------------- validation
    def on_validation_epoch_start(self) -> None:
        self._val_sum, self._val_n = 0.0, 0

    def validation_step(self, batch: Any, batch_idx: int) -> torch.Tensor:
        loss = super().validation_step(batch, batch_idx)
        self._val_sum += float(loss) * batch.num_graphs
        self._val_n += batch.num_graphs
        return loss

    @torch.no_grad()
    def response_metrics(self, loader: DataLoader) -> tuple[float, dict]:
        """Exact L_response over a whole pair set + per-type import slope ratios."""
        sums: dict = {}
        num = {k: 0.0 for k in rl.TYPES}
        den = {k: 0.0 for k in rl.TYPES}
        num_ac = {k: 0.0 for k in rl.TYPES}
        for ba, bb, types, x in loader:
            ba, bb, x = ba.to(self.device), bb.to(self.device), x.to(self.device, torch.float32)
            comp, (pa, pb, aa, ab) = self._pair_components(ba, bb, types, x)
            for key, (s, n) in comp.items():
                t = sums.setdefault(key, [0.0, 0])
                t[0] += float(s)
                t[1] += n
            di_hat = (pb["import"] - pa["import"]).squeeze(1)
            di_ac = (ab["import"] - aa["import"]).squeeze(1)
            for j, k in enumerate(types):
                xv = float(x[j])
                num[k] += float(di_hat[j]) * xv
                num_ac[k] += float(di_ac[j]) * xv
                den[k] += xv * xv
        comp = {k: (torch.tensor(v[0]), v[1]) for k, v in sums.items()}
        l_resp = float(rl.combine(comp))
        diag = {f"{k} import slope ratio": num[k] / num_ac[k] for k in rl.TYPES if num_ac[k] != 0}
        for (k, o), (s, n) in comp.items():
            diag[f"{k} {o} h"] = float(s) / n
        return l_resp, diag

    def on_validation_epoch_end(self) -> None:
        if self.sigma is None or self._val_n == 0:  # sanity check before on_fit_start
            return
        l_orig = self._val_sum / self._val_n
        l_resp, diag = self.response_metrics(self._val_loader)
        total = l_orig + self.lam * self.kappa * l_resp
        self.log("Validation total loss", total, on_epoch=True, logger=True, sync_dist=True)
        self.log("Validation response loss", l_resp, on_epoch=True, logger=True, sync_dist=True)
        for k, v in diag.items():
            self.log(f"Validation {k}", v, on_epoch=True, logger=True, sync_dist=True)
