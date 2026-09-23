"""One merged utilization sample: a single minute on a single link."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class UtilizationRecord:
    site: str
    link_type: str          # "Primary" | "Secondary"
    timestamp: datetime     # naive, in REPORT_TIMEZONE, floored to the minute
    value: float            # utilization %, max(inbound, outbound) for that minute
    source_file: str | None = None
