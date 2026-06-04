from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from src.config import ZABBIX_API_TOKEN, ZABBIX_API_URL, ZABBIX_VERIFY_SSL
from src.clients.zabbix_client import ZabbixClient
from src.sources.zabbix_source import fetch_site_records_with_stats
from src.services.utilization_service import summarize_records
from src.models.utilization_record import UtilizationRecord


RAW_LINE_PATTERN = re.compile(
    r"""
    ^
    (?P<date>\d{4}-\d{2}-\d{2})
    \s+
    (?P<time>\d{2}:\d{2}:\d{2})
    \s+
    (?P<meridian>AM|PM|am|pm)
    \s+
    \d+
    \s+
    (?P<value>\d+(?:\.\d+)?)
    \s+
    "(?P<label>[^"]+)"
    $
    """,
    re.VERBOSE,
)


def ask_file_path() -> Path:
    raw = input("Enter raw TXT log file path: ").strip().strip('"')
    if not raw:
        raise ValueError("No file path entered.")

    file_path = Path(raw)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    return file_path


def ask_site_name() -> str:
    site = input("Enter site name exactly (example: Chennai): ").strip()
    if not site:
        raise ValueError("Site name is required.")
    return site


def ask_report_date() -> str:
    report_date = input("Enter report date in DD-MM-YYYY format (example: 17-03-2026): ").strip()
    if not report_date:
        raise ValueError("Report date is required.")
    return report_date


def detect_link_and_direction(label: str) -> tuple[str | None, str | None]:
    normalized = label.lower()

    if "primary link utilization inbound" in normalized:
        return "Primary", "Inbound"
    if "primary link utilization outbound" in normalized:
        return "Primary", "Outbound"
    if "secondary link utilization inbound" in normalized:
        return "Secondary", "Inbound"
    if "secondary link utilization outbound" in normalized:
        return "Secondary", "Outbound"

    return None, None


def parse_raw_txt_to_channel_maps(
    file_path: Path,
) -> dict[tuple[str, str], dict[int, float]]:
    """
    Returns:
        {
            ("Primary", "Inbound"): {minute_clock: value, ...},
            ("Primary", "Outbound"): {...},
            ("Secondary", "Inbound"): {...},
            ("Secondary", "Outbound"): {...},
        }
    """
    channel_maps: dict[tuple[str, str], dict[int, float]] = defaultdict(dict)

    with file_path.open("r", encoding="utf-8", errors="replace") as file:
        for line_number, line in enumerate(file, start=1):
            raw_line = line.strip()
            if not raw_line:
                continue

            if raw_line.endswith(" items") and ":" in raw_line and '"' not in raw_line:
                continue

            match = RAW_LINE_PATTERN.match(raw_line)
            if not match:
                continue

            label = match.group("label")
            link_type, direction = detect_link_and_direction(label)
            if not link_type or not direction:
                continue

            dt_str = (
                f"{match.group('date')} "
                f"{match.group('time')} "
                f"{match.group('meridian').upper()}"
            )
            timestamp = datetime.strptime(dt_str, "%Y-%m-%d %I:%M:%S %p")
            value = float(match.group("value"))

            minute_clock = int(timestamp.timestamp()) - (int(timestamp.timestamp()) % 60)

            key = (link_type, direction)
            if minute_clock in channel_maps[key]:
                channel_maps[key][minute_clock] = max(channel_maps[key][minute_clock], value)
            else:
                channel_maps[key][minute_clock] = value

    return channel_maps


def merge_channel_maps_to_records(
    site_name: str,
    channel_maps: dict[tuple[str, str], dict[int, float]],
) -> list[UtilizationRecord]:
    records: list[UtilizationRecord] = []

    for link_type in ("Primary", "Secondary"):
        inbound_map = channel_maps.get((link_type, "Inbound"), {})
        outbound_map = channel_maps.get((link_type, "Outbound"), {})

        all_minutes = sorted(set(inbound_map.keys()) | set(outbound_map.keys()))

        for minute_clock in all_minutes:
            in_value = inbound_map.get(minute_clock, 0.0)
            out_value = outbound_map.get(minute_clock, 0.0)
            merged_value = max(in_value, out_value)

            records.append(
                UtilizationRecord(
                    site=site_name,
                    link_type=link_type,
                    timestamp=datetime.fromtimestamp(minute_clock),
                    value=merged_value,
                    source_file=None,
                )
            )

    return records


