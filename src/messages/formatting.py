"""Small helpers shared by the text report and the team message."""
from __future__ import annotations

from datetime import datetime


def clock(iso_value: str | None) -> str:
    """'2026-09-22T15:42' -> '15:42' (or '22 Sep 15:42' for multi-day periods)."""
    if not iso_value:
        return "-"
    return datetime.fromisoformat(iso_value).strftime("%H:%M")


def day_clock(iso_value: str | None) -> str:
    if not iso_value:
        return "-"
    return datetime.fromisoformat(iso_value).strftime("%d %b %H:%M")


def minutes_text(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest} min" if rest else f"{hours} h"


def period_title(label: str) -> str:
    return label.replace("_to_", " to ")
