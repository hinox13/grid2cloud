"""Measure cross-dataset joins on real values (E0-D §4).

Every join is exact on a documented key (optionally normalised with
`ukpn_audit.normalise_name` and/or scoped by licence area). No fuzzy matching.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def measure_join(
    name: str,
    left: pd.Series,
    right: pd.Series,
    *,
    right_entity: pd.Series | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Match statistics for left keys looked up in right keys.

    left          one key per left row (None/NaN = row has no usable key)
    right         one key per right row
    right_entity  entity ID per right row (defaults to the key itself). A right key is
                  *ambiguous* if it maps to more than one distinct entity.
    """
    left = pd.Series(left).reset_index(drop=True)
    right = pd.Series(right).reset_index(drop=True)
    entity = right if right_entity is None else pd.Series(right_entity).reset_index(drop=True)
    right_df = pd.DataFrame({"key": right, "entity": entity}).dropna(subset=["key"])
    entities_per_key = right_df.groupby("key")["entity"].nunique()
    ambiguous_keys = set(entities_per_key[entities_per_key > 1].index)
    right_keys = set(entities_per_key.index)

    has_key = left.notna()
    matched = has_key & left.isin(right_keys)
    keyed = int(has_key.sum())
    unmatched_values = left[has_key & ~matched]
    return {
        "join": name,
        "left_rows": len(left),
        "left_rows_without_key": int((~has_key).sum()),
        "matched_rows": int(matched.sum()),
        "unmatched_rows": int((has_key & ~matched).sum()),
        "match_pct": round(100 * matched.sum() / keyed, 2) if keyed else 0.0,
        "left_duplicate_key_rows": int(left[has_key].duplicated(keep=False).sum()),
        "right_distinct_keys": len(right_keys),
        "right_ambiguous_keys": len(ambiguous_keys),
        "ambiguous_matched_rows": int((matched & left.isin(ambiguous_keys)).sum()),
        "unmatched_examples": "; ".join(map(str, unmatched_values.drop_duplicates().head(5))),
        "note": note,
    }
