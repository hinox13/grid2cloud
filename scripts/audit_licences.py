"""E0-L — licence audit of metadata/data_sources.yaml.

    uv run python scripts/audit_licences.py [--check-remote] [--strict]

Prints, for every registered source, its licence status and the gate decision for each
intended use, and writes reports/tables/e0_licence_audit.csv.

--check-remote  re-read the licence declared by the provider where it is machine-readable
                (UKPN Opendatasoft catalogue; Hugging Face card metadata) and flag drift.
--strict        exit non-zero if any source is UNVERIFIED or drifts.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
import requests
import yaml

from cloud2grid.data.ukpn import ODS_LICENCE_TO_ID, UKPNClient
from cloud2grid.licensing import Registry, SourceRecord, Use, check
from cloud2grid.licensing.registry import REPO_ROOT

HF_LICENCE_TO_ID = {"apache-2.0": "Apache-2.0", "cc-by-4.0": "CC-BY-4.0"}


def remote_licence(source: SourceRecord, ukpn: UKPNClient) -> str | None:
    """Licence as currently declared by the provider, or None if not machine-readable."""
    if source.api_dataset_id:
        meta = ukpn.metadata(source.api_dataset_id)
        return ODS_LICENCE_TO_ID.get(meta.licence or "", meta.licence)
    url = source.source_url
    if url.startswith("https://huggingface.co/"):
        path = url.removeprefix("https://huggingface.co/")
        kind = "datasets" if path.startswith("datasets/") else "models"
        repo = path.removeprefix("datasets/")
        if path.startswith("spaces/"):
            return None
        info = requests.get(f"https://huggingface.co/api/{kind}/{repo}", timeout=30).json()
        raw = (info.get("cardData") or {}).get("license")
        return HF_LICENCE_TO_ID.get(raw, raw)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check-remote", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    registry = Registry.load()
    ukpn_cfg = yaml.safe_load((REPO_ROOT / "configs" / "data" / "ukpn.yaml").read_text())
    ukpn = UKPNClient.from_config(ukpn_cfg["portal"])

    rows = []
    for source_id, source in registry.sources.items():
        row = {
            "source_id": source_id,
            "kind": source.kind,
            "licence": source.licence,
            "verified": str(source.licence_verified or "—"),
            **{u.value: "ok" if check(source_id, u, registry).allowed else "x" for u in Use},
        }
        if args.check_remote:
            try:
                remote = remote_licence(source, ukpn)
            except requests.RequestException as exc:
                remote = f"error: {exc.__class__.__name__}"
            row["remote_licence"] = remote or "n/a"
            row["drift"] = (
                bool(remote) and remote != source.licence and source.licence != "UNVERIFIED"
            )
        rows.append(row)

    table = pd.DataFrame(rows)
    out = REPO_ROOT / "reports" / "tables" / "e0_licence_audit.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out, index=False)
    with pd.option_context("display.width", 200, "display.max_columns", None):
        print(table.to_string(index=False))

    unverified = table.loc[table["licence"] == "UNVERIFIED", "source_id"].tolist()
    drifted = table.loc[table.get("drift", pd.Series(False, index=table.index)), "source_id"]
    print(f"\nUNVERIFIED (blocked by gate): {unverified}")
    if args.check_remote:
        print(f"Licence drift vs provider: {drifted.tolist() or 'none'}")
    return 1 if args.strict and (unverified or len(drifted)) else 0


if __name__ == "__main__":
    sys.exit(main())
