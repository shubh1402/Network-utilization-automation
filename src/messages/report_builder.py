"""Detailed plain-text report (archived next to the Excel workbook)."""
from __future__ import annotations

from src.config import THRESHOLDS
from src.messages.formatting import clock, day_clock, minutes_text, period_title
from src.services.utilization_service import build_headline, site_status

RULE = "=" * 78


def build_summary(
    report_label: str,
    site_data: dict,
    file_count: int = 0,
    data_source: str = "",
    checks: list[dict] | None = None,
    multi_day: bool = False,
) -> str:
    fmt = day_clock if multi_day or "_to_" in report_label else clock
    lines = [
        RULE,
        f"NETWORK UTILIZATION REPORT | {period_title(report_label)}",
        RULE,
        build_headline(site_data),
        "",
    ]
    if data_source:
        lines.append(f"Data source : {data_source}")
    if file_count:
        lines.append(f"Files read  : {file_count}")
    lines.append(f"Sites       : {len(site_data)}")
    lines.append("")

    header = f"{'Site':<14}{'Link':<11}{'Peak %':>8}{'At':>13}{'Avg %':>8}{'P95 %':>8}" + "".join(
        f"{'>' + str(t) + '%':>8}" for t in THRESHOLDS
    ) + f"{'Samples':>9}  Status"
    lines += [header, "-" * len(header)]
    for site, links in site_data.items():
        for link_type, link in links.items():
            lines.append(
                f"{site:<14}{link_type:<11}{link['peak']:>8.1f}{fmt(link['peak_time']):>13}"
                f"{link['average']:>8.1f}{link['p95']:>8.1f}"
                + "".join(f"{link[f'above_{t}_events']:>8}" for t in THRESHOLDS)
                + f"{link['total_base_events']:>9}  {link['status']}"
            )
    lines.append("")

    lines.append("Breach episodes above 70%")
    lines.append("-" * 25)
    any_episode = False
    for site, links in site_data.items():
        for link_type, link in links.items():
            for ep in link.get("episodes", []):
                any_episode = True
                lines.append(
                    f"  {site} {link_type}: {fmt(ep['start'])}-{clock(ep['end'])} "
                    f"({minutes_text(ep['minutes'])} above 70% in {minutes_text(ep['duration'])}), "
                    f"peak {ep['peak']:.1f}% at {clock(ep['peak_time'])}"
                )
    if not any_episode:
        lines.append("  None")
    lines.append("")

    quiet = [s for s, links in site_data.items() if site_status(links) == "normal"]
    if quiet:
        lines.append(f"Sites below 70% all period: {', '.join(quiet)}")

    if checks:
        lines += ["", "Accuracy checks", "-" * 15]
        for check in checks:
            mark = "PASS" if check["passed"] else ("WARN" if check["severity"] == "warning" else "FAIL")
            lines.append(f"  [{mark}] {check['name']}: {check['detail']}")

    lines.append(RULE)
    return "\n".join(lines) + "\n"
