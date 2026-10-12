"""E0-D — UKPN feasibility audit.

    uv run --env-file .env python scripts/audit_ukpn.py [--refresh | --offline]

1. For every dataset in configs/data/ukpn.yaml: licence gate (download) → live catalogue
   metadata → licence-drift check against metadata/data_sources.yaml.
2. With UKPN_API_KEY set: export missing tables (or, for the multi-million-row half-hourly
   series, a server-side per-circuit aggregate only) to data/raw/ukpn/ + provenance.
   Existing local files are reused unless --refresh.
3. Parse and summarise every table, measure cross-dataset joins on real values, build
   132/33 kV regions (GSP groups and grid-fed 33 kV BSP subtrees), attribute solar assets
   through identifiers only, and rank candidate regions.

No GENCO output and no weather/satellite data are used.

Outputs (regenerated on every run):
    reports/tables/e0_ukpn_sources.csv
    reports/tables/e0_ukpn_missingness_<table>.csv
    reports/tables/e0_ukpn_identifier_overlap.csv      (join measurements)
    reports/tables/e0_ukpn_line_status.csv
    reports/tables/e0_ukpn_nodes.csv
    reports/tables/e0_ukpn_solar_attribution.csv
    reports/tables/e0_ukpn_candidate_regions.csv
    reports/experiments/e0_ukpn_audit/summary.json
    reports/e0_ukpn_audit_generated.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Any

import pandas as pd
import requests
import yaml

from cloud2grid.data.ukpn import ODS_LICENCE_TO_ID, UKPNAccessError, UKPNClient
from cloud2grid.licensing import Registry, Use, check
from cloud2grid.licensing.registry import REPO_ROOT
from cloud2grid.network import study_region as sr
from cloud2grid.network import ukpn_audit as ua
from cloud2grid.network import ukpn_regions as ur
from cloud2grid.network.ukpn_joins import measure_join
from cloud2grid.utils import markdown, provenance

DATA_CONFIG = REPO_ROOT / "configs" / "data" / "ukpn.yaml"
REGION_CONFIG = REPO_ROOT / "configs" / "networks" / "candidate_regions.yaml"
TABLES = REPO_ROOT / "reports" / "tables"
RUN_DIR = REPO_ROOT / "reports" / "experiments" / "e0_ukpn_audit"
GENERATED_MD = REPO_ROOT / "reports" / "e0_ukpn_audit_generated.md"
STUDY_REGION = REPO_ROOT / "configs" / "networks" / "study_region.yaml"
DECISION = REPO_ROOT / "configs" / "networks" / "region_decision.yaml"

REQUIRED_FOR_RANKING = [
    "grid_and_primary_sites",
    "ltds_circuits",
    "ltds_transformers_2w",
    "ecr_1mw_and_above",
    "ecr_under_1mw",
    "op_132kv_monthly",
    "op_33kv_monthly",
]
GEO_COLUMNS = {
    "grid_and_primary_sites": "spatial_coordinates",
    "ecr_1mw_and_above": "spatialcoordinates_customer",
    "ecr_under_1mw": "spatial_coordinates",
}


# ------------------------------------------------------------------------------ acquire


def acquire(cfg: dict[str, Any], registry: Registry, refresh: bool, offline: bool) -> pd.DataFrame:
    client = UKPNClient.from_config(cfg["portal"])
    raw_dir = REPO_ROOT / cfg["raw_dir"]
    rows = []
    for name, ds in cfg["datasets"].items():
        source = registry.sources[ds["source_id"]]
        local = raw_dir / f"{name}.parquet"
        row: dict[str, Any] = {
            "name": name,
            "source_id": ds["source_id"],
            "dataset_id": ds["dataset_id"],
            "mode": ds["mode"],
            "registry_licence": source.licence,
            "local_path": local.relative_to(REPO_ROOT).as_posix(),
        }
        decision = check(ds["source_id"], Use.DOWNLOAD, registry)
        row["gate"] = decision.reason.value
        try:
            meta = client.metadata(ds["dataset_id"])
        except requests.RequestException as exc:
            rows.append({**row, "status": f"metadata_error: {exc.__class__.__name__}"})
            continue
        portal_licence = ODS_LICENCE_TO_ID.get(meta.licence or "", meta.licence)
        row.update(
            portal_licence=portal_licence,
            records_count=meta.records_count,
            modified=meta.modified,
        )

        if not decision.allowed:
            row["status"] = "blocked_by_licence_gate"
        elif ds["mode"] == "region_extract":
            row["status"] = "region_extract_only (scripts/download_region_timeseries.py)"
        elif portal_licence != source.licence:
            row["status"] = "licence_drift (registry != portal) — not downloaded"
        elif local.exists() and not refresh:
            row["status"] = "present_locally"
        elif offline:
            row["status"] = "skipped_offline"
        elif not client.api_key:
            row["status"] = f"blocked_no_api_key ({cfg['portal']['api_key_env']} unset)"
        else:
            try:
                if ds["mode"] == "coverage":
                    q = cfg["coverage_query"]
                    params = {"select": " ".join(q["select"].split()), "group_by": q["group_by"]}
                    n_rows = client.export_aggregate(ds["dataset_id"], params, local)
                    url = client.export_url(ds["dataset_id"], "json")
                else:
                    params = None
                    n_rows = client.export_parquet(
                        ds["dataset_id"], local, None, meta.records_count
                    )
                    url = client.export_url(ds["dataset_id"])
                provenance.record(
                    local,
                    source_id=ds["source_id"],
                    url=url,
                    licence=source.licence,
                    revision=meta.modified,
                    extra={"export_params": params, "n_rows": n_rows},
                )
                row["status"] = "downloaded"
            except (UKPNAccessError, RuntimeError, requests.RequestException) as exc:
                row["status"] = f"access_error: {exc}"
        row["rows_local"] = len(pd.read_parquet(local)) if local.exists() else None
        rows.append(row)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------- joins


def _key(*parts: object) -> str | None:
    return (
        None
        if any(p is None or (isinstance(p, float) and pd.isna(p)) for p in parts)
        else ("|".join(map(str, parts)))
    )


def _area_name_keys(area: pd.Series, names: pd.Series) -> pd.Series:
    return pd.Series(
        [
            _key(ua.licence_area_code(a), ua.normalise_name(n))
            for a, n in zip(area, names, strict=True)
        ]
    )


def _bsp_key(value: object) -> str | None:
    key = ua.normalise_name(value)
    return None if key == "DIRECT" else key


def measure_joins(
    t: dict[str, pd.DataFrame],
    monthly: pd.DataFrame,
    ecr: pd.DataFrame,
    study_circuits: pd.DataFrame,
) -> pd.DataFrame:
    c, t2, sites = t["ltds_circuits"], t["ltds_transformers_2w"], t["grid_and_primary_sites"]
    c_area = c["licencearea"].map(ua.licence_area_code)
    m_area = monthly["licence_area"].map(ua.licence_area_code)
    site_area = sites["sitefunctionallocation"].str[:3]

    t1_line = pd.Series([_key(a, n) for a, n in zip(c_area, c["linename"], strict=True)])
    m_lines = (
        pd.Series([_key(a, n) for a, n in zip(m_area, monthly["ltds_line_name"], strict=True)])
        .dropna()
        .drop_duplicates()
    )

    def pair(a: object, f: object, to: object) -> str | None:
        fk, tk = ua.node_key(a, f), ua.node_key(a, to)
        return None if fk is None or tk is None else "|".join(sorted((fk, tk)))

    t1_pair = pd.Series(
        [
            pair(a, f, to)
            for a, f, to in zip(c["licencearea"], c["fromnode"], c["tonode"], strict=True)
        ]
    )
    m_pair = pd.Series(
        [
            pair(a, f, to)
            for a, f, to in zip(
                monthly["licence_area"],
                monthly["from_ltds_node"],
                monthly["to_ltds_node"],
                strict=True,
            )
        ]
    )
    m_line_pair = (
        pd.Series(
            [
                _key(lk, p)
                for lk, p in zip(
                    [_key(a, n) for a, n in zip(m_area, monthly["ltds_line_name"], strict=True)],
                    m_pair,
                    strict=True,
                )
            ]
        )
        .dropna()
        .drop_duplicates()
    )
    t1_line_pair = pd.Series([_key(lk, p) for lk, p in zip(t1_line, t1_pair, strict=True)])

    study_line = pd.Series(
        [
            _key(a, n)
            for a, n in zip(study_circuits["area"], study_circuits["line_name"], strict=True)
            if a in ("EPN", "SPN")
        ]
    )

    t1_from_floc = c["fromsubstation_sitefunctionallocation"].where(
        c["fromsubstation_sitefunctionallocation"] != "CUSTOMER_SITE"
    )
    endpoints_area = pd.concat([c_area, c_area], ignore_index=True)
    endpoint_names = pd.concat([c["fromsubstation"], c["tosubstation"]], ignore_index=True)
    site_name_keys = _area_name_keys(site_area, sites["sitename"])
    m_site_floc = pd.Series(
        [
            ua.floc_from_code(a, ua.site_code_from_label(lbl))
            for a, lbl in zip(monthly["licence_area"], monthly["grid_supply_point"], strict=True)
        ]
    )
    ltds_names = pd.concat(
        [
            _area_name_keys(c["licencearea"], c["fromsubstation"]),
            _area_name_keys(c["licencearea"], c["tosubstation"]),
            _area_name_keys(t2["licencearea"], t2["hv_substation"]),
            _area_name_keys(t2["licencearea"], t2["lv_substation"]),
        ],
        ignore_index=True,
    )
    t2_lv_names = _area_name_keys(t2["licencearea"], t2["lv_substation"])
    ecr_floc = ecr["sitefunctionallocation"].where(
        ecr["sitefunctionallocation"].map(ua.normalise_name).notna()
    )
    ecr_bsp = pd.Series(
        [
            _key(ua.licence_area_code(a), _bsp_key(b))
            for a, b in zip(ecr["licence_area"], ecr["bulk_supply_point"], strict=True)
        ]
    )
    ltds_sites_floc = pd.concat(
        [t1_from_floc, t2["sitefunctionallocation"]], ignore_index=True
    ).dropna()

    joins = [
        measure_join(
            "monthly line name -> LTDS T1 linename (area-scoped)",
            m_lines,
            t1_line,
            right_entity=c["id"],
            note="distinct (area, ltds_line_name) in the 132+33 kV monthly index",
        ),
        measure_join(
            "LTDS T1 132/33 kV circuit (EPN/SPN) -> monthly line name",
            study_line,
            m_lines,
            note="how much of the LTDS study network is in the operational "
            "index (LPN has no operational data)",
        ),
        measure_join(
            "monthly from/to node pair -> LTDS T1 fromnode/tonode pair (area-scoped, unordered)",
            m_pair.dropna().drop_duplicates(),
            t1_pair,
            right_entity=c["id"],
            note="independent of line names",
        ),
        measure_join(
            "monthly (line name + node pair) -> LTDS T1 (linename + node pair)",
            m_line_pair,
            t1_line_pair,
            right_entity=c["id"],
            note="name and nodes agree simultaneously",
        ),
        measure_join(
            "LTDS T1 fromsubstation_sitefunctionallocation -> site FLOC",
            t1_from_floc,
            sites["sitefunctionallocation"],
            note="'CUSTOMER_SITE' values counted as no key; T1 has no to-side FLOC",
        ),
        measure_join(
            "LTDS T2a sitefunctionallocation -> site FLOC",
            t2["sitefunctionallocation"],
            sites["sitefunctionallocation"],
        ),
        measure_join(
            "LTDS T1 from/to substation name -> sitename (area-scoped, exact normalised)",
            _area_name_keys(endpoints_area, endpoint_names),
            site_name_keys,
            right_entity=sites["sitefunctionallocation"],
            note="one row per circuit endpoint",
        ),
        measure_join(
            "monthly 'grid_supply_point' site code -> site FLOC",
            m_site_floc.drop_duplicates(),
            sites["sitefunctionallocation"],
            note="code in parentheses, e.g. 'SALL GRID (0D5023)' -> EPN-S0000000D5023",
        ),
        measure_join(
            "monthly 'grid_supply_point' label -> LTDS gridsupplypoint (normalised)",
            monthly["grid_supply_point"].map(ua.normalise_name).drop_duplicates(),
            c["gridsupplypoint"].map(ua.normalise_name),
            note="shows the monthly field is a metering site, not an LTDS GSP",
        ),
        measure_join(
            "ECR sitefunctionallocation -> site FLOC",
            ecr_floc,
            sites["sitefunctionallocation"],
            note="both registers, all technologies",
        ),
        measure_join(
            "ECR sitefunctionallocation -> LTDS T1/T2a site FLOC",
            ecr_floc,
            ltds_sites_floc,
            note="sites with LTDS electrical nodes",
        ),
        measure_join(
            "ECR grid_supply_point -> LTDS gridsupplypoint (exact normalised)",
            ecr["grid_supply_point"].map(ua.normalise_name),
            c["gridsupplypoint"].map(ua.normalise_name),
        ),
        measure_join(
            "ECR bulk_supply_point -> LTDS T1/T2a substation name (area-scoped)",
            ecr_bsp,
            ltds_names,
            note="'Direct' and '-' counted as no key",
        ),
        measure_join(
            "ECR bulk_supply_point -> sitename (area-scoped)",
            ecr_bsp,
            site_name_keys,
            right_entity=sites["sitefunctionallocation"],
        ),
        measure_join(
            "ECR primary -> LTDS T2a lv_substation (area-scoped)",
            _area_name_keys(ecr["licence_area"], ecr["primary"]),
            t2_lv_names,
            right_entity=t2["sitefunctionallocation"],
            note="entity = transformer site FLOC (a primary has several transformers)",
        ),
        measure_join(
            "ECR primary -> sitename (area-scoped)",
            _area_name_keys(ecr["licence_area"], ecr["primary"]),
            site_name_keys,
            right_entity=sites["sitefunctionallocation"],
        ),
    ]
    return pd.DataFrame(joins)


# ------------------------------------------------------------------------------ analyse


def analyse(cfg: dict[str, Any], region_cfg: dict[str, Any]) -> dict[str, Any]:
    raw_dir = REPO_ROOT / cfg["raw_dir"]
    t = {
        name: pd.read_parquet(raw_dir / f"{name}.parquet")
        for name in cfg["datasets"]
        if (raw_dir / f"{name}.parquet").exists()
    }
    missing = [n for n in REQUIRED_FOR_RANKING if n not in t]
    summary: dict[str, Any] = {"tables_loaded": sorted(t), "missing_for_ranking": missing}
    summary["records"] = {name: len(df) for name, df in t.items()}
    for name, df in t.items():
        ua.missingness(df).to_csv(TABLES / f"e0_ukpn_missingness_{name}.csv", index=False)
    if missing:
        return summary, {}

    # ---- parser counters / real encodings
    counters: dict[str, Any] = {}
    for name, column in GEO_COLUMNS.items():
        df = ua.add_lat_lon(t[name], column)
        t[name] = df
        raw = t[name][column]
        counters[f"{name}.{column}"] = {
            "null": int(raw.isna().sum()),
            "parsed": int(df["lat"].notna().sum()),
            "unparsed_non_null": int((raw.notna() & df["lat"].isna()).sum()),
        }
    for name in ("ecr_1mw_and_above", "ecr_under_1mw"):
        df = t[name]
        counters[f"{name}.lat_lon_columns_vs_geo"] = {
            "max_abs_diff_deg": float((df["latitude"] - df["lat"]).abs().max(skipna=True) or 0.0),
        }
        counters[f"{name}.identifier_placeholders"] = {
            col: {
                "null": int(df[col].isna().sum()),
                "placeholder": int(df[col].map(ua.is_placeholder).sum()),
                "direct": int(df[col].map(ua.normalise_name).eq("DIRECT").sum()),
            }
            for col in (
                "grid_supply_point",
                "bulk_supply_point",
                "primary",
                "sitefunctionallocation",
            )
        }
    c = t["ltds_circuits"]
    counters["ltds_circuits.operating_voltage"] = {
        "values": c["operating_voltage"].value_counts().to_dict(),
        "unparsed": int(c["operating_voltage"].map(ua.parse_voltage_kv).isna().sum()),
    }
    counters["ltds_circuits.fromsubstation_sitefunctionallocation"] = {
        "CUSTOMER_SITE": int((c["fromsubstation_sitefunctionallocation"] == "CUSTOMER_SITE").sum()),
        "null": int(c["fromsubstation_sitefunctionallocation"].isna().sum()),
    }
    counters["ltds_circuits.duplicate_linename_rows_area_scoped"] = int(
        c.assign(a=c["licencearea"].map(ua.licence_area_code))
        .duplicated(["a", "linename"], keep=False)
        .sum()
    )
    monthly = pd.concat([t["op_132kv_monthly"], t["op_33kv_monthly"]], ignore_index=True)
    counters["monthly"] = ua.publication_counters(monthly)
    counters["monthly.redacted_values"] = monthly["redacted"].astype(str).value_counts().to_dict()
    counters["monthly.nominal_voltage_values"] = {
        str(k): int(v) for k, v in monthly["nominal_voltage"].value_counts().items()
    }
    counters["monthly.licence_area_values"] = monthly["licence_area"].value_counts().to_dict()
    labels = monthly["grid_supply_point"].drop_duplicates()
    counters["monthly.grid_supply_point_labels"] = {
        "distinct": len(labels),
        "with_site_code": int(labels.map(ua.site_code_from_label).notna().sum()),
    }
    months = pd.to_datetime(monthly["timestamp"], utc=True).dt.strftime("%Y-%m")
    all_months = pd.period_range(months.min(), months.max(), freq="M").strftime("%Y-%m")
    summary["monthly_time_coverage"] = {
        "first": months.min(),
        "last": months.max(),
        "distinct_months": int(months.nunique()),
        "missing_months": sorted(set(all_months) - set(months)),
    }
    summary["parser_counters"] = counters

    # ---- network, geography, measurement
    min_public = region_cfg["measurement"]["min_public_fraction"]
    rcfg = ur.RankingConfig(
        min_nodes=region_cfg["size"]["min_nodes"],
        max_nodes=region_cfg["size"]["max_nodes"],
        out_of_band_penalty=region_cfg["size"]["out_of_band_penalty"],
        solar_mw_target=region_cfg["solar"]["solar_mw_target"],
        min_public_fraction=min_public,
        min_hh_completeness=region_cfg["measurement"]["min_half_hourly_completeness"],
        weights=region_cfg["weights"],
    )
    t3 = t.get("ltds_transformers_3w")
    branches, branch_counters = ur.build_branches(c, t["ltds_transformers_2w"], t3)
    summary["network"] = {
        **branch_counters,
        "study_branches": len(branches),
        "study_circuits_132kv": int(
            ((branches.kind == "circuit") & (branches.from_kv == 132)).sum()
        ),
        "study_circuits_33kv": int(((branches.kind == "circuit") & (branches.from_kv == 33)).sum()),
        "grid_transformers_132_33": int((branches.kind == "transformer").sum()),
    }
    floc_index = ur.substation_floc_index(
        c, t["ltds_transformers_2w"], t3, t["grid_and_primary_sites"]
    )
    nodes = ur.node_table(branches, floc_index, t["grid_and_primary_sites"])
    nodes.to_csv(TABLES / "e0_ukpn_nodes.csv")
    summary["nodes"] = {
        "n_nodes": len(nodes),
        "coord_status": nodes["coord_status"].value_counts().to_dict(),
        "nodes_with_multiple_specific_names": int((nodes["n_specific_names"] > 1).sum()),
        "nodes_with_no_specific_name": int((nodes["n_specific_names"] == 0).sum()),
    }

    publication = ua.circuit_publication_status(monthly, min_public)
    coverages = []
    for name, ds in cfg["datasets"].items():
        if ds["mode"] == "coverage" and name in t:
            cov = ds["covers"]
            coverages.append(
                ur.HalfHourlyCoverage(name, frozenset(cov["areas"]), float(cov["kv"]), t[name])
            )
            summary.setdefault("half_hourly_coverage", {})[name] = {
                "lines": int(t[name]["ltds_line_name"].notna().sum()),
                "rows_null_line_name": int(
                    t[name].loc[t[name]["ltds_line_name"].isna(), "n_rows"].sum()
                ),
                "first": str(t[name]["first_timestamp"].min()),
                "last": str(t[name]["last_timestamp"].max()),
                "lines_with_zero_active_power": int(
                    ((t[name]["n_active_power"] == 0) & t[name]["ltds_line_name"].notna()).sum()
                ),
            }
    line_status = ur.build_line_status(branches, c, publication, coverages, rcfg)
    line_status.to_csv(TABLES / "e0_ukpn_line_status.csv", index=False)
    summary["line_status"] = {
        "study_lines": len(line_status),
        "in_monthly_index": int(line_status["in_monthly_index"].sum()),
        "usable_monthly": int(line_status["usable_monthly"].fillna(False).sum()),
        "hh_status": line_status["hh_status"].value_counts().to_dict(),
        "usable": int(line_status["usable"].sum()),
        "usable_active_power": int(line_status["usable_active_power"].sum()),
        "usable_monthly_only": int(line_status["usable_monthly_only"].sum()),
        "node_pair_consistent": int(line_status["node_pair_consistent"].sum()),
    }

    # ---- joins
    ecr = pd.concat(
        [
            t["ecr_1mw_and_above"].assign(register=">=1MW"),
            t["ecr_under_1mw"].assign(register="<1MW"),
        ],
        ignore_index=True,
    )
    joins = measure_joins(t, monthly, ecr, branches[branches["kind"] == "circuit"])
    joins.to_csv(TABLES / "e0_ukpn_identifier_overlap.csv", index=False)
    summary["joins"] = joins.drop(columns=["unmatched_examples", "note"]).to_dict(orient="records")

    # ---- solar attribution (identifiers only)
    solar = ua.solar_assets(ecr)
    summary["solar"] = ua.solar_counters(ecr, solar)
    network_nodes = set(nodes.index)
    floc_nodes, primary_nodes, bsp_nodes = ur.site_node_index(
        c, t["ltds_transformers_2w"], network_nodes
    )
    attr = ur.attribute_solar(solar, nodes["kv"].to_dict(), floc_nodes, primary_nodes, bsp_nodes)
    conn = attr[attr["connected"]]
    summary["solar_attribution_connected"] = {
        "assets": len(conn),
        "by_route": conn["route"].fillna("unattributed").value_counts().to_dict(),
        "mw_by_route": conn.groupby(conn["route"].fillna("unattributed"))["capacity_mw"]
        .sum()
        .round(1)
        .to_dict(),
    }
    # Diagnostic only (never used for attribution): asset-to-attached-node distance.
    dists = []
    for rec in conn[conn["route"].notna()].itertuples():
        pts = [nodes.loc[n, ["lat", "lon"]] for n in rec.nodes if pd.notna(nodes.loc[n, "lat"])]
        if pts and pd.notna(rec.lat):
            dists.append(min(ur.haversine_km(rec.lat, rec.lon, p.lat, p.lon) for p in pts))
    d = pd.Series(dists)
    summary["solar_attribution_distance_check_km"] = {
        "n": len(d),
        "median": round(float(d.median()), 2) if len(d) else None,
        "p90": round(float(d.quantile(0.9)), 2) if len(d) else None,
        "share_over_30km": round(float((d > 30).mean()), 4) if len(d) else None,
    }
    attr_out = attr[
        [
            "register",
            "area",
            "connection_status",
            "capacity_mw",
            "grid_supply_point",
            "bulk_supply_point",
            "primary",
            "floc",
            "route",
        ]
    ].assign(nodes=attr["nodes"].map(lambda ns: "; ".join(sorted(ns))))
    attr_out.to_csv(TABLES / "e0_ukpn_solar_attribution.csv", index_label="ecr_row")

    # ---- regions + ranking
    regions = ur.gsp_regions(branches)
    bsp, bsp_counters = ur.bsp_subtrees(branches)
    regions += bsp
    summary["regions"] = {
        "gsp_groups": sum(r.level == "gsp" for r in regions),
        "bsp_subtrees": len(bsp),
        **bsp_counters,
    }
    sel = region_cfg["selection"]
    ranked = ur.eligibility(
        ur.score_regions(regions, branches, nodes, line_status, attr, rcfg), sel
    )
    ranked.to_csv(TABLES / "e0_ukpn_candidate_regions.csv", index=False)
    summary["n_candidate_regions"] = len(ranked)
    summary["n_candidates_in_size_band"] = int(ranked["size_in_band"].sum())
    summary["n_eligible"] = int(ranked["eligible"].sum())
    summary["ineligibility_reasons"] = (
        ranked.loc[~ranked["eligible"], "ineligible_reasons"]
        .str.split(", ")
        .explode()
        .value_counts()
        .to_dict()
    )
    summary["top_candidates"] = ranked.head(15).to_dict(orient="records")

    rob = sel["robustness"]
    sens = ur.weight_sensitivity(ranked, rcfg, rob["n_weight_draws"], rob["seed"])
    sens.to_csv(TABLES / "e0_ukpn_rank_sensitivity.csv", index=False)
    summary["sensitivity_top"] = sens.head(10).to_dict(orient="records")
    best = sens.iloc[0] if len(sens) else None
    selected = best is not None and best["p_top1"] >= rob["min_top1_share"]
    summary["selection"] = {
        "rule": sel,
        "selected": bool(selected),
        "region_id": best["candidate_region"] if selected else None,
        "best_eligible": None if best is None else best.to_dict(),
        "reason": (
            "best eligible region ranks first in "
            f"{best['p_top1']:.1%} of weight draws (threshold {rob['min_top1_share']:.0%})"
            if best is not None
            else "no region passes the hard requirements"
        ),
    }
    ecr_attr = ur.attribute_solar(
        ua.ecr_assets(ecr), nodes["kv"].to_dict(), floc_nodes, primary_nodes, bsp_nodes
    )
    artefacts = {
        "tables": t,
        "monthly": monthly,
        "coverages": {c.name: c.table for c in coverages},
        "floc_index": floc_index,
        "ecr_attr": ecr_attr,
        "regions": {r.region_id: r for r in regions},
        "branches": branches,
        "nodes": nodes,
        "line_status": line_status,
        "solar": attr,
        "ranked": ranked,
        "coverage_names": {
            name: ds for name, ds in cfg["datasets"].items() if ds["mode"] == "coverage"
        },
    }
    return summary, artefacts


# ------------------------------------------------------------------------------ report


def write_markdown(sources: pd.DataFrame, summary: dict[str, Any], generated_at: str) -> None:
    cols = [
        "name",
        "dataset_id",
        "registry_licence",
        "portal_licence",
        "gate",
        "records_count",
        "modified",
        "rows_local",
        "status",
    ]
    lines = [
        "# E0-D UKPN audit — generated output",
        "",
        f"_Generated by `scripts/audit_ukpn.py` at {generated_at}. Do not edit by hand; "
        "interpretation lives in `reports/e0_data_audit.md`._",
        "",
        "## Sources",
        "",
        markdown.table(sources[[c for c in cols if c in sources]]),
    ]
    joins_path = TABLES / "e0_ukpn_identifier_overlap.csv"
    if joins_path.exists() and "joins" in summary:
        jcols = [
            "join",
            "left_rows",
            "left_rows_without_key",
            "matched_rows",
            "unmatched_rows",
            "match_pct",
            "left_duplicate_key_rows",
            "right_ambiguous_keys",
            "ambiguous_matched_rows",
        ]
        lines += ["", "## Joins", "", markdown.table(pd.read_csv(joins_path)[jcols])]
    if summary.get("top_candidates"):
        tc = pd.DataFrame(summary["top_candidates"])[
            [
                "candidate_region",
                "level",
                "n_nodes",
                "n_circuits",
                "n_circuits_132kv",
                "n_circuits_33kv",
                "n_usable_measured_circuits",
                "n_usable_active_power_circuits",
                "solar_mw",
                "n_solar_assets",
                "topology_score",
                "measurement_score",
                "solar_score",
                "coordinate_score",
                "identifier_score",
                "overall_score",
                "known_limitations",
            ]
        ]
        lines += ["", "## Top candidate regions", "", markdown.table(tc)]
    lines += [
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(
            {k: v for k, v in summary.items() if k not in ("top_candidates", "joins")},
            indent=2,
            default=str,
        ),
        "```",
    ]
    GENERATED_MD.write_text("\n".join(lines) + "\n")


def write_study_region(
    summary: dict[str, Any], art: dict[str, Any], generated_at: str, decision: dict[str, Any] | None
) -> None:
    """Freeze the selected region for E1 (identifiers only, no customer data).

    `decision` is None when the original E0-D rule selected the region; otherwise it is the
    post-audit manual decision (configs/networks/region_decision.yaml), recorded verbatim.
    """
    sel = summary["selection"]
    region_id = sel["region_id"] if decision is None else decision["region_id"]
    region = art["regions"][region_id]
    t = art["tables"]
    mb = sr.model_branches(region, art["branches"], t["ltds_transformers_2w"])
    sites = t["grid_and_primary_sites"]
    nodes = ur.node_table(mb, art["floc_index"], sites)
    model_nodes = set(nodes.index)
    row = art["ranked"].set_index("candidate_region").loc[region_id]
    role_of = {}
    for b in mb.itertuples():
        for key, kv in ((b.from_key, b.from_kv), (b.to_key, b.to_kv)):
            if b.role == "primary_transformer" and kv != 33.0:
                role_of.setdefault(key, "primary_lv_busbar")
            elif b.role == "boundary_132kv" and key not in region.node_keys:
                role_of.setdefault(key, "boundary_busbar")
            else:
                role_of[key] = "e0_region"

    site_coords = sites.set_index("sitefunctionallocation")
    flocs = sorted({f for fl in nodes["flocs"] for f in fl.split("; ") if f})
    mb_t2 = mb[mb["role"] == "primary_transformer"]
    t2 = t["ltds_transformers_2w"]
    flocs = sorted(
        set(flocs)
        | set(
            t2[t2["id"].astype(str).isin(mb_t2["branch_id"].str.split(":").str[1])][
                "sitefunctionallocation"
            ].dropna()
        )
    )
    demand = t["ltds_demand_3a"]

    doc = {
        "region_id": region_id,
        "status": "selected for E1 (planning topology; reconstruction/validation in E1/E2)",
        "written_at": generated_at,
        "selection": {
            "mode": "e0_rule" if decision is None else decision["selection_mode"],
            "passed_original_robustness_rule": bool(sel["selected"]),
            "original_rule_result": sel["reason"],
            "original_rule": sel["rule"],
            "original_scores": {k: float(row[k]) for k in ur.SCORE_COLUMNS},
            "original_overall_score_equal_weights": float(row["overall_score"]),
            "original_sensitivity_best_eligible": {
                k: sr._none(v) for k, v in (sel["best_eligible"] or {}).items()
            },
            "post_audit_decision": decision,
            "inputs_excluded": ["GENCO outputs", "weather/satellite data"],
        },
        "level": region.level,
        "licence_area": region.area,
        "ltds_gsps": list(region.gsps),
        "feeding_grid_substations": list(region.feeding_substations),
        "e0_region": {
            "node_keys": sorted(region.node_keys),
            "branch_ids": sorted(region.branch_ids),
        },
        "model_extension_rules": {
            "boundary_132kv": "LTDS 132 kV circuits with an endpoint at a region 132 kV node",
            "primary_transformer": "LTDS T2a transformers whose HV node is a region 33 kV node",
        },
        "nodes": [
            {
                "node_key": key,
                "role": role_of.get(key, "e0_region"),
                "kv": float(n["kv"]),
                "substation_names": n["substation_names"],
                "site_flocs": n["flocs"] or None,
                "lat": sr._none(n["lat"]),
                "lon": sr._none(n["lon"]),
                "geolocation_status": n["coord_status"],
            }
            for key, n in nodes.iterrows()
        ],
        "branches": [
            {
                "branch_id": b.branch_id,
                "ltds_table": b.branch_id.split(":")[0],
                "ltds_id": int(b.branch_id.split(":")[1]),
                "role": b.role,
                "kind": b.kind,
                "from": b.from_key,
                "to": b.to_key,
                "kv": [float(b.from_kv), float(b.to_kv)],
                "ltds_line_name": b.line_name,
                "params_complete": bool(b.params_complete),
            }
            for b in mb.itertuples()
        ],
        "sites": [
            {
                "site_floc": f,
                "sitename": site_coords.loc[f, "sitename"] if f in site_coords.index else None,
                "sitetype": site_coords.loc[f, "sitetype"] if f in site_coords.index else None,
                "lat": sr._none(site_coords.loc[f, "lat"]) if f in site_coords.index else None,
                "lon": sr._none(site_coords.loc[f, "lon"]) if f in site_coords.index else None,
            }
            for f in flocs
        ],
        "assets": sr.attached_assets(art["ecr_attr"], model_nodes),
        "measurements": {
            "circuits": sr.linked_circuit_series(
                art["monthly"], model_nodes, art["coverages"], mb["line_name"].dropna()
            ),
            "grid_transformers": sr.linked_transformer_series(t["grid_tx_monthly"], model_nodes),
            "primary_transformers": sr.linked_transformer_series(
                t["primary_tx_monthly"], model_nodes
            ),
            "half_hourly_datasets": {
                "circuits_33kv": "ukpn_33kv_operational_half_hourly_epn",
                "grid_transformers": "ukpn_grid_transformer_half_hourly",
                "primary_transformers": "ukpn_primary_transformer_half_hourly_epn",
            },
        },
        "planning_demand_ltds_3a": [
            {k: sr._none(v) for k, v in r.items() if k not in ("licencearea", "substation_mrid")}
            for r in demand[demand["functional_location"].isin(flocs)].to_dict(orient="records")
        ],
        "known_limitations_e0": [x for x in str(row["known_limitations"]).split("; ") if x],
        "provenance_classes": {
            "topology": "DERIVED from LTDS planning tables (not operational state)",
            "measurements": "OBSERVED (UKPN operational data)",
            "assets": "register entries (capacities, not generation)",
        },
    }
    header = (
        "# Study region. GENERATED by scripts/audit_ukpn.py --write-study-region; do not edit.\n"
        "# selection.mode says whether the E0-D rule selected it or a post-audit decision did.\n"
        "# ECR assets are referenced by register row, site FLOC and capacity only.\n"
    )
    STUDY_REGION.write_text(header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--refresh", action="store_true", help="re-download existing tables")
    group.add_argument("--offline", action="store_true", help="never download")
    parser.add_argument(
        "--write-study-region",
        action="store_true",
        help="write configs/networks/study_region.yaml if the selection rule passes, or from an "
        "explicit post-audit decision (configs/networks/region_decision.yaml) if it does not",
    )
    args = parser.parse_args()

    cfg = yaml.safe_load(DATA_CONFIG.read_text())
    region_cfg = yaml.safe_load(REGION_CONFIG.read_text())
    registry = Registry.load()
    TABLES.mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")

    sources = acquire(cfg, registry, args.refresh, args.offline)
    sources.to_csv(TABLES / "e0_ukpn_sources.csv", index=False)
    summary, artefacts = analyse(cfg, region_cfg)
    if args.write_study_region:
        if summary.get("selection", {}).get("selected"):
            write_study_region(summary, artefacts, generated_at, decision=None)
            print(f"Wrote {STUDY_REGION.relative_to(REPO_ROOT)} (E0-D rule passed)")
        elif DECISION.exists():
            decision = yaml.safe_load(DECISION.read_text())
            if decision.get("passed_original_robustness_rule") is not False:
                raise SystemExit("region_decision.yaml must state passed_original_robustness_rule")
            write_study_region(summary, artefacts, generated_at, decision=decision)
            print(
                f"Selection rule NOT met; wrote {STUDY_REGION.relative_to(REPO_ROOT)} from the "
                f"post-audit decision in {DECISION.relative_to(REPO_ROOT)}"
            )
        else:
            print("Selection rule not met — study_region.yaml NOT written.")
    summary["generated_at"] = generated_at
    summary["statuses"] = dict(zip(sources["name"], sources["status"], strict=True))
    (RUN_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    write_markdown(sources, summary, generated_at)

    print(sources[["name", "records_count", "rows_local", "status"]].to_string(index=False))
    if summary["missing_for_ranking"]:
        print(f"\nRanking not possible yet — missing: {summary['missing_for_ranking']}")
        return 2
    print(
        f"\nRanked {summary['n_candidate_regions']} candidate regions "
        f"({summary['n_candidates_in_size_band']} in size band)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
