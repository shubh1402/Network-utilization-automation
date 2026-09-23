"""Deterministic traffic simulator so the whole system runs without Zabbix.

The data goes through exactly the same path as real Zabbix data: separate
inbound/outbound channels per link, merged per minute, then summarised.

Each site/day gets its own seeded random stream, so a given date always
produces the same numbers (today's partial run agrees with tomorrow's
"yesterday" run). Traffic follows the site's *local* business hours, dips at
lunch, drops at weekends, can include nightly backup windows and short
bursts, some sites can fail over from primary to secondary, and some can have
short collection gaps (to exercise the accuracy checks).
"""
from __future__ import annotations

import zlib
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from src.config import LINK_TYPES, REPORT_TIMEZONE, SITES
from src.models.utilization_record import UtilizationRecord
from src.services.utilization_service import ChannelMaps, merge_channel_maps
from src.sources.zabbix_source import STAT_KEYS
from src.utils.date_utils import now_local

MINUTES_PER_DAY = 1440


def _offset_hours(site_tz: str, day: date) -> float:
    """How far the site's clock is ahead of the report timezone (DST-aware)."""
    noon = datetime.combine(day, time(12))
    site_offset = noon.replace(tzinfo=ZoneInfo(site_tz)).utcoffset()
    report_offset = noon.replace(tzinfo=ZoneInfo(REPORT_TIMEZONE)).utcoffset()
    return (site_offset - report_offset).total_seconds() / 3600


def _business_curve(local_hours: np.ndarray) -> np.ndarray:
    """0..1 office-traffic shape: morning ramp, lunch dip, afternoon plateau."""
    morning = np.exp(-((local_hours - 11.0) ** 2) / (2 * 2.0**2))
    afternoon = 0.95 * np.exp(-((local_hours - 15.6) ** 2) / (2 * 1.9**2))
    lunch = 0.22 * np.exp(-((local_hours - 13.2) ** 2) / (2 * 0.5**2))
    curve = np.clip(morning + afternoon - lunch, 0, None)
    return curve / curve.max()


def _ar1_noise(rng: np.random.Generator, size: int, sigma: float, phi: float = 0.92) -> np.ndarray:
    shocks = rng.normal(0, sigma * np.sqrt(1 - phi**2), size)
    noise = np.empty(size)
    noise[0] = rng.normal(0, sigma)
    for i in range(1, size):
        noise[i] = phi * noise[i - 1] + shocks[i]
    return noise


