import pandas as pd

from cloud2grid.network.ukpn_joins import measure_join


def test_measure_join_counts():
    left = pd.Series(["a", "a", "b", "z", None])
    right = pd.Series(["a", "b", "b", "c"])
    entity = pd.Series([1, 2, 3, 4])  # key "b" maps to two entities → ambiguous
    out = measure_join("test", left, right, right_entity=entity)
    assert out["left_rows"] == 5
    assert out["left_rows_without_key"] == 1
    assert out["matched_rows"] == 3 and out["unmatched_rows"] == 1
    assert out["match_pct"] == 75.0
    assert out["left_duplicate_key_rows"] == 2
    assert out["right_ambiguous_keys"] == 1 and out["ambiguous_matched_rows"] == 1
    assert out["unmatched_examples"] == "z"


def test_measure_join_without_entity_has_no_ambiguity():
    out = measure_join("t", pd.Series(["x"]), pd.Series(["x", "x"]))
    assert out["right_ambiguous_keys"] == 0 and out["match_pct"] == 100.0


def test_measure_join_empty_left():
    out = measure_join("t", pd.Series([None, None]), pd.Series(["x"]))
    assert out["match_pct"] == 0.0 and out["matched_rows"] == 0
