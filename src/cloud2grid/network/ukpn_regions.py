"""Candidate study regions from the LTDS 132/33 kV planning network (E0-D §7–8).

Region levels
    gsp          all 132/33 kV LTDS branches listed under one LTDS `gridsupplypoint`
    bsp_subtree  one connected 33 kV network (LTDS T1 33 kV circuits, area-scoped node IDs)
                 plus the 132/33 kV grid transformers (LTDS T2a) feeding it and their 132 kV
                 busbar nodes. This is the electrically meaningful split of a large GSP group.

Geography comes only from Grid/Primary Site coordinates, reached through site functional
locations (FLOCs) or exact normalised substation names. Solar assets are attributed to
electrical nodes through identifiers only (ECR FLOC → LTDS transformer/circuit site → node;
then ECR primary name; then ECR BSP name). Geographic proximity is never used to infer an
electrical connection. Ranking never uses GENCO results or weather data.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from cloud2grid.network.ukpn_audit import (
    licence_area_code,
    node_key,
    normalise_name,
    parse_voltage_kv,
)

STUDY_KV = (132.0, 33.0)
GENERIC_SUBSTATION_PREFIXES = ("DNO UKPN", "EPN ", "SPN ", "LPN ", "CUSTOMER")


def _kv_class(kv: float | None) -> float | None:
    """Round nominal voltages: 33.2 → 33, 132 → 132; others → None (outside study levels)."""
    if kv is None or pd.isna(kv):
        return None
    for level in STUDY_KV:
        if abs(kv - level) <= 0.05 * level:
            return level
    return None


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


# ------------------------------------------------------------------------------ branches


def build_branches(
    circuits: pd.DataFrame, t2: pd.DataFrame, t3: pd.DataFrame | None = None
) -> tuple[pd.DataFrame, dict[str, int]]:
    """132/33 kV branches (circuits + 132/33 kV transformers) with area-scoped node keys."""
    rows: list[dict[str, Any]] = []
    counters = {"t1_rows": len(circuits), "t1_unparsed_voltage": 0, "self_loops_skipped": 0}

    for rec in circuits.to_dict(orient="records"):
        kv_raw = parse_voltage_kv(rec.get("operating_voltage"))
        if kv_raw is None:
            counters["t1_unparsed_voltage"] += 1
            continue
        kv = _kv_class(kv_raw)
        if kv is None:
            continue
        f_key = node_key(rec.get("licencearea"), rec.get("fromnode"))
        t_key = node_key(rec.get("licencearea"), rec.get("tonode"))
        if f_key == t_key:
            counters["self_loops_skipped"] += 1
            continue
        rating = pd.to_numeric(rec.get("rating_amps_summer"), errors="coerce")
        rows.append(
            {
                "branch_id": f"T1:{rec.get('id')}",
                "kind": "circuit",
                "area": licence_area_code(rec.get("licencearea")),
                "gsp": rec.get("gridsupplypoint"),
                "from_key": f_key,
                "to_key": t_key,
                "from_kv": kv,
                "to_kv": kv,
                "line_name": rec.get("linename"),
                "from_sub": rec.get("fromsubstation"),
                "to_sub": rec.get("tosubstation"),
                "params_complete": bool(
                    pd.notna(rec.get("positive_sequence_impedance_r_percent"))
                    and pd.notna(rec.get("positive_sequence_impedance_x_percent"))
                    and pd.notna(rating)
                    and rating > 0
                ),
            }
        )

    for rec in t2.to_dict(orient="records"):
        hv = _kv_class(parse_voltage_kv(rec.get("voltage_hv")))
        lv = _kv_class(parse_voltage_kv(rec.get("voltage_lv")))
        if (hv, lv) != (132.0, 33.0):
            continue
        rows.append(
            {
                "branch_id": f"T2a:{rec.get('id')}",
                "kind": "transformer",
                "area": licence_area_code(rec.get("licencearea")),
                "gsp": rec.get("gridsupplypoint"),
                "from_key": node_key(rec.get("licencearea"), rec.get("hv_node")),
                "to_key": node_key(rec.get("licencearea"), rec.get("lv_node")),
                "from_kv": hv,
                "to_kv": lv,
                "line_name": None,
                "from_sub": rec.get("hv_substation"),
                "to_sub": rec.get("lv_substation"),
                "params_complete": bool(
                    pd.notna(rec.get("positive_sequence_impedance_r_percent"))
                    and pd.notna(rec.get("positive_sequence_impedance_x_percent"))
                    and pd.notna(rec.get("transformer_rating_mva_summer"))
                ),
            }
        )

    for rec in (t3 if t3 is not None else pd.DataFrame()).to_dict(orient="records"):
        hv = _kv_class(parse_voltage_kv(rec.get("voltage_hv")))
        for i in (1, 2):
            lv = _kv_class(parse_voltage_kv(rec.get(f"voltage_lv_{i}")))
            if (hv, lv) != (132.0, 33.0):
                continue
            rows.append(
                {
                    "branch_id": f"T2b:{rec.get('id')}:{i}",
                    "kind": "transformer",
                    "area": licence_area_code(rec.get("licencearea")),
                    "gsp": rec.get("gridsupplypoint"),
                    "from_key": node_key(rec.get("licencearea"), rec.get("hv_node")),
                    "to_key": node_key(rec.get("licencearea"), rec.get(f"lv_node_{i}")),
                    "from_kv": hv,
                    "to_kv": lv,
                    "line_name": None,
                    "from_sub": rec.get("hv_substation"),
                    "to_sub": rec.get(f"lv_substation_{i}"),
                    "params_complete": bool(
                        pd.notna(rec.get(f"positive_sequence_impedance_x_hv_lv{i}_percent"))
                    ),
                }
            )

    branches = pd.DataFrame(rows)
    branches = branches.dropna(subset=["from_key", "to_key"]).reset_index(drop=True)
    return branches, counters


# ---------------------------------------------------------------------------- geography


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def substation_floc_index(
    circuits: pd.DataFrame, t2: pd.DataFrame, t3: pd.DataFrame | None, sites: pd.DataFrame
) -> dict[tuple[str, str], set[str]]:
    """(area, normalised substation name) → site FLOCs, from FLOCs published *in* the data.

    Sources: LTDS T1 from-side FLOC, LTDS T2a/T2b site FLOC (for hv and lv substation names),
    and Grid/Primary Sites `sitename` (exact normalised name).
    """
    index: dict[tuple[str, str], set[str]] = {}

    def add(area: object, name: object, floc: object) -> None:
        area_code, key = licence_area_code(area), normalise_name(name)
        if (
            area_code
            and key
            and isinstance(floc, str)
            and floc.startswith(("EPN-", "SPN-", "LPN-"))
        ):
            index.setdefault((area_code, key), set()).add(floc)

    for rec in circuits.to_dict(orient="records"):
        add(
            rec.get("licencearea"),
            rec.get("fromsubstation"),
            rec.get("fromsubstation_sitefunctionallocation"),
        )
    for table, names in [
        (t2, ("hv_substation", "lv_substation")),
        (
            t3 if t3 is not None else pd.DataFrame(),
            ("hv_substation", "lv_substation_1", "lv_substation_2"),
        ),
    ]:
        for rec in table.to_dict(orient="records"):
            for name in names:
                add(rec.get("licencearea"), rec.get(name), rec.get("sitefunctionallocation"))
    for rec in sites.to_dict(orient="records"):
        add(rec.get("licencearea"), rec.get("sitename"), rec.get("sitefunctionallocation"))
    return index


def node_table(
    branches: pd.DataFrame,
    floc_index: dict[tuple[str, str], set[str]],
    site_coords: pd.DataFrame,
    max_spread_km: float = 2.0,
) -> pd.DataFrame:
    """One row per network node: voltage, substation names, FLOCs and resolved coordinates.

    Coordinates are 'resolved' when all FLOCs reachable from the node's substation name(s) lie
    within `max_spread_km` of each other (e.g. a grid site's 132 kV and 33 kV site records).
    """
    coords = site_coords.set_index("sitefunctionallocation")[["lat", "lon"]].dropna()
    long = pd.concat(
        [
            branches[["from_key", "from_sub", "from_kv", "area"]].set_axis(
                ["node", "sub", "kv", "area"], axis=1
            ),
            branches[["to_key", "to_sub", "to_kv", "area"]].set_axis(
                ["node", "sub", "kv", "area"], axis=1
            ),
        ]
    )
    rows = []
    for node, grp in long.groupby("node"):
        names = {k for k in grp["sub"].map(normalise_name) if k}
        specific = {n for n in names if not n.startswith(GENERIC_SUBSTATION_PREFIXES)}
        area = grp["area"].iloc[0]
        flocs = (
            set().union(*(floc_index.get((area, n), set()) for n in specific))
            if specific
            else set()
        )
        pts = [tuple(coords.loc[f]) for f in flocs if f in coords.index]
        lat = lon = None
        spread = 0.0
        if pts:
            spread = max(haversine_km(*a, *b) for a in pts for b in pts)
            if spread <= max_spread_km:
                lat = sum(p[0] for p in pts) / len(pts)
                lon = sum(p[1] for p in pts) / len(pts)
        status = "resolved" if lat is not None else ("ambiguous" if pts else "unresolved")
        rows.append(
            {
                "node_key": node,
                "area": area,
                "kv": float(grp["kv"].max()),
                "n_kv_levels": int(grp["kv"].nunique()),
                "substation_names": "; ".join(sorted(names)),
                "n_specific_names": len(specific),
                "flocs": "; ".join(sorted(flocs)),
                "n_flocs": len(flocs),
                "coord_spread_km": round(spread, 3),
                "lat": lat,
                "lon": lon,
                "coord_status": status,
            }
        )
    return pd.DataFrame(rows).set_index("node_key")


# ------------------------------------------------------------------------------ regions


@dataclass(frozen=True)
class Region:
    region_id: str
    level: str
    area: str
    gsps: tuple[str, ...]
    node_keys: frozenset[str]
    branch_ids: frozenset[str]
    feeding_substations: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)


def n_components(branches: pd.DataFrame) -> int:
    uf = _UnionFind()
    for a, b in zip(branches["from_key"], branches["to_key"], strict=True):
        uf.union(a, b)
    return len({uf.find(x) for x in list(uf.parent)})


def gsp_regions(branches: pd.DataFrame) -> list[Region]:
    regions = []
    for (area, gsp), grp in branches.groupby(["area", "gsp"]):
        nodes = frozenset(grp["from_key"]) | frozenset(grp["to_key"])
        regions.append(
            Region(f"GSP:{area}:{gsp}", "gsp", area, (gsp,), nodes, frozenset(grp["branch_id"]))
        )
    return regions


def bsp_subtrees(branches: pd.DataFrame) -> tuple[list[Region], dict[str, int]]:
    """Connected 33 kV networks fed by 132/33 kV grid transformers."""
    c33 = branches[(branches["kind"] == "circuit") & (branches["from_kv"] == 33.0)]
    gtx = branches[branches["kind"] == "transformer"]
    uf = _UnionFind()
    for a, b in zip(c33["from_key"], c33["to_key"], strict=True):
        uf.union(a, b)
    for lv in gtx["to_key"]:
        uf.find(lv)
    root_of = {n: uf.find(n) for n in list(uf.parent)}

    regions: list[Region] = []
    unfed_components = unfed_nodes = 0
    for root in sorted(set(root_of.values())):
        members = frozenset(n for n, r in root_of.items() if r == root)
        feeders = gtx[gtx["to_key"].isin(members)]
        circuits = c33[c33["from_key"].isin(members)]
        if feeders.empty:
            unfed_components += 1
            unfed_nodes += len(members)
            continue
        grid_subs = tuple(sorted(set(feeders["to_sub"].dropna())))
        gsps = tuple(sorted(set(feeders["gsp"].dropna()) | set(circuits["gsp"].dropna())))
        nodes = members | frozenset(feeders["from_key"])
        notes = []
        if len(gsps) > 1:
            notes.append(
                f"33 kV network spans {len(gsps)} LTDS GSPs — likely normally-open ties "
                "(planning topology; open/closed state not published)"
            )
        label = grid_subs[0] + (f" +{len(grid_subs) - 1}" if len(grid_subs) > 1 else "")
        regions.append(
            Region(
                region_id=f"BSP:{feeders['area'].iloc[0]}:{label}",
                level="bsp_subtree",
                area=feeders["area"].iloc[0],
                gsps=gsps,
                node_keys=nodes,
                branch_ids=frozenset(circuits["branch_id"]) | frozenset(feeders["branch_id"]),
                feeding_substations=grid_subs,
                notes=tuple(notes),
            )
        )
    return regions, {"unfed_33kv_components": unfed_components, "unfed_33kv_nodes": unfed_nodes}


# ---------------------------------------------------------------------- solar attribution


def site_node_index(
    circuits: pd.DataFrame, t2: pd.DataFrame, network_nodes: Iterable[str]
) -> tuple[dict[str, set[str]], dict[tuple[str, str], set[str]], dict[tuple[str, str], set[str]]]:
    """Lookup tables from published identifiers to network node keys.

    floc_nodes     site FLOC → nodes at that site (T2a hv/lv nodes, T1 from-node)
    primary_nodes  (area, normalised T2a lv_substation) → T2a hv node (the 33 kV busbar
                   feeding that primary)
    bsp_nodes      (area, normalised 132/33 kV lv_substation) → 33 kV busbar node(s)
    Only nodes inside the 132/33 kV network are kept.
    """
    network = set(network_nodes)
    floc_nodes: dict[str, set[str]] = {}
    primary_nodes: dict[tuple[str, str], set[str]] = {}
    bsp_nodes: dict[tuple[str, str], set[str]] = {}
    for rec in t2.to_dict(orient="records"):
        area = licence_area_code(rec.get("licencearea"))
        hv = node_key(rec.get("licencearea"), rec.get("hv_node"))
        lv = node_key(rec.get("licencearea"), rec.get("lv_node"))
        floc = rec.get("sitefunctionallocation")
        for node in (hv, lv):
            if node in network and isinstance(floc, str):
                floc_nodes.setdefault(floc, set()).add(node)
        lv_name = normalise_name(rec.get("lv_substation"))
        if area and lv_name and hv in network:
            primary_nodes.setdefault((area, lv_name), set()).add(hv)
        hv_kv = _kv_class(parse_voltage_kv(rec.get("voltage_hv")))
        lv_kv = _kv_class(parse_voltage_kv(rec.get("voltage_lv")))
        if (hv_kv, lv_kv) == (132.0, 33.0) and area and lv_name and lv in network:
            bsp_nodes.setdefault((area, lv_name), set()).add(lv)
    for rec in circuits.to_dict(orient="records"):
        node = node_key(rec.get("licencearea"), rec.get("fromnode"))
        floc = rec.get("fromsubstation_sitefunctionallocation")
        if node in network and isinstance(floc, str) and floc != "CUSTOMER_SITE":
            floc_nodes.setdefault(floc, set()).add(node)
    return floc_nodes, primary_nodes, bsp_nodes


def attribute_solar(
    solar: pd.DataFrame,
    node_kv: dict[str, float],
    floc_nodes: dict[str, set[str]],
    primary_nodes: dict[tuple[str, str], set[str]],
    bsp_nodes: dict[tuple[str, str], set[str]],
) -> pd.DataFrame:
    """Attach each solar asset to 132/33 kV network node(s) via identifiers only.

    Route priority: ECR site FLOC → ECR primary name → ECR bulk-supply-point name. When a site
    has nodes at both 132 and 33 kV, the node matching the ECR point-of-connection voltage is
    used (132 if POC ≥ 100 kV, otherwise 33 kV). Unattributed assets keep `route = None`.
    """
    out = []
    for idx, rec in solar.iterrows():
        area = rec.get("area")
        poc = parse_voltage_kv(rec.get("point_of_connection_poc_voltage_kv"))
        want = 132.0 if (poc is not None and poc >= 100) else 33.0
        candidates = [
            (
                "floc",
                floc_nodes.get(rec.get("floc"), set())
                if isinstance(rec.get("floc"), str)
                else set(),
            ),
            ("primary_name", primary_nodes.get((area, rec.get("primary_key")), set())),
            ("bsp_name", bsp_nodes.get((area, rec.get("bsp_key")), set())),
        ]
        route, nodes = None, set()
        for name, found in candidates:
            if found:
                route, nodes = name, found
                break
        preferred = {n for n in nodes if node_kv.get(n) == want}
        nodes = preferred or nodes
        out.append({"ecr_index": idx, "route": route, "nodes": frozenset(nodes)})
    attr = pd.DataFrame(out).set_index("ecr_index")
    return solar.join(attr)


# ---------------------------------------------------------------------- measurement status


@dataclass(frozen=True)
class HalfHourlyCoverage:
    """Server-side per-line aggregate of one half-hourly dataset and what it covers."""

    name: str
    areas: frozenset[str]
    kv: float
    table: pd.DataFrame  # ltds_line_name, n_rows, n_active_power, n_current, first/last_timestamp


def build_line_status(
    branches: pd.DataFrame,
    circuits_all: pd.DataFrame,
    publication: pd.DataFrame,
    coverages: list[HalfHourlyCoverage],
    cfg: RankingConfig,
) -> pd.DataFrame:
    """One row per (area, LTDS line name) of the 132/33 kV study circuits."""
    study = branches[branches["kind"] == "circuit"]
    study = study.assign(
        pair=[frozenset(p) for p in zip(study["from_key"], study["to_key"], strict=True)]
    )
    name_counts = (
        circuits_all.assign(area=circuits_all["licencearea"].map(licence_area_code))
        .groupby(["area", "linename"])
        .size()
    )
    # A duplicated line name unions its circuits' nodes, so it can never look node-consistent.
    pairs = study.groupby(["area", "line_name"]).agg(
        kv=("from_kv", "first"), ltds_pair=("pair", lambda s: frozenset().union(*s))
    )
    pub = publication.set_index(["area", "line_name"])
    out = pairs.join(pub, how="left")
    out["ltds_name_unique"] = [name_counts.get(k, 0) == 1 for k in out.index]
    out["in_monthly_index"] = out["n_months"].notna()
    out["node_pair_consistent"] = [
        bool(row.in_monthly_index)
        and row.n_node_pairs == 1
        and frozenset((row.from_node_key, row.to_node_key)) == row.ltds_pair
        for row in out.itertuples()
    ]

    # Half-hourly rows carry no licence-area field: a line name present in LTDS under more
    # than one area cannot be attributed and is marked ambiguous rather than "checked".
    areas_per_name = name_counts.reset_index().groupby("linename")["area"].nunique()

    records = []
    for (area, line), row in out.iterrows():
        cov = next((c for c in coverages if area in c.areas and c.kv == row.kv), None)
        rec: dict[str, Any] = {"hh_dataset": cov.name if cov else None}
        if cov is None:
            rec["hh_status"] = "no_half_hourly_dataset"
        elif len(cov.areas) > 1 and areas_per_name.get(line, 0) > 1:
            rec["hh_status"] = "ambiguous_line_name_across_areas"
        else:
            hit = cov.table[cov.table["ltds_line_name"] == line]
            if hit.empty:
                rec["hh_status"] = "absent_from_half_hourly"
                rec["hh_active_power_completeness"] = 0.0
                rec["hh_current_completeness"] = 0.0
            else:
                h = hit.iloc[0]
                rec.update(
                    hh_status="checked",
                    hh_rows=int(h["n_rows"]),
                    hh_active_power_completeness=float(h["n_active_power"]) / float(h["n_rows"]),
                    hh_current_completeness=float(h["n_current"]) / float(h["n_rows"]),
                    hh_first_timestamp=h["first_timestamp"],
                    hh_last_timestamp=h["last_timestamp"],
                )
        records.append(rec)
    hh = pd.DataFrame(records, index=out.index)
    for column in (
        "hh_rows",
        "hh_active_power_completeness",
        "hh_current_completeness",
        "hh_first_timestamp",
        "hh_last_timestamp",
    ):
        if column not in hh:
            hh[column] = None
    out = out.join(hh)

    thr = cfg.min_hh_completeness
    monthly_ok = out["usable_monthly"].fillna(False).astype(bool)
    checked = out["hh_status"] == "checked"
    p_ok = checked & (out["hh_active_power_completeness"].fillna(0) >= thr)
    i_ok = checked & (out["hh_current_completeness"].fillna(0) >= thr)
    no_hh = out["hh_status"] == "no_half_hourly_dataset"
    # usable: an OBSERVED flow quantity (|I| or P) is published; usable_active_power: P is.
    out["usable"] = monthly_ok & (p_ok | i_ok | no_hh)
    out["usable_active_power"] = monthly_ok & p_ok
    out["usable_monthly_only"] = monthly_ok & no_hh
    out = out.drop(columns=["ltds_pair"])
    return out.reset_index()


# ------------------------------------------------------------------------------ scoring


@dataclass(frozen=True)
class RankingConfig:
    min_nodes: int = 10
    max_nodes: int = 50
    solar_mw_target: float = 50.0
    min_public_fraction: float = 0.9
    min_hh_completeness: float = 0.8
    out_of_band_penalty: float = 0.5
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "topology_score": 1.0,
            "measurement_score": 1.0,
            "solar_score": 1.0,
            "coordinate_score": 1.0,
            "identifier_score": 1.0,
        }
    )


def score_regions(
    regions: list[Region],
    branches: pd.DataFrame,
    nodes: pd.DataFrame,
    line_status: pd.DataFrame,
    solar_attr: pd.DataFrame,
    cfg: RankingConfig,
) -> pd.DataFrame:
    """Transparent per-region scores, each in [0, 1].

    topology_score     mean of: share of region branches with complete electrical parameters
                       (circuits: R, X, summer rating > 0; transformers: R, X, MVA rating);
                       1 / number of connected components; share of nodes WITHOUT
                       conflicting substation names (≤ 1 specific name; unnamed tee points
                       are not penalised here — they are already counted by coordinate_score)
    measurement_score  mean of two shares of region circuits: (a) *usable* — published in
                       the monthly index in ≥ min_public_fraction of months and, where a
                       half-hourly dataset exists for that area/voltage, with current OR
                       active power non-null in ≥ min_hh_completeness of half-hourly rows;
                       (b) *usable_active_power* — the same with active power specifically
                       (needed for flow direction). Most 33 kV lines publish current only.
    solar_score        min(1, connected solar MW attributed to region nodes / solar_mw_target)
    coordinate_score   share of region nodes with resolved site coordinates
    identifier_score   share of region circuits found in the monthly index whose LTDS line
                       name is unique and whose monthly from/to nodes equal the LTDS nodes
    overall_score      weighted mean × out_of_band_penalty if n_nodes outside the size band
    """
    by_id = branches.set_index("branch_id")
    status = line_status.set_index(["area", "line_name"])
    connected = solar_attr[solar_attr["connected"] & solar_attr["route"].notna()]
    rows = []
    for region in regions:
        reg_branches = by_id.loc[sorted(region.branch_ids)].reset_index()
        circuits = reg_branches[reg_branches["kind"] == "circuit"]
        reg_nodes = nodes.loc[nodes.index.intersection(sorted(region.node_keys))]
        keys = list(zip(circuits["area"], circuits["line_name"], strict=True))
        st = status.reindex(keys)
        in_index = st["in_monthly_index"].fillna(False).astype(bool)
        usable = st["usable"].fillna(False).astype(bool)
        usable_p = st["usable_active_power"].fillna(False).astype(bool)
        consistent = (
            in_index
            & st["node_pair_consistent"].fillna(False).astype(bool)
            & st["ltds_name_unique"].fillna(False).astype(bool)
        )

        in_region = connected["nodes"].map(lambda ns, rn=region.node_keys: bool(ns) and ns <= rn)
        reg_solar = connected[in_region]
        solar_mw = float(reg_solar["capacity_mw"].sum())

        n_nodes = len(region.node_keys)
        scores = {
            "topology_score": (
                reg_branches["params_complete"].mean()
                + 1 / n_components(reg_branches)
                + (reg_nodes["n_specific_names"] <= 1).mean()
            )
            / 3,
            "measurement_score": (float(usable.mean()) + float(usable_p.mean())) / 2
            if len(circuits)
            else 0.0,
            "solar_score": min(1.0, solar_mw / cfg.solar_mw_target),
            "coordinate_score": float((reg_nodes["coord_status"] == "resolved").mean()),
            "identifier_score": float(consistent.sum() / in_index.sum()) if in_index.any() else 0.0,
        }
        in_band = cfg.min_nodes <= n_nodes <= cfg.max_nodes
        overall = sum(scores[k] * w for k, w in cfg.weights.items()) / sum(cfg.weights.values())
        if not in_band:
            overall *= cfg.out_of_band_penalty

        limits = list(region.notes)
        if not in_band:
            limits.append(f"{n_nodes} nodes outside [{cfg.min_nodes}, {cfg.max_nodes}]")
        if region.area == "LPN":
            limits.append("LPN: no monthly/half-hourly operational data published")
        monthly_only = int(st["usable_monthly_only"].fillna(False).astype(bool).sum())
        if monthly_only:
            limits.append(f"{monthly_only} circuits usable on monthly index only (no HH check)")
        if usable.any() and not usable_p.any():
            limits.append("measured circuits publish current only (no active power/direction)")
        not_indexed = int((~in_index).sum())
        if not_indexed:
            limits.append(f"{not_indexed}/{len(circuits)} circuits absent from monthly index")
        missing_cap = int(reg_solar["capacity_mw"].isna().sum())
        if missing_cap:
            limits.append(f"{missing_cap} connected solar assets lack capacity")
        n_amb_nodes = int((reg_nodes["coord_status"] == "ambiguous").sum())
        if n_amb_nodes:
            limits.append(f"{n_amb_nodes} nodes with ambiguous site coordinates")

        rows.append(
            {
                "candidate_region": region.region_id,
                "level": region.level,
                "licence_area": region.area,
                "gsps": "; ".join(region.gsps),
                "feeding_grid_substations": "; ".join(region.feeding_substations),
                "n_nodes": n_nodes,
                "n_circuits": len(circuits),
                "n_circuits_132kv": int((circuits["from_kv"] == 132.0).sum()),
                "n_circuits_33kv": int((circuits["from_kv"] == 33.0).sum()),
                "n_transformers": int((reg_branches["kind"] == "transformer").sum()),
                "n_circuits_in_monthly_index": int(in_index.sum()),
                "n_usable_measured_circuits": int(usable.sum()),
                "n_usable_active_power_circuits": int(usable_p.sum()),
                "solar_mw": round(solar_mw, 3),
                "n_solar_assets": len(reg_solar),
                **{k: round(float(v), 4) for k, v in scores.items()},
                "size_in_band": in_band,
                "overall_score": round(float(overall), 4),
                "known_limitations": "; ".join(limits),
            }
        )
    ranked = pd.DataFrame(rows)
    if ranked.empty:
        return ranked
    return ranked.sort_values(
        ["overall_score", "candidate_region"], ascending=[False, True]
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------- selection

SCORE_COLUMNS = (
    "topology_score",
    "measurement_score",
    "solar_score",
    "coordinate_score",
    "identifier_score",
)


def eligibility(ranked: pd.DataFrame, selection: dict[str, Any]) -> pd.DataFrame:
    """Hard requirements for a study region; adds `eligible` and `ineligible_reasons`."""
    checks = {
        "size_out_of_band": ~ranked["size_in_band"]
        if selection.get("require_size_in_band", True)
        else pd.Series(False, index=ranked.index),
        "too_few_measured_circuits": ranked["n_usable_measured_circuits"]
        < selection["min_usable_measured_circuits"],
        "no_active_power_circuit": ranked["n_usable_active_power_circuits"]
        < selection["min_usable_active_power_circuits"],
        "too_little_connected_solar": ranked["solar_mw"] < selection["min_connected_solar_mw"],
        "too_few_located_nodes": ranked["coordinate_score"] < selection["min_coordinate_score"],
    }
    failed = pd.DataFrame(checks)
    out = ranked.copy()
    out["eligible"] = ~failed.any(axis=1)
    out["ineligible_reasons"] = failed.apply(
        lambda row: ", ".join(name for name, bad in row.items() if bad), axis=1
    )
    return out


def weight_sensitivity(
    ranked: pd.DataFrame, cfg: RankingConfig, n_draws: int, seed: int
) -> pd.DataFrame:
    """Rank stability of eligible regions under random score weights.

    For each of `n_draws` Dirichlet(1, …, 1) weight vectors the overall score is recomputed
    (same size penalty) and eligible regions are re-ranked. Also reports leave-one-score-out
    ranks. Uses only the five audit scores — never GENCO or weather data.
    """
    import numpy as np

    pool = ranked[ranked["eligible"]].reset_index(drop=True)
    if pool.empty:
        return pool.assign(p_top1=[], p_top3=[], median_rank=[], worst_rank_leave_one_out=[])
    scores = pool[list(SCORE_COLUMNS)].to_numpy(dtype=float)
    penalty = np.where(pool["size_in_band"], 1.0, cfg.out_of_band_penalty)
    rng = np.random.default_rng(seed)
    weights = rng.dirichlet(np.ones(len(SCORE_COLUMNS)), size=n_draws)
    overall = (scores @ weights.T) * penalty[:, None]  # regions × draws
    ranks = (-overall).argsort(axis=0).argsort(axis=0) + 1
    loo = []
    for drop in range(len(SCORE_COLUMNS)):
        w = np.ones(len(SCORE_COLUMNS))
        w[drop] = 0
        o = scores @ (w / w.sum()) * penalty
        loo.append((-o).argsort().argsort() + 1)
    out = pool[["candidate_region", "level", "overall_score"]].copy()
    out["rank_equal_weights"] = (-pool["overall_score"].to_numpy()).argsort().argsort() + 1
    out["p_top1"] = (ranks == 1).mean(axis=1)
    out["p_top3"] = (ranks <= 3).mean(axis=1)
    out["median_rank"] = np.median(ranks, axis=1)
    out["worst_rank_leave_one_out"] = np.max(np.array(loo), axis=0)
    return out.sort_values(["p_top1", "p_top3"], ascending=False).reset_index(drop=True)
