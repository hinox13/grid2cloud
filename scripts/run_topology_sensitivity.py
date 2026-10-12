"""Run the Sundon baseline and every named variant through identical E2 validation, compare.

    uv run --env-file .env python scripts/run_topology_sensitivity.py

Reads configs/networks/topology_sensitivity.yaml (variant list + pre-declared replacement rule).
Each variant is run with scripts/validate_operational.py on the baseline's 200 timestamps.

Outputs
    reports/tables/e2_topology_sensitivity.csv            one row per variant (V0 primary)
    reports/tables/e2_topology_sensitivity_circuits.csv   per-circuit NMAE / r per variant
    reports/experiments/e2_validation/topology_sensitivity.json
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.network import scenarios as scn

CFG = REPO_ROOT / "configs" / "networks" / "topology_sensitivity.yaml"
TABLES = REPO_ROOT / "reports" / "tables"
E2 = REPO_ROOT / "reports" / "experiments" / "e2_validation"


def run(config: Path) -> None:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "validate_operational.py"),
        "--config",
        str(config),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"{config.name} failed:\n{proc.stderr[-3000:]}")


def collect(config: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    cfg = scn.load_config(config)
    name = cfg["scenario"]["name"]
    is_base = not cfg["scenario"]["changes"]
    summary = json.loads(
        ((E2 if is_base else E2 / "scenarios" / name) / "summary.json").read_text()
    )
    metrics = pd.read_csv(
        TABLES / ("e2_metrics_by_circuit.csv" if is_base else f"e2_metrics_by_circuit_{name}.csv")
    )
    prim = summary["verdict"]["primary_scenario"]
    m = metrics[metrics.scenario == prim]
    core = m[m.core]
    cur = m[m.kind == "current"].iloc[0]
    imp = summary["aggregate"][prim]["import"]
    fit = (core.r >= 0.9) & (core.nmae <= 0.15)
    row = {
        "variant": name,
        "calibration": bool(cfg["scenario"].get("calibration", False)),
        "changes": "; ".join(
            c["type"] + (f":{c.get('series', '')}" if c.get("series") else "")
            for c in cfg["scenario"]["changes"]
        )
        or "none (baseline)",
        "scale_factor": next((v["factor"] for v in summary["measurement_scales"].values()), None),
        "outage_exclusions": len(summary["observed_outages"]),
        "pf_convergence": summary["verdict"]["pf_convergence_rate"],
        "import_nmae": imp["nmae"],
        "import_rmse_mw": imp["rmse"],
        "import_mae_mw": imp["mae"],
        "import_r": imp["r"],
        "core_mae_mw": summary["aggregate"][prim]["core_p_circuits"]["mae"],
        "core_nmae": summary["aggregate"][prim]["core_p_circuits"]["nmae"],
        "core_mean_r": float(core.r.mean()),
        "share_core_r_ge_0.9": float((core.r >= 0.9).mean()),
        "share_core_fit_A": float(fit.mean()),
        "min_core_direction_agreement": float(core.direction_agreement.min()),
        "current_SU33_SU11_2_mae_a": float(cur.mae),
        "current_SU33_SU11_2_r": float(cur.r),
        "verdict": summary["verdict"]["level"],
    }
    return row, m.assign(variant=name)


def evaluate_rule(
    base: dict, var: dict, base_c: pd.DataFrame, var_c: pd.DataFrame, rule: dict, cfg: dict
) -> dict[str, Any]:
    b = base_c[base_c.core].set_index("line")
    v = var_c[var_c.core].set_index("line").reindex(b.index)
    worsening = v.nmae - b.nmae
    improved = int((worsening < -0.005).sum())
    checks = {
        "not_a_calibration_experiment": not var["calibration"],
        "import_nmae_decreases": var["import_nmae"] < base["import_nmae"],
        "share_core_fit_not_decreased": var["share_core_fit_A"] >= base["share_core_fit_A"],
        "no_core_circuit_nmae_worse_than_tolerance": bool(
            (worsening <= rule["max_core_circuit_nmae_worsening"]).all()
        ),
        "direction_agreement_ok": var["min_core_direction_agreement"]
        >= rule["min_direction_agreement_core"],
        "improvement_generalises": improved >= rule["min_core_circuits_improved_nmae"],
    }
    return {
        "variant": var["variant"],
        "eligible_to_replace_baseline": all(checks.values()),
        "checks": checks,
        "core_circuits_improved": improved,
        "max_core_nmae_worsening": float(worsening.max()),
        "worst_circuit": str(worsening.idxmax()),
    }


def main() -> int:
    cfg = yaml.safe_load(CFG.read_text())
    configs = [REPO_ROOT / cfg["baseline"]] + [REPO_ROOT / v for v in cfg["variants"]]
    rows, circuits = [], []
    for c in configs:
        run(c)
        row, m = collect(c)
        rows.append(row)
        circuits.append(m)
        print(
            f"ran {row['variant']}: verdict {row['verdict']}, import NMAE {row['import_nmae']:.3f}"
        )
    table = pd.DataFrame(rows)
    table.to_csv(TABLES / "e2_topology_sensitivity.csv", index=False)
    per_c = pd.concat(circuits)
    wide = per_c.pivot_table(index="line", columns="variant", values=["nmae", "r"])
    wide.columns = [f"{a}|{b}" for a, b in wide.columns]
    wide.to_csv(TABLES / "e2_topology_sensitivity_circuits.csv")
    base = rows[0]
    base_c = circuits[0]
    decisions = [
        evaluate_rule(base, r, base_c, c, cfg["replacement_rule"], cfg)
        for r, c in zip(rows[1:], circuits[1:], strict=True)
    ]
    out = {
        "replacement_rule": cfg["replacement_rule"],
        "not_implemented": cfg["not_implemented"],
        "variants": rows,
        "decisions": decisions,
        "baseline_replaced_by": [
            d["variant"] for d in decisions if d["eligible_to_replace_baseline"]
        ],
    }
    (E2 / "topology_sensitivity.json").write_text(json.dumps(out, indent=2, default=str))
    with pd.option_context("display.width", 250, "display.max_columns", None):
        print(table.round(4).to_string(index=False))
    print(json.dumps(decisions, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
