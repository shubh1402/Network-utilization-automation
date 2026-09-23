"""Parse Zabbix history exports (the "Latest data -> History -> As plain text" format).

A data line looks like:
    2026-03-17 10:15:00 AM 1773722700 45.2 "Primary link utilization inbound"
The site comes from the file name ("Pune_Primary.txt", "pune - secondary link.txt"),
the link and direction from the quoted item label.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from src.config import LINK_TYPES, SITE_ORDER
from src.models.utilization_record import UtilizationRecord
from src.services.utilization_service import ChannelMaps, add_to_channel, merge_channel_maps

RAW_LINE_PATTERN = re.compile(
    r"""
    ^
    (?P<date>\d{4}-\d{2}-\d{2})
    \s+
    (?P<time>\d{1,2}:\d{2}:\d{2})
    (?:\s+(?P<meridian>AM|PM|am|pm))?
    \s+
    \d+
    \s+
    (?P<value>-?\d+(?:\.\d+)?)
    \s+
    "(?P<label>[^"]+)"
    $
    """,
    re.VERBOSE,
)
HEADER_PATTERN = re.compile(r"^[^\"]+:\s*\d+\s+items?$", re.IGNORECASE)
MAX_UNMATCHED_SAMPLES = 5


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def detect_site_from_filename(file_name: str, known_sites: list[str] | None = None) -> str:
    stem = _normalise(Path(file_name).stem)
    # Longest name first so "New York" wins over "York".
    for site in sorted(known_sites or SITE_ORDER, key=len, reverse=True):
        if _normalise(site) and _normalise(site) in stem:
            return site
    return "Unknown"


def detect_link_from_filename(file_name: str) -> str:
    stem = Path(file_name).stem.lower()
    for link_type in LINK_TYPES:
        if link_type.lower() in stem:
            return link_type
    return "Unknown"


def detect_link_and_direction(label: str) -> tuple[str | None, str | None]:
    normalized = label.lower()
    link = next((lt for lt in LINK_TYPES if lt.lower() in normalized), None)
    if "inbound" in normalized or re.search(r"\bin\b", normalized):
        direction = "Inbound"
    elif "outbound" in normalized or re.search(r"\bout\b", normalized):
        direction = "Outbound"
    else:
        direction = None
    return link, direction


def parse_line(raw_line: str) -> tuple[datetime, float, str] | None:
    match = RAW_LINE_PATTERN.match(raw_line)
    if not match:
        return None
    meridian = match.group("meridian")
    if meridian:
        stamp = datetime.strptime(
            f"{match.group('date')} {match.group('time')} {meridian.upper()}", "%Y-%m-%d %I:%M:%S %p"
        )
    else:
        stamp = datetime.strptime(f"{match.group('date')} {match.group('time')}", "%Y-%m-%d %H:%M:%S")
    return stamp, float(match.group("value")), match.group("label")


def parse_log_file(file_path: Path, channel_maps: ChannelMaps, known_sites: list[str] | None = None) -> dict:
    """Parse one export into `channel_maps` and return its line statistics."""
    summary = {
        "file_name": file_path.name,
        "site": detect_site_from_filename(file_path.name, known_sites),
        "link": detect_link_from_filename(file_path.name),
        "total_lines": 0,
        "matched_lines": 0,
        "unmatched_lines": 0,
        "blank_lines": 0,
        "ignored_header_lines": 0,
        "duplicate_lines": 0,
        "value_count": 0,
        "max_value": None,
        "links_seen": [],
        "sample_unmatched_lines": [],
    }
    seen_lines: set[str] = set()
    links_seen: set[str] = set()

    with file_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            summary["total_lines"] += 1
            raw_line = line.strip()
            if not raw_line:
                summary["blank_lines"] += 1
                continue
            if HEADER_PATTERN.match(raw_line):
                summary["ignored_header_lines"] += 1
                continue
            if raw_line in seen_lines:
                summary["duplicate_lines"] += 1
                continue
            seen_lines.add(raw_line)

            parsed = parse_line(raw_line)
            link, direction = detect_link_and_direction(parsed[2]) if parsed else (None, None)
            link = link or (summary["link"] if summary["link"] != "Unknown" else None)
            if parsed is None or link is None or direction is None:
                summary["unmatched_lines"] += 1
                if len(summary["sample_unmatched_lines"]) < MAX_UNMATCHED_SAMPLES:
                    summary["sample_unmatched_lines"].append(raw_line[:160])
                continue

            stamp, value, _ = parsed
            summary["matched_lines"] += 1
            summary["value_count"] += 1
            summary["max_value"] = value if summary["max_value"] is None else max(summary["max_value"], value)
            links_seen.add(link)
            add_to_channel(channel_maps, link, direction, stamp, value)

    summary["links_seen"] = sorted(links_seen)
    if summary["link"] == "Unknown" and len(links_seen) == 1:
        summary["link"] = next(iter(links_seen))
    return summary


def fetch_txt_records(
    logs_dir: Path,
    known_sites: list[str] | None = None,
) -> tuple[list[UtilizationRecord], list[dict]]:
    """Parse every *.txt in `logs_dir`. Files for the same site are merged together,
    so inbound and outbound can live in separate exports."""
    logs_dir = Path(logs_dir)
    files = sorted(p for p in logs_dir.glob("*.txt") if p.is_file())

    site_channels: dict[str, ChannelMaps] = {}
    file_summaries: list[dict] = []
    for file_path in files:
        summary = parse_log_file(file_path, site_channels.setdefault(
            detect_site_from_filename(file_path.name, known_sites), {}), known_sites)
        file_summaries.append(summary)

    records: list[UtilizationRecord] = []
    for site, channel_maps in site_channels.items():
        if site == "Unknown":
            continue
        sources = ", ".join(s["file_name"] for s in file_summaries if s["site"] == site)
        records.extend(merge_channel_maps(site, channel_maps, source_file=sources))
    return records, file_summaries


def write_zabbix_export(path: Path, site: str, rows: list[tuple[datetime, float, str]]) -> None:
    """Write rows in the Zabbix plain-text export format (used for samples and tests)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"{site}: {len(rows)} items\n")
        for stamp, value, label in rows:
            clock = int(stamp.timestamp())
            handle.write(f'{stamp.strftime("%Y-%m-%d %I:%M:%S %p")} {clock} {value:.2f} "{label}"\n')
