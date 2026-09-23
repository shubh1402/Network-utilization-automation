"""Minimal Zabbix JSON-RPC client.

Supports API-token auth both ways Zabbix accepts it:
  * header mode (Zabbix 6.4+): `Authorization: Bearer <token>`
  * body mode   (older):       `"auth": "<token>"` inside the request
"""
from __future__ import annotations

import itertools
import time
from typing import Any

import requests
import urllib3


class ZabbixAPIError(RuntimeError):
    """Raised when Zabbix returns an error object or the call cannot be completed."""


class ZabbixClient:
    # Zabbix value_type -> history table: 0 = float, 3 = unsigned integer
    NUMERIC_HISTORY_TYPES = (0, 3)

    def __init__(
        self,
        api_url: str,
        api_token: str,
        verify_ssl: bool = True,
        auth_mode: str = "header",
        timeout: int = 30,
        retries: int = 3,
        session: requests.Session | None = None,
    ) -> None:
        if not api_url:
            raise ValueError("Zabbix API URL is required")
        if not api_token:
            raise ValueError("Zabbix API token is required")
        self.api_url = api_url if api_url.endswith("api_jsonrpc.php") else api_url.rstrip("/") + "/api_jsonrpc.php"
        self.api_token = api_token
        self.verify_ssl = verify_ssl
        self.auth_mode = auth_mode
        self.timeout = timeout
        self.retries = retries
        self.session = session or requests.Session()
        self._ids = itertools.count(1)
        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # -- transport -------------------------------------------------------------
    def call(self, method: str, params: Any = None, authenticated: bool = True) -> Any:
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params if params is not None else {},
            "id": next(self._ids),
        }
        headers = {"Content-Type": "application/json-rpc"}
        if authenticated:
            if self.auth_mode == "body":
                payload["auth"] = self.api_token
            else:
                headers["Authorization"] = f"Bearer {self.api_token}"

        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.post(
                    self.api_url, json=payload, headers=headers, timeout=self.timeout, verify=self.verify_ssl
                )
                response.raise_for_status()
                body = response.json()
            except (requests.RequestException, ValueError) as error:
                last_error = error
                if attempt < self.retries:
                    time.sleep(min(2 ** (attempt - 1), 8))
                    continue
                raise ZabbixAPIError(f"{method} failed after {self.retries} attempts: {error}") from error

            if "error" in body:
                err = body["error"]
                raise ZabbixAPIError(f"{method}: {err.get('message')} {err.get('data', '')}".strip())
            return body.get("result")

        raise ZabbixAPIError(f"{method} failed: {last_error}")

    # -- API helpers -----------------------------------------------------------
    def api_version(self) -> str:
        return self.call("apiinfo.version", {}, authenticated=False)

    def get_hosts(self, host_names: list[str]) -> list[dict]:
        return self.call(
            "host.get",
            {"output": ["hostid", "host", "name"], "filter": {"host": host_names}},
        )

    def get_host_id(self, host_name: str) -> str:
        hosts = self.get_hosts([host_name])
        if not hosts:
            raise ZabbixAPIError(f"Host '{host_name}' not found in Zabbix")
        return hosts[0]["hostid"]

    def get_items(self, host_id: str, item_names: list[str]) -> list[dict]:
        return self.call(
            "item.get",
            {
                "output": ["itemid", "name", "key_", "value_type", "units"],
                "hostids": host_id,
                "filter": {"name": item_names},
            },
        )

    def get_history(
        self,
        item_ids: list[str],
        time_from: int,
        time_till: int,
        history_type: int = 0,
        chunk_seconds: int = 6 * 3600,
    ) -> list[dict]:
        """Fetch history in time chunks so a multi-day range never becomes one huge response."""
        if history_type not in self.NUMERIC_HISTORY_TYPES:
            raise ValueError(f"Unsupported history type {history_type}; expected numeric item")
        rows: list[dict] = []
        start = time_from
        while start <= time_till:
            end = min(start + chunk_seconds - 1, time_till)
            rows.extend(
                self.call(
                    "history.get",
                    {
                        "output": ["itemid", "clock", "value"],
                        "history": history_type,
                        "itemids": item_ids,
                        "time_from": start,
                        "time_till": end,
                        "sortfield": "clock",
                        "sortorder": "ASC",
                    },
                )
                or []
            )
            start = end + 1
        return rows
