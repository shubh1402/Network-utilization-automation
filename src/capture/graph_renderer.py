"""Draw per-site utilization graphs straight from the collected data.

This is the default (GRAPH_MODE=render). It needs no browser and no Zabbix web
login, and the graph always matches the numbers in the report exactly.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from src.config import THRESHOLDS  # noqa: E402

LINK_COLORS = {"Primary": "#1F7A99", "Secondary": "#7A5CC7"}
THRESHOLD_COLORS = {90: "#D13438", 80: "#E8742C", 70: "#C9A227"}


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")


def render_site_graph(
    site: str,
    series: dict[str, list[float | None]],
    start: datetime,
    step_minutes: int,
    out_dir: Path,
    title_suffix: str = "",
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 3.4), dpi=110)
    for link_type, values in series.items():
        times = [start + timedelta(minutes=i * step_minutes) for i in range(len(values))]
        ys = [v if v is not None else float("nan") for v in values]
        ax.plot(times, ys, color=LINK_COLORS.get(link_type, "#444"), linewidth=1.3, label=link_type)
    for threshold in THRESHOLDS:
        ax.axhline(threshold, color=THRESHOLD_COLORS[threshold], linewidth=0.8, linestyle=(0, (4, 3)))
        ax.text(1.002, threshold, f"{threshold}%", transform=ax.get_yaxis_transform(),
                va="center", fontsize=8, color=THRESHOLD_COLORS[threshold])
    ax.set_ylim(0, 102)
    ax.set_ylabel("Utilization %")
    span_days = len(next(iter(series.values()))) * step_minutes / 1440 if series else 1
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M" if span_days <= 1.01 else "%d %b"))
    ax.grid(axis="y", color="#E3E7EA", linewidth=0.7)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.set_title(f"{site}: link utilization {title_suffix}".strip(), loc="left", fontsize=11, fontweight="bold")
    ax.legend(loc="upper left", frameon=False, ncol=2, fontsize=9)
    fig.tight_layout()
    path = out_dir / f"{safe_name(site)}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def render_all_graphs(
    series_by_site: dict[str, dict[str, list[float | None]]],
    start: datetime,
    step_minutes: int,
    out_dir: Path,
    title_suffix: str = "",
) -> list[dict]:
    """Same result shape as the Selenium capture: one dict per graph."""
    results = []
    for site, series in series_by_site.items():
        try:
            path = render_site_graph(site, series, start, step_minutes, Path(out_dir), title_suffix)
            results.append({"site": site, "link": "Primary + Secondary", "status": "SUCCESS", "path": str(path), "error": ""})
        except Exception as error:  # a broken graph must not stop the report
            results.append({"site": site, "link": "Primary + Secondary", "status": "FAILED", "path": "", "error": str(error)})
    return results
