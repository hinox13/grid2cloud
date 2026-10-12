"""E5d scale-normalised response loss (pure tensor math; graphkit wiring in response_task.py).

For pair p of perturbation type k (pv / battery / load), element j of output family o
(import, branch_P, branch_Q, Vm, Va), x_p = Δ net withdrawal at the perturbed node (MW):

    Δŷ = ŷ(B) − ŷ(A)      Δy = y_AC(B) − y_AC(A)
    σ_{k,o} = sqrt( mean_{training pairs of type k, elements of o} (Δy / x)² )
    r = (Δŷ − Δy) / (|x| · σ_{k,o})
    h_δ(r) = r²/(2δ) if |r| ≤ δ else |r| − δ/2            (δ = 0.1)
    L_response = (1/|K|) Σ_k (1/|O|) Σ_o mean_{p∈k, j∈o} h_δ(r)

All values are in the model's normalised units; σ is in the same units per MW, so r is
dimensionless (a response-blind model has RMS |r| = 1 on the training pairs).
Pre-registered in configs/experiments/e5d_response_training.yaml `response_loss`.
"""

from __future__ import annotations

from collections.abc import Mapping

import torch

FAMILIES = ("import", "branch_P", "branch_Q", "Vm", "Va")
TYPES = ("pv", "battery", "load")


def huber(r: torch.Tensor, delta: float) -> torch.Tensor:
    a = r.abs()
    return torch.where(a <= delta, r * r / (2.0 * delta), a - delta / 2.0)


def deltas(a: Mapping[str, torch.Tensor], b: Mapping[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    """Per family: [n_pairs, n_elements] change from member A to member B."""
    return {o: b[o] - a[o] for o in FAMILIES}


def sigma_accumulate(
    acc: dict[tuple[str, str], list[float]],
    d_ac: Mapping[str, torch.Tensor],
    x: torch.Tensor,
    types: list[str],
) -> None:
    """Add Σ (Δy/x)² and element counts per (type, family) to `acc` (training pairs only)."""
    for k in TYPES:
        sel = torch.tensor([t == k for t in types], device=x.device)
        if not bool(sel.any()):
            continue
        xs = x[sel].abs().unsqueeze(1)
        for o in FAMILIES:
            v = (d_ac[o][sel] / xs).double()
            s = acc.setdefault((k, o), [0.0, 0.0])
            s[0] += float((v * v).sum())
            s[1] += float(v.numel())


def sigma_finalise(acc: Mapping[tuple[str, str], list[float]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {k: {} for k in TYPES}
    for (k, o), (ss, n) in acc.items():
        if n == 0 or ss <= 0:
            raise ValueError(f"σ undefined for ({k}, {o}): no AC response in the training pairs")
        out[k][o] = (ss / n) ** 0.5
    for k in TYPES:
        missing = set(FAMILIES) - set(out[k])
        if missing:
            raise ValueError(f"σ missing for {k}: {sorted(missing)}")
    return out


def residuals(
    d_pred: Mapping[str, torch.Tensor],
    d_ac: Mapping[str, torch.Tensor],
    x: torch.Tensor,
    types: list[str],
    sigma: Mapping[str, Mapping[str, float]],
) -> dict[str, torch.Tensor]:
    """Dimensionless r per family, [n_pairs, n_elements]."""
    s = torch.tensor(
        [[sigma[t][o] for o in FAMILIES] for t in types], dtype=x.dtype, device=x.device
    )
    xs = x.abs().unsqueeze(1)
    return {o: (d_pred[o] - d_ac[o]) / (xs * s[:, i : i + 1]) for i, o in enumerate(FAMILIES)}


def component_sums(
    r: Mapping[str, torch.Tensor], types: list[str], delta: float
) -> dict[tuple[str, str], tuple[torch.Tensor, int]]:
    """Σ h_δ(r) and element count per (type, family)."""
    out = {}
    for k in TYPES:
        sel = torch.tensor([t == k for t in types], device=next(iter(r.values())).device)
        if not bool(sel.any()):
            continue
        for o in FAMILIES:
            h = huber(r[o][sel], delta)
            out[(k, o)] = (h.sum(), h.numel())
    return out


def combine(comp: Mapping[tuple[str, str], tuple[torch.Tensor, int]]) -> torch.Tensor:
    """L_response = mean over types present of mean over families of the per-component means."""
    per_type = []
    for k in TYPES:
        parts = [comp[(k, o)][0] / comp[(k, o)][1] for o in FAMILIES if (k, o) in comp]
        if parts:
            per_type.append(torch.stack(parts).mean())
    return torch.stack(per_type).mean()


def response_loss(
    d_pred: Mapping[str, torch.Tensor],
    d_ac: Mapping[str, torch.Tensor],
    x: torch.Tensor,
    types: list[str],
    sigma: Mapping[str, Mapping[str, float]],
    delta: float = 0.1,
) -> torch.Tensor:
    return combine(component_sums(residuals(d_pred, d_ac, x, types, sigma), types, delta))
