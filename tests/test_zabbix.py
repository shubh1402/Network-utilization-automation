from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.clients.zabbix_client import ZabbixAPIError, ZabbixClient
from src.sources.zabbix_source import fetch_site_records_with_stats


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, body):
        self.body, self.calls = body, []

    def post(self, url, json, headers, timeout, verify):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return FakeResponse(self.body)


def test_header_auth_and_url_normalisation():
    session = FakeSession({"jsonrpc": "2.0", "result": "7.0.0", "id": 1})
    client = ZabbixClient("https://zbx.example.com", "tok", session=session)
    client.call("host.get", {})
    call = session.calls[0]
    assert call["url"] == "https://zbx.example.com/api_jsonrpc.php"
    assert call["headers"]["Authorization"] == "Bearer tok"
    assert "auth" not in call["json"]


def test_body_auth_for_older_zabbix():
    session = FakeSession({"jsonrpc": "2.0", "result": [], "id": 1})
    ZabbixClient("https://zbx/api_jsonrpc.php", "tok", auth_mode="body", session=session).call("host.get")
    assert session.calls[0]["json"]["auth"] == "tok"


def test_api_errors_raise():
    session = FakeSession({"jsonrpc": "2.0", "error": {"message": "Not authorised", "data": "bad token"}, "id": 1})
    with pytest.raises(ZabbixAPIError, match="Not authorised"):
        ZabbixClient("https://zbx", "tok", session=session).call("host.get")


class FakeClient:
    """Stands in for ZabbixClient: one host, % items for primary, bps items for secondary."""

    def get_host_id(self, host):
        assert host == "PUN-FW01"
        return "10101"

    def get_items(self, host_id, names):
        return [
            {"itemid": "1", "name": "Primary link utilization inbound", "value_type": "0", "units": "%"},
            {"itemid": "2", "name": "Primary link utilization outbound", "value_type": "0", "units": "%"},
            {"itemid": "3", "name": "Secondary link utilization inbound", "value_type": "3", "units": "bps"},
        ]

    def get_history(self, item_ids, time_from, time_till, history_type=0):
        clock = int(datetime(2026, 9, 22, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp())
        rows = {
            0: [{"itemid": "1", "clock": clock, "value": "72.5"}, {"itemid": "2", "clock": clock + 20, "value": "91"}],
            3: [{"itemid": "3", "clock": clock, "value": "85000000"}],  # 85 Mbps on a 100 Mbps link
        }
        return rows[history_type]


def test_zabbix_source_merges_and_converts_bps():
    records, stats = fetch_site_records_with_stats(FakeClient(), "Pune", report_date="22-09-2026")
    by_link = {r.link_type: r.value for r in records}
    assert by_link == {"Primary": 91.0, "Secondary": 85.0}
    assert stats["primary_in_rows"] == 1 and stats["primary_out_rows"] == 1
    assert stats["secondary_in_rows"] == 1 and stats["total_records"] == 2
    assert stats["missing_items"] == ["Secondary link utilization outbound"]
