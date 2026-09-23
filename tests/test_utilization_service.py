from datetime import datetime, timedelta

from src.models.utilization_record import UtilizationRecord
from src.services.utilization_service import (
    build_headline,
    find_episodes,
    get_sites_above_70,
    merge_channel_maps,
    sort_site_data,
    summarize_records,
)

T0 = datetime(2026, 9, 22, 10, 0)


def records(values, site="Pune", link="Primary"):
    return [UtilizationRecord(site, link, T0 + timedelta(minutes=i), v) for i, v in enumerate(values)]


def test_merge_takes_the_busier_direction_per_minute():
    maps = {
        ("Primary", "Inbound"): {T0: 40.0, T0 + timedelta(minutes=1): 90.0},
        ("Primary", "Outbound"): {T0: 55.0},
    }
    merged = merge_channel_maps("Pune", maps)
    assert [(r.timestamp, r.value) for r in merged] == [(T0, 55.0), (T0 + timedelta(minutes=1), 90.0)]


def test_thresholds_are_strict_and_cumulative():
    link = summarize_records(records([70, 70.01, 80, 80.5, 90, 95]))["Pune"]["Primary"]
    assert link["above_70_events"] == 5
    assert link["above_80_events"] == 3
    assert link["above_90_events"] == 1
    assert link["total_base_events"] == 6
    assert link["peak"] == 95 and link["status"] == "critical"


def test_short_dips_do_not_split_a_breach_period():
    values = [75] * 10 + [60] * 3 + [85] * 5 + [50] * 10 + [72] * 2
    points = [(r.timestamp, r.value) for r in records(values)]
    episodes = find_episodes(points)
    assert len(episodes) == 2
    first, second = episodes
    assert first["minutes"] == 15 and first["duration"] == 18 and first["level"] == 80
    assert second["minutes"] == 2
    assert sum(e["minutes"] for e in episodes) == sum(v > 70 for v in values)


def test_missing_sites_are_reported_as_no_data():
    site_data = sort_site_data(summarize_records(records([10, 20])), site_order=["Pune", "Mumbai"])
    assert list(site_data) == ["Pune", "Mumbai"]
    assert site_data["Mumbai"]["Primary"]["status"] == "no-data"


def test_sites_above_70_and_headline():
    data = summarize_records(records([50, 60]) + records([50, 88, 88], site="Mumbai"))
    assert get_sites_above_70(data) == ["Mumbai"]
    assert build_headline(data).startswith("Mumbai's primary link ran above 80% for 2 minutes")
    assert "stayed below 70%" in build_headline(summarize_records(records([10])))
