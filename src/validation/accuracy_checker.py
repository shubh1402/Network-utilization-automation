"""Cross-checks between the raw TXT exports and the summarised numbers (TXT mode only)."""
from __future__ import annotations

from collections import defaultdict

from src.validation.checks import CheckResult, failures

MAX_UNMATCHED_RATIO = 0.01


def evaluate_txt(file_summaries: list[dict], site_data: dict) -> list[CheckResult]:
    results: list[CheckResult] = []

    unknown = [f["file_name"] for f in file_summaries if f["site"] == "Unknown"]
    results.append(CheckResult(
        "Files mapped to sites",
        not unknown,
        "Every file name matches a configured site." if not unknown else f"Unknown site in: {', '.join(unknown)}.",
    ))

    empty = [f["file_name"] for f in file_summaries if f["value_count"] == 0]
    results.append(CheckResult(
        "Files contain data",
        not empty,
        "Every file has utilization values." if not empty else f"No values in: {', '.join(empty)}.",
    ))

    noisy = []
    for f in file_summaries:
        parsed = f["matched_lines"] + f["unmatched_lines"]
        if parsed and f["unmatched_lines"] / parsed > MAX_UNMATCHED_RATIO:
            noisy.append(f"{f['file_name']} ({f['unmatched_lines']} of {parsed} lines)")
    results.append(CheckResult(
        "Lines parsed",
        not noisy,
        f"Fewer than {MAX_UNMATCHED_RATIO:.0%} unreadable lines per file." if not noisy else "Unreadable lines: " + "; ".join(noisy),
        severity="warning",
    ))

    # Peak in the report must equal the highest raw value seen for that site/link,
    # and the merged minute count can't exceed the number of raw values.
    raw_peak: dict[tuple[str, str], float] = {}
    raw_values: dict[tuple[str, str], int] = defaultdict(int)
    for f in file_summaries:
        for link in f.get("links_seen", []):
            key = (f["site"], link)
            if f["max_value"] is not None:
                raw_peak[key] = max(raw_peak.get(key, 0.0), f["max_value"])
            raw_values[key] += f["value_count"]

    mismatches = []
    for (site, link), peak in raw_peak.items():
        summary = site_data.get(site, {}).get(link)
        if summary is None:
            mismatches.append(f"{site} {link} missing from report")
            continue
        if abs(summary["peak"] - round(peak, 2)) > 0.01:
            mismatches.append(f"{site} {link} peak {summary['peak']} vs raw {peak}")
        if summary["total_base_events"] > raw_values[(site, link)]:
            mismatches.append(f"{site} {link} more minutes than raw values")
    results.append(CheckResult(
        "Report matches raw files",
        not mismatches,
        "Peaks and sample counts agree with the raw exports." if not mismatches else "; ".join(mismatches),
    ))
    return results


def run_accuracy_checks(file_summaries: list[dict], site_data: dict) -> list[str]:
    """Original interface: a list of human-readable problems (empty = all good)."""
    return failures(evaluate_txt(file_summaries, site_data))
