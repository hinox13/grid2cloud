"""Submission summary figure: "What did we learn?" (E4 → E5d), from frozen published tables only.

    uv run python scripts/plot_what_we_learned.py   # → reports/figures/c2g_what_we_learned.png

Numbers: reports/tables/e5d_real_transfer.csv (every model on the same 2,829 real S1 states;
values for zero-shot / E5 / E5b / E5c equal the E5c tables). Colours follow the Explorer's
light palette (demo/c2g/theme.py); each stage is named in text, never by colour alone.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from cloud2grid.licensing.registry import REPO_ROOT  # noqa: E402

INK, INK_2, MUTED, BORDER = "#0f172a", "#3b4659", "#5f6b84", "#d5dbe5"
STAGES = [  # (table row, name, code, what was added, what it showed, colour)
    ("zero-shot (E4)", "Off-the-shelf", "E4", "zero-shot", "Topology failure", "#eb6834"),  # noqa: E501
    ("E5", "Grid-tuned", "E5", "+ synthetic topology\nadaptation", "Synthetic success,\nreal failure", "#e87ba4"),  # noqa: E501
    ("E5b", "Envelope-tuned", "E5b", "+ broader operating\nenvelope", "~99 % lower\nreal-state error", "#1baf7a"),  # noqa: E501
    ("E5c", "Generator-aware", "E5c", "+ explicit generators", "Better load/battery;\nPV still blind", "#2a78d6"),  # noqa: E501
    ("E5d", "Response-aware", "E5d", "+ paired response\nsupervision", "PV sensitivity transfers;\ncalibration still off", "#751e5f"),  # noqa: E501
]  # fmt: skip


def main() -> int:
    t = pd.read_csv(REPO_ROOT / "reports/tables/e5d_real_transfer.csv").set_index("model")
    ac_pv = float(t.iloc[0]["ac_slope_pv"])
    fig = plt.figure(figsize=(15, 4.7), dpi=150)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 15)
    ax.set_ylim(0, 4.7)
    ax.axis("off")
    ax.text(0.35, 4.3, "What did we learn?", fontsize=20, fontweight="bold", color=INK)
    ax.text(
        0.35,
        3.92,
        "Adapting GENCO to a real UK distribution network, one failure mode at a time "
        "(frozen results, same 2,829 real 2024 states)",
        fontsize=11,
        color=INK_2,
    )
    w, gap, x0, y0, h = 2.62, 0.25, 0.35, 0.65, 2.95
    for i, (row, name, code, added, showed, col) in enumerate(STAGES):
        x = x0 + i * (w + gap)
        r = t.loc[row]
        ax.add_patch(
            FancyBboxPatch((x, y0), w, h, boxstyle="round,pad=0,rounding_size=0.12",
                           fc="white", ec=BORDER, lw=1.2)
        )  # fmt: skip
        ax.add_patch(plt.Rectangle((x, y0 + h - 0.09), w, 0.09, color=col, lw=0))
        ax.text(x + 0.15, y0 + h - 0.38, f"{i + 1}. {name}", fontsize=12.5, fontweight="bold",
                color=INK)  # fmt: skip
        ax.text(x + w - 0.15, y0 + h - 0.38, code, fontsize=9, color=MUTED, ha="right")
        ax.text(x + 0.15, y0 + h - 0.62, added, fontsize=9.5, color=MUTED, va="top")
        ax.text(x + 0.15, y0 + h - 1.32, showed, fontsize=11.5, fontweight="bold", color=INK,
                va="top")  # fmt: skip
        stats = [
            ("Real-state error", f"{r.PBE_mean:.2g} MVA"),
            (f"PV response (AC {ac_pv:+.2f})".replace("-", "−"), f"{r.genco_slope_pv:+.2f}"),
            ("Import bias", f"{r.import_bias_mw:+.0f} MW"),
        ]
        stats = [(a, b.replace("-", "−")) for a, b in stats]
        for k, (lab, val) in enumerate(stats):
            yy = y0 + 0.95 - k * 0.31
            ax.plot([x + 0.15, x + w - 0.15], [yy + 0.2, yy + 0.2], color=BORDER, lw=0.8)
            ax.text(x + 0.15, yy, lab, fontsize=9, color=INK_2)
            ax.text(x + w - 0.15, yy, val, fontsize=10, color=INK, ha="right", fontweight="bold")
        if i < len(STAGES) - 1:
            ax.annotate("", xy=(x + w + gap - 0.03, y0 + h / 2), xytext=(x + w + 0.03, y0 + h / 2),
                        arrowprops=dict(arrowstyle="-|>", color=MUTED, lw=1.2))  # fmt: skip
    ax.text(
        0.35,
        0.25,
        "No stage passes the full pre-registered real-transfer gate, so the weather question "
        "remains unresolved.  E5's PV slope comes with import r 0.11: not a usable response.",
        fontsize=9.5,
        color=MUTED,
    )
    out = REPO_ROOT / "reports/figures/c2g_what_we_learned.png"
    fig.savefig(out, dpi=150, facecolor="white")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