def simulate_site_day(site: dict, day: date) -> dict[tuple[str, str], np.ndarray]:
    """Full-day minute arrays (index 0 = 00:00 report time) for the four channels.

    NaN marks minutes with no collected sample.
    """
    profile = {"base": 8, "peak": 45, "noise": 2.5, "bursts": 3, "backup": 0,
               "failover_chance": 0.0, "gap_chance": 0.0}
    profile.update(site.get("demo", {}))
    rng = np.random.default_rng(zlib.crc32(f"{site['name']}|{day.isoformat()}".encode()))

    minutes = np.arange(MINUTES_PER_DAY)
    local_hours = (minutes / 60 + _offset_hours(site["timezone"], day)) % 24
    local_day = day + timedelta(days=int(np.floor((0 + _offset_hours(site["timezone"], day)) / 24)))
    weekend = datetime.combine(local_day, time(12)).weekday() >= 5
    workday = 0.3 if weekend else 1.0

    peak = profile["peak"] * rng.normal(1.0, 0.06)
    base = profile["base"]
    level = base + (peak - base) * _business_curve(local_hours) * workday

    # Nightly backup window around 01:00-02:30 local time.
    if profile["backup"]:
        window = (local_hours >= 1.0) & (local_hours < 2.5)
        level = np.where(window, np.maximum(level, profile["backup"] * rng.normal(1, 0.05)), level)

    # Short bursts during office hours (large downloads, video calls, updates).
    office = np.where((local_hours > 9) & (local_hours < 18.5))[0]
    for _ in range(rng.poisson(profile["bursts"] * workday)):
        start = int(rng.choice(office))
        length = int(rng.integers(4, 35))
        height = float(rng.uniform(8, 26))
        ramp = np.sin(np.linspace(0, np.pi, length)) ** 0.6
        end = min(start + length, MINUTES_PER_DAY)
        level[start:end] += height * ramp[: end - start]

    inbound = level + _ar1_noise(rng, MINUTES_PER_DAY, profile["noise"])
    outbound = level * rng.uniform(0.45, 0.7) + _ar1_noise(rng, MINUTES_PER_DAY, profile["noise"] * 0.7)

    sec_in = rng.uniform(1.5, 3.5) + np.abs(_ar1_noise(rng, MINUTES_PER_DAY, 0.9))
    sec_out = sec_in * 0.6 + np.abs(_ar1_noise(rng, MINUTES_PER_DAY, 0.5))

    # Primary link outage: traffic fails over to the (smaller) secondary link.
    if rng.random() < profile["failover_chance"] * workday:
        start = int(rng.choice(office))
        length = int(rng.integers(25, 75))
        end = min(start + length, MINUTES_PER_DAY)
        caps = site.get("capacity_mbps", {})
        ratio = caps.get("Primary", 300) / max(caps.get("Secondary", 100), 1)
        sec_in[start:end] = np.minimum(inbound[start:end] * ratio * rng.uniform(0.6, 0.85), 99.4)
        sec_out[start:end] = sec_in[start:end] * 0.55
        inbound[start:end] = rng.uniform(0.1, 0.6, end - start)
        outbound[start:end] = rng.uniform(0.1, 0.4, end - start)

    channels = {
        ("Primary", "Inbound"): inbound,
        ("Primary", "Outbound"): outbound,
        ("Secondary", "Inbound"): sec_in,
        ("Secondary", "Outbound"): sec_out,
    }
    channels = {key: np.round(np.clip(values, 0, 100), 2) for key, values in channels.items()}

    # Occasional collection gap (agent/proxy outage) across every channel.
    if rng.random() < profile["gap_chance"]:
        start = int(rng.integers(0, MINUTES_PER_DAY - 60))
        length = int(rng.integers(35, 60))
        for values in channels.values():
            values[start : start + length] = np.nan

    # A handful of single dropped samples, like a real poller.
    for values in channels.values():
        values[rng.integers(0, MINUTES_PER_DAY, rng.integers(0, 3))] = np.nan

    return channels


def fetch_demo_records_with_stats(
    from_date: date,
    to_date: date,
    now: datetime | None = None,
    sites: list[dict] | None = None,
) -> tuple[list[UtilizationRecord], list[dict]]:
    """Same return shape as `fetch_all_site_records_with_stats` for Zabbix."""
    now = now or now_local()
    records: list[UtilizationRecord] = []
    all_stats: list[dict] = []

    for site in sites or SITES:
        channel_maps: ChannelMaps = {}
        stats = {key: 0 for key in STAT_KEYS}
        stats.update({"site": site["name"], "from_date": from_date.isoformat(), "to_date": to_date.isoformat()})

        day = from_date
        while day <= to_date:
            day_start = datetime.combine(day, time.min)
            for (link_type, direction), values in simulate_site_day(site, day).items():
                bucket = channel_maps.setdefault((link_type, direction), {})
                stat_key = f"{link_type.lower()}_{'in' if direction == 'Inbound' else 'out'}_rows"
                for minute, value in enumerate(values):
                    stamp = day_start + timedelta(minutes=minute)
                    if stamp >= now:
                        break
                    if not np.isnan(value):
                        bucket[stamp] = float(value)
                        stats[stat_key] += 1
            day += timedelta(days=1)

        site_records = merge_channel_maps(site["name"], channel_maps)
        for link_type in LINK_TYPES:
            stats[f"{link_type.lower()}_merged_rows"] = sum(1 for r in site_records if r.link_type == link_type)
        stats["total_records"] = len(site_records)
        records.extend(site_records)
        all_stats.append(stats)

    return records, all_stats
