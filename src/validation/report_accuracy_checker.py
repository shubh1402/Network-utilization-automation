"""Sanity checks on the summarised numbers before anything is sent to anyone."""
from __future__ import annotations

from src.config import MIN_COVERAGE, SITE_ORDER, THRESHOLDS
from src.validation.checks import CheckResult, failures


def evaluate_report(site_data: dict, expected_minutes: int | None = None) -> list[CheckResult]:
    results: list[CheckResult] = []

    # 1. Every configured site returned data.
    silent = [s for s in SITE_ORDER if sum(lk.get("total_base_events", 0) for lk in site_data.get(s, {}).values()) == 0]
    results.append(CheckResult(
        "All sites reporting",
        not silent,
        "Every configured site returned data." if not silent else f"No data for: {', '.join(silent)}.",
    ))

    # 2. Cumulative threshold counts are ordered: >90 <= >80 <= >70 <= total.
    broken = []
    for site, links in site_data.items():
        for link_type, link in links.items():
            counts = [link.get(f"above_{t}_events", 0) for t in THRESHOLDS] + [link.get("total_base_events", 0)]
            if counts != sorted(counts):
                broken.append(f"{site} {link_type} {counts}")
    results.append(CheckResult(
        "Threshold counts consistent",
        not broken,
        "Counts above 90/80/70% nest correctly." if not broken else "Out of order: " + "; ".join(broken),
    ))

    # 3. Values are valid percentages and statistics agree with each other.
    invalid = []
    for site, links in site_data.items():
        for link_type, link in links.items():
            if link.get("total_base_events", 0) == 0:
                continue
            peak, avg, p95 = link.get("peak", 0), link.get("average", 0), link.get("p95", 0)
            if not (0 <= avg <= p95 <= peak <= 100):
                invalid.append(f"{site} {link_type} (avg {avg}, p95 {p95}, peak {peak})")
    results.append(CheckResult(
        "Values within 0-100%",
        not invalid,
        "All averages, P95s and peaks are valid percentages." if not invalid else "Invalid: " + "; ".join(invalid),
    ))

    # 4. Enough samples to trust the counts (a gap can hide a breach).
    if expected_minutes:
        gaps = []
        for site, links in site_data.items():
            for link_type, link in links.items():
                total = link.get("total_base_events", 0)
                if total and total / expected_minutes < MIN_COVERAGE:
                    missing = expected_minutes - total
                    gaps.append(f"{site} {link_type} missing {missing} of {expected_minutes} minutes")
        results.append(CheckResult(
            "Sample coverage",
            not gaps,
            f"Every link has at least {MIN_COVERAGE:.0%} of expected samples." if not gaps else "; ".join(gaps) + ".",
            severity="warning",
        ))

    # 5. Every breach minute belongs to an episode (episode detection is complete).
    unaccounted = []
    for site, links in site_data.items():
        for link_type, link in links.items():
            in_episodes = sum(e["minutes"] for e in link.get("episodes", []))
            if in_episodes != link.get("above_70_events", 0):
                unaccounted.append(f"{site} {link_type} ({in_episodes} vs {link.get('above_70_events', 0)})")
    results.append(CheckResult(
        "Breach episodes reconcile",
        not unaccounted,
        "Minutes above 70% match the listed episodes." if not unaccounted else "Mismatch: " + "; ".join(unaccounted),
    ))
    return results


def run_report_accuracy_checks(site_data: dict, expected_minutes: int | None = None) -> list[str]:
    """Original interface: a list of human-readable problems (empty = all good)."""
    return failures(evaluate_report(site_data, expected_minutes))
