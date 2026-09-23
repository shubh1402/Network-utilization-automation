from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from src.config import SITES_BY_NAME
from src.services.utilization_service import summarize_records
from src.sources.demo_source import fetch_demo_records_with_stats, simulate_site_day
from src.sources.txt_source import (
    detect_site_from_filename,
    fetch_txt_records,
    parse_log_file,
    write_zabbix_export,
)

DAY = date(2026, 9, 22)
END_OF_TIME = datetime(2100, 1, 1)


def test_demo_is_deterministic_and_bounded():
    a, _ = fetch_demo_records_with_stats(DAY, DAY, now=END_OF_TIME)
    b, _ = fetch_demo_records_with_stats(DAY, DAY, now=END_OF_TIME)
    assert a == b
    assert all(0 <= r.value <= 100 for r in a)


def test_demo_respects_now_for_partial_days():
    now = datetime(2026, 9, 22, 12, 0)
    records, _ = fetch_demo_records_with_stats(DAY, DAY, now=now)
    assert max(r.timestamp for r in records) < now


def test_filename_detection():
    assert detect_site_from_filename("pune_primary.txt") == "Pune"
    assert detect_site_from_filename("FRANKFURT - Secondary link.txt") == "Frankfurt"
    assert detect_site_from_filename("mystery.txt") == "Unknown"


def test_parser_counts_every_kind_of_line(tmp_path: Path):
    path = tmp_path / "Pune_Primary.txt"
    path.write_text(
        "Pune: 4 items\n"
        "\n"
        '2026-09-22 10:15:00 AM 1790000000 45.20 "Primary link utilization inbound"\n'
        '2026-09-22 10:15:00 AM 1790000000 45.20 "Primary link utilization inbound"\n'
        '2026-09-22 22:15:30 1790000000 71.5 "Primary link utilization outbound"\n'
        "garbage line\n",
        encoding="utf-8",
    )
    maps = {}
    summary = parse_log_file(path, maps)
    assert summary["site"] == "Pune" and summary["link"] == "Primary"
    assert summary["ignored_header_lines"] == 1
    assert summary["blank_lines"] == 1
    assert summary["duplicate_lines"] == 1
    assert summary["matched_lines"] == 2
    assert summary["unmatched_lines"] == 1
    assert maps[("Primary", "Outbound")] == {datetime(2026, 9, 22, 22, 15): 71.5}


def test_txt_export_round_trip_matches_demo_numbers(tmp_path: Path):
    """Export demo data in Zabbix's text format, parse it back, get identical counts."""
    site = SITES_BY_NAME["Hyderabad"]
    start = datetime.combine(DAY, datetime.min.time())
    for (link, direction), values in simulate_site_day(site, DAY).items():
        rows = [
            (start + timedelta(minutes=i), float(v), f"{link} link utilization {direction.lower()}")
            for i, v in enumerate(values) if not np.isnan(v)
        ]
        write_zabbix_export(tmp_path / f"Hyderabad_{link}_{direction}.txt", "Hyderabad", rows)

    txt_records, summaries = fetch_txt_records(tmp_path)
    demo_records, _ = fetch_demo_records_with_stats(DAY, DAY, now=END_OF_TIME, sites=[site])
    assert len(summaries) == 4
    assert summarize_records(txt_records) == summarize_records(demo_records)
