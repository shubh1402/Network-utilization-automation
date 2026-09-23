"""Collect per-minute link utilization for every site from the Zabbix API."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.clients.zabbix_client import ZabbixAPIError, ZabbixClient
from src.config import LINK_TYPES, REPORT_TIMEZONE, SITES, SITES_BY_NAME, ZABBIX_ITEM_NAMES
from src.models.utilization_record import UtilizationRecord
from src.services.utilization_service import ChannelMaps, add_to_channel, merge_channel_maps
from src.utils.date_utils import build_report_period, parse_date, period_bounds

STAT_KEYS = (
    "primary_in_rows",
    "primary_out_rows",
    "secondary_in_rows",
    "secondary_out_rows",
    "primary_merged_rows",
    "secondary_merged_rows",
    "total_records",
)


def _channel_stat_key(link_type: str, direction: str) -> str:
    return f"{link_type.lower()}_{'in' if direction == 'Inbound' else 'out'}_rows"


def _to_epoch(local_naive: datetime) -> int:
    return int(local_naive.replace(tzinfo=ZoneInfo(REPORT_TIMEZONE)).timestamp())


def _from_epoch(clock: int) -> datetime:
    return datetime.fromtimestamp(clock, tz=ZoneInfo(REPORT_TIMEZONE)).replace(tzinfo=None)


def _to_percent(raw: float, units: str, capacity_mbps: float | None) -> float:
    """Items may report % directly or raw bits per second."""
    units = (units or "").strip().lower()
    if units in ("bps", "b/s", "bit/s"):
        if not capacity_mbps:
            raise ZabbixAPIError("Item reports bps but the site has no capacity_mbps configured")
        return raw / (capacity_mbps * 1_000_000) * 100
    return raw


def fetch_site_records_with_stats(
    client: ZabbixClient,
    site_name: str,
    report_date: str | date | None = None,
    from_date: str | date | None = None,
    to_date: str | date | None = None,
) -> tuple[list[UtilizationRecord], dict]:
    """Records + row statistics for one site.

    Pass either `report_date` (single day, as used by compare.py) or a
    `from_date`/`to_date` range.
    """
    if report_date is not None:
        day = parse_date(report_date)
        period = build_report_period("date", day, today=max(day, date.today()))
    else:
        period = build_report_period("range", from_date, to_date, today=max(parse_date(to_date), date.today()))
    start, end = period_bounds(period)

    site = SITES_BY_NAME.get(site_name, {"name": site_name, "zabbix_host": site_name, "capacity_mbps": {}})
    host_id = client.get_host_id(site["zabbix_host"])

    wanted = {name: key for key, name in ZABBIX_ITEM_NAMES.items()}
    items = client.get_items(host_id, list(wanted))
    item_meta: dict[str, dict] = {}
    for item in items:
        link_type, direction = wanted[item["name"]]
        item_meta[item["itemid"]] = {
            "link_type": link_type,
            "direction": direction,
            "units": item.get("units", ""),
            "value_type": int(item.get("value_type", 0)),
        }

    missing = sorted(set(wanted) - {i["name"] for i in items})
    stats = {key: 0 for key in STAT_KEYS}
    stats.update(
        {
            "site": site_name,
            "from_date": period["from_date"].isoformat(),
            "to_date": period["to_date"].isoformat(),
            "missing_items": missing,
        }
    )

    channel_maps: ChannelMaps = {}
    time_from, time_till = _to_epoch(start), _to_epoch(end) - 1
    for value_type in sorted({meta["value_type"] for meta in item_meta.values()}):
        ids = [item_id for item_id, meta in item_meta.items() if meta["value_type"] == value_type]
        for row in client.get_history(ids, time_from, time_till, history_type=value_type):
            meta = item_meta[row["itemid"]]
            capacity = site.get("capacity_mbps", {}).get(meta["link_type"])
            value = _to_percent(float(row["value"]), meta["units"], capacity)
            add_to_channel(channel_maps, meta["link_type"], meta["direction"], _from_epoch(int(row["clock"])), value)
            stats[_channel_stat_key(meta["link_type"], meta["direction"])] += 1

    records = merge_channel_maps(site_name, channel_maps)
    for link_type in LINK_TYPES:
        stats[f"{link_type.lower()}_merged_rows"] = sum(1 for r in records if r.link_type == link_type)
    stats["total_records"] = len(records)
    return records, stats


def fetch_all_site_records_with_stats(
    client: ZabbixClient,
    from_date: str | date,
    to_date: str | date,
    sites: list[dict] | None = None,
) -> tuple[list[UtilizationRecord], list[dict]]:
    """Records for every configured site. One failing site does not stop the others."""
    records: list[UtilizationRecord] = []
    all_stats: list[dict] = []
    for site in sites or SITES:
        try:
            site_records, stats = fetch_site_records_with_stats(
                client, site["name"], from_date=from_date, to_date=to_date
            )
        except ZabbixAPIError as error:
            stats = {key: 0 for key in STAT_KEYS}
            stats.update({"site": site["name"], "from_date": str(from_date), "to_date": str(to_date), "error": str(error)})
            site_records = []
        records.extend(site_records)
        all_stats.append(stats)
    return records, all_stats
