"""Turns per-minute utilization records into the numbers the report needs.

Rules (kept identical to the original production logic):
  * inbound and outbound are merged per minute by taking the max, because a
    link is congested if *either* direction is saturated;
  * a threshold event is one minute strictly above the threshold;
  * counts are cumulative (a 93% minute counts for >90, >80 and >70).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import fmean

from src.config import FORTIGATE_TRIGGER_THRESHOLD, LINK_TYPES, SITE_ORDER, THRESHOLDS
from src.models.utilization_record import UtilizationRecord

# {(link_type, direction): {minute_timestamp: value}}
ChannelMaps = dict[tuple[str, str], dict[datetime, float]]

STATUS_BY_THRESHOLD = {90: "critical", 80: "high", 70: "elevated"}
STATUS_RANK = {"no-data": -1, "normal": 0, "elevated": 1, "high": 2, "critical": 3}


def floor_minute(value: datetime) -> datetime:
    return value.replace(second=0, microsecond=0)


def add_to_channel(channel_maps: ChannelMaps, link_type: str, direction: str, when: datetime, value: float) -> bool:
    """Insert one sample, keeping the max if the minute already has one.

    Returns True when the minute was already present (a duplicate sample).
    """
    minute = floor_minute(when)
    bucket = channel_maps.setdefault((link_type, direction), {})
    if minute in bucket:
        bucket[minute] = max(bucket[minute], value)
        return True
    bucket[minute] = value
    return False


def merge_channel_maps(
    site: str,
    channel_maps: ChannelMaps,
    source_file: str | None = None,
) -> list[UtilizationRecord]:
    """Merge inbound/outbound into one record per minute per link."""
    records: list[UtilizationRecord] = []
    for link_type in LINK_TYPES:
        inbound = channel_maps.get((link_type, "Inbound"), {})
        outbound = channel_maps.get((link_type, "Outbound"), {})
        for minute in sorted(inbound.keys() | outbound.keys()):
            value = max(inbound.get(minute, 0.0), outbound.get(minute, 0.0))
            records.append(
                UtilizationRecord(
                    site=site,
                    link_type=link_type,
                    timestamp=minute,
                    value=round(float(value), 2),
                    source_file=source_file,
                )
            )
    return records


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    index = (len(sorted_values) - 1) * pct / 100
    low = int(index)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (index - low)


EPISODE_MERGE_GAP_MINUTES = 5


def find_episodes(
    points: list[tuple[datetime, float]],
    threshold: float = FORTIGATE_TRIGGER_THRESHOLD,
    merge_gap: int = EPISODE_MERGE_GAP_MINUTES,
) -> list[dict]:
    """Congestion periods: minutes above `threshold`, where breaches separated by
    a dip (or missing samples) of `merge_gap` minutes or less count as one period.

    `minutes` counts only minutes actually above the threshold, so the sum over
    all episodes always equals the link's `above_70_events`.
    """
    episodes: list[dict] = []
    current: dict | None = None
    gap = timedelta(minutes=merge_gap + 1)

    for when, value in points:
        if value <= threshold:
            continue
        if current is not None and when - current["end"] <= gap:
            current["end"] = when
            current["minutes"] += 1
            if value > current["peak"]:
                current["peak"], current["peak_time"] = value, when
        else:
            if current is not None:
                episodes.append(current)
            current = {"start": when, "end": when, "minutes": 1, "peak": value, "peak_time": when}

    if current is not None:
        episodes.append(current)

    for episode in episodes:
        episode["duration"] = int((episode["end"] - episode["start"]).total_seconds() // 60) + 1
        episode["level"] = next((t for t in THRESHOLDS if episode["peak"] > t), threshold)
        for key in ("start", "end", "peak_time"):
            episode[key] = episode[key].isoformat(timespec="minutes")
        episode["peak"] = round(episode["peak"], 2)
    return episodes


def empty_link_summary() -> dict:
    summary = {f"above_{t}_events": 0 for t in THRESHOLDS}
    summary.update(
        {
            "total_base_events": 0,
            "peak": 0.0,
            "peak_time": None,
            "average": 0.0,
            "p95": 0.0,
            "first_timestamp": None,
            "last_timestamp": None,
            "episodes": [],
            "status": "no-data",
        }
    )
    return summary


def link_status(link: dict) -> str:
    if link.get("total_base_events", 0) == 0:
        return "no-data"
    for threshold in THRESHOLDS:
        if link.get(f"above_{threshold}_events", 0) > 0:
            return STATUS_BY_THRESHOLD[threshold]
    return "normal"


def site_status(links: dict) -> str:
    statuses = [link_status(link) for link in links.values()] or ["no-data"]
    return max(statuses, key=lambda s: STATUS_RANK[s])


def summarize_records(records: list[UtilizationRecord]) -> dict[str, dict[str, dict]]:
    """{site: {link_type: summary}} with threshold counts and basic statistics."""
    grouped: dict[str, dict[str, list[tuple[datetime, float]]]] = defaultdict(lambda: defaultdict(list))
    for record in records:
        grouped[record.site][record.link_type].append((record.timestamp, record.value))

    site_data: dict[str, dict[str, dict]] = {}
    for site, links in grouped.items():
        site_data[site] = {}
        for link_type in LINK_TYPES:
            points = sorted(links.get(link_type, []))
            summary = empty_link_summary()
            if points:
                values = [value for _, value in points]
                ordered = sorted(values)
                peak_time, peak = max(points, key=lambda p: (p[1], -p[0].timestamp()))
                summary.update(
                    {
                        "total_base_events": len(points),
                        "peak": round(peak, 2),
                        "peak_time": peak_time.isoformat(timespec="minutes"),
                        "average": round(fmean(values), 2),
                        "p95": round(_percentile(ordered, 95), 2),
                        "first_timestamp": points[0][0].isoformat(timespec="minutes"),
                        "last_timestamp": points[-1][0].isoformat(timespec="minutes"),
                        "episodes": find_episodes(points),
                    }
                )
                for threshold in THRESHOLDS:
                    summary[f"above_{threshold}_events"] = sum(1 for v in values if v > threshold)
            summary["status"] = link_status(summary)
            site_data[site][link_type] = summary
    return site_data


def sort_site_data(site_data: dict, site_order: list[str] | None = None) -> dict:
    """Order sites as configured and add configured sites that returned no data,
    so a silent site shows up as 'no data' instead of disappearing."""
    order = site_order if site_order is not None else SITE_ORDER
    ordered: dict[str, dict] = {}
    for site in order:
        ordered[site] = site_data.get(site) or {link: empty_link_summary() for link in LINK_TYPES}
    for site in sorted(set(site_data) - set(order)):
        ordered[site] = site_data[site]
    return ordered


def get_sites_above_70(site_data: dict) -> list[str]:
    """Sites where any link crossed the FortiGate trigger threshold."""
    key = f"above_{FORTIGATE_TRIGGER_THRESHOLD}_events"
    return [
        site
        for site, links in site_data.items()
        if any(link.get(key, 0) > 0 for link in links.values())
    ]


def build_series(
    records: list[UtilizationRecord],
    start: datetime,
    end: datetime,
    step_minutes: int = 5,
) -> dict[str, dict[str, list[float | None]]]:
    """Max value per `step_minutes` bucket from start to end, None where no data.

    Used for charts; the report numbers always come from the per-minute data.
    """
    step = timedelta(minutes=step_minutes)
    buckets = max(1, int((end - start) / step))
    series: dict[str, dict[str, list[float | None]]] = defaultdict(
        lambda: {link: [None] * buckets for link in LINK_TYPES}
    )
    for record in records:
        index = int((record.timestamp - start) / step)
        if 0 <= index < buckets:
            row = series[record.site][record.link_type]
            if row[index] is None or record.value > row[index]:
                row[index] = record.value
    return dict(series)


def worst_link(site_data: dict) -> tuple[str, str, dict] | None:
    """The single most important finding: highest status, then longest, then peak."""
    candidates = []
    for site, links in site_data.items():
        for link_type, link in links.items():
            status = link_status(link)
            if status in ("normal", "no-data"):
                continue
            threshold = next(t for t, s in STATUS_BY_THRESHOLD.items() if s == status)
            minutes = link.get(f"above_{threshold}_events", 0)
            candidates.append(((STATUS_RANK[status], minutes, link.get("peak", 0)), site, link_type, link))
    if not candidates:
        return None
    _, site, link_type, link = max(candidates, key=lambda c: c[0])
    return site, link_type, link


def build_headline(site_data: dict) -> str:
    """One plain-language sentence that leads the report and the dashboard."""
    finding = worst_link(site_data)
    reporting = [s for s, links in site_data.items() if site_status(links) != "no-data"]
    if finding is None:
        if not reporting:
            return "No utilization data was collected for this period."
        return f"All {len(reporting)} reporting sites stayed below {FORTIGATE_TRIGGER_THRESHOLD}% utilization."
    site, link_type, link = finding
    status = link_status(link)
    threshold = next(t for t, s in STATUS_BY_THRESHOLD.items() if s == status)
    return (
        f"{site}'s {link_type.lower()} link ran above {threshold}% for "
        f"{duration_text(link[f'above_{threshold}_events'])}, peaking at {link['peak']:.1f}%."
    )


def duration_text(minutes: int) -> str:
    """19 -> '19 minutes', 152 -> '2 h 32 min'."""
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest} min" if rest else f"{hours} h"
