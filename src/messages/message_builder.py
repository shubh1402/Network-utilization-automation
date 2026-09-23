"""Short message for the ops channel (Teams / email / WhatsApp)."""
from __future__ import annotations

from src.config import FORTIGATE_TRIGGER_THRESHOLD, THRESHOLDS
from src.messages.formatting import clock, day_clock, minutes_text, period_title
from src.services.utilization_service import STATUS_RANK, build_headline, link_status, site_status


def _link_line(link_type: str, link: dict, fmt) -> str:
    status = link_status(link)
    if status == "no-data":
        return f"  {link_type}: no data collected"
    if status == "normal":
        return f"  {link_type}: normal (peak {link['peak']:.1f}%)"
    counts = ", ".join(
        f">{t}%: {minutes_text(link[f'above_{t}_events'])}" for t in THRESHOLDS if link[f"above_{t}_events"]
    )
    return f"  {link_type}: peak {link['peak']:.1f}% at {fmt(link['peak_time'])} | {counts}"


def build_message(report_label: str, site_data: dict) -> str:
    fmt = day_clock if "_to_" in report_label else clock
    flagged = sorted(
        (s for s, links in site_data.items() if site_status(links) not in ("normal", "no-data")),
        key=lambda s: -STATUS_RANK[site_status(site_data[s])],
    )
    silent = [s for s, links in site_data.items() if site_status(links) == "no-data"]
    quiet = [s for s, links in site_data.items() if site_status(links) == "normal"]

    lines = [
        f"Network utilization update: {period_title(report_label)}",
        "",
        build_headline(site_data),
        f"Sites above {FORTIGATE_TRIGGER_THRESHOLD}%: {len(flagged)} of {len(site_data)}",
    ]
    for site in flagged:
        lines += ["", site]
        lines += [_link_line(lt, link, fmt) for lt, link in site_data[site].items()]
    if quiet:
        lines += ["", f"Below {FORTIGATE_TRIGGER_THRESHOLD}% all period: {', '.join(quiet)}"]
    if silent:
        lines += [f"No data received: {', '.join(silent)}"]
    if flagged:
        lines += ["", "FortiGate top-talker captures and graphs are attached in the Excel report."]
    return "\n".join(lines) + "\n"