def build_summary_from_records(records: list[UtilizationRecord]) -> dict:
    site_data = summarize_records(records)
    return site_data


def extract_site_counts(site_data: dict, site_name: str) -> dict[str, dict[str, int]]:
    links = site_data.get(site_name, {})

    result: dict[str, dict[str, int]] = {}
    for link_type in ("Primary", "Secondary"):
        link_data = links.get(link_type, {})
        result[link_type] = {
            "above_90_events": int(link_data.get("above_90_events", 0)),
            "above_80_events": int(link_data.get("above_80_events", 0)),
            "above_70_events": int(link_data.get("above_70_events", 0)),
            "total_base_events": int(link_data.get("total_base_events", 0)),
        }

    return result


def fetch_zabbix_counts(site_name: str, report_date: str) -> dict[str, dict[str, int]]:
    if not ZABBIX_API_URL:
        raise RuntimeError("Missing ZABBIX_API_URL in .env")
    if not ZABBIX_API_TOKEN:
        raise RuntimeError("Missing ZABBIX_API_TOKEN in .env")

    client = ZabbixClient(
        ZABBIX_API_URL,
        ZABBIX_API_TOKEN,
        verify_ssl=ZABBIX_VERIFY_SSL,
    )

    records, stats = fetch_site_records_with_stats(client, site_name, report_date=report_date)

    print(
        f"\nZABBIX FETCH | {site_name} | "
        f"primary_merged={stats['primary_merged_rows']} | "
        f"secondary_merged={stats['secondary_merged_rows']} | "
        f"total_records={stats['total_records']}"
    )

    site_data = summarize_records(records)
    return extract_site_counts(site_data, site_name)


def compare_counts(
    txt_counts: dict[str, dict[str, int]],
    zabbix_counts: dict[str, dict[str, int]],
    site_name: str,
) -> None:
    print("\n" + "#" * 100)
    print(f"RAW TXT VS ZABBIX COMPARISON | SITE: {site_name}")
    print("#" * 100)

    for link_type in ("Primary", "Secondary"):
        print(f"\n{link_type} Utilization")

        txt_link = txt_counts.get(link_type, {})
        zbx_link = zabbix_counts.get(link_type, {})

        for label, key in (
            ("Above 90", "above_90_events"),
            ("Above 80", "above_80_events"),
            ("Above 70", "above_70_events"),
            ("Total Base Events", "total_base_events"),
        ):
            txt_value = int(txt_link.get(key, 0))
            zbx_value = int(zbx_link.get(key, 0))

            if txt_value == zbx_value:
                print(f"  MATCH    | {label:<16} | txt={txt_value} | zabbix={zbx_value}")
            else:
                print(f"  MISMATCH | {label:<16} | txt={txt_value} | zabbix={zbx_value}")


def print_counts(title: str, counts: dict[str, dict[str, int]]) -> None:
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)

    for link_type in ("Primary", "Secondary"):
        link = counts.get(link_type, {})
        print(f"\n{link_type} Utilization")
        print(f"Above 90 events : {link.get('above_90_events', 0)}")
        print(f"Above 80 events : {link.get('above_80_events', 0)}")
        print(f"Above 70 events : {link.get('above_70_events', 0)}")
        print(f"Total base events: {link.get('total_base_events', 0)}")


def main() -> None:
    txt_file = ask_file_path()
    site_name = ask_site_name()
    report_date = ask_report_date()

    channel_maps = parse_raw_txt_to_channel_maps(txt_file)
    txt_records = merge_channel_maps_to_records(site_name, channel_maps)
    txt_site_data = build_summary_from_records(txt_records)
    txt_counts = extract_site_counts(txt_site_data, site_name)

    zabbix_counts = fetch_zabbix_counts(site_name, report_date)

    print_counts("RAW TXT DERIVED COUNTS", txt_counts)
    print_counts("ZABBIX DERIVED COUNTS", zabbix_counts)

    compare_counts(txt_counts, zabbix_counts, site_name)


if __name__ == "__main__":
    main()