"""Tiny Markdown helpers for generated reports (avoids a `tabulate` dependency)."""

from __future__ import annotations

import pandas as pd


def table(df: pd.DataFrame, float_fmt: str = "{:.3f}") -> str:
    if df.empty:
        return "_(no rows)_"

    def fmt(value: object) -> str:
        if isinstance(value, float):
            return "" if pd.isna(value) else float_fmt.format(value)
        return str(value).replace("|", "\\|").replace("\n", " ")

    header = "| " + " | ".join(map(str, df.columns)) + " |"
    rule = "|" + "|".join("---" for _ in df.columns) + "|"
    body = ["| " + " | ".join(fmt(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([header, rule, *body])
