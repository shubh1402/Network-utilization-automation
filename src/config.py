"""Central configuration.

Everything environment-specific lives in `.env` (secrets, URLs) or in
`config/sites.json` (site inventory). Nothing site- or customer-specific is
hard-coded here, so the same code runs against a real Zabbix or in demo mode.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    if not value:
        return default
    path = Path(value)
    return path if path.is_absolute() else BASE_DIR / path


# --- Folders ----------------------------------------------------------------
INPUT_DIR = BASE_DIR / "input"
INPUT_LOGS_DIR = _env_path("INPUT_LOGS_DIR", INPUT_DIR / "logs")
INPUT_SCREENSHOTS_DIR = INPUT_DIR / "screenshots"

OUTPUT_DIR = _env_path("OUTPUT_DIR", BASE_DIR / "output")
OUTPUT_REPORTS_DIR = OUTPUT_DIR / "reports"
OUTPUT_MESSAGES_DIR = OUTPUT_DIR / "messages"
OUTPUT_RUNS_DIR = OUTPUT_DIR / "runs"
RUN_LOG_FILE = OUTPUT_DIR / "run_logs" / "automation.log"

WEB_DIR = BASE_DIR / "web"

# --- Behaviour ----------------------------------------------------------------
# demo   -> built-in traffic simulator (no credentials needed)
# zabbix -> live Zabbix JSON-RPC API
# txt    -> Zabbix history exports dropped into input/logs
DATA_SOURCE = os.getenv("DATA_SOURCE", "demo").strip().lower()
SUPPORTED_DATA_SOURCES = ("demo", "zabbix", "txt")

# All report times are shown in this timezone (the NOC's timezone).
REPORT_TIMEZONE = os.getenv("REPORT_TIMEZONE", "Asia/Kolkata")

# render  -> draw graphs from the collected data with matplotlib (default)
# zabbix  -> screenshot the graphs from the Zabbix web UI with Selenium
GRAPH_MODE = os.getenv("GRAPH_MODE", "render").strip().lower()

# Utilization thresholds (%), highest first. Counts are cumulative:
# a minute at 93% counts towards >90, >80 and >70.
THRESHOLDS = (90, 80, 70)
FORTIGATE_TRIGGER_THRESHOLD = 70
LINK_TYPES = ("Primary", "Secondary")
DIRECTIONS = ("Inbound", "Outbound")

# Minimum share of expected per-minute samples before a link is flagged
# as having a data gap by the report accuracy checker.
MIN_COVERAGE = float(os.getenv("MIN_COVERAGE", "0.98"))

HEADLESS = _env_bool("HEADLESS", True)

# --- Site inventory -----------------------------------------------------------
SITES_FILE = _env_path("SITES_FILE", BASE_DIR / "config" / "sites.json")


def load_sites(path: Path = SITES_FILE) -> list[dict]:
    """Load and validate the site inventory."""
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    sites = payload.get("sites", [])
    seen: set[str] = set()
    for site in sites:
        if "name" not in site:
            raise ValueError(f"Site entry without a name in {path}")
        if site["name"] in seen:
            raise ValueError(f"Duplicate site name '{site['name']}' in {path}")
        seen.add(site["name"])
        site.setdefault("zabbix_host", site["name"])
        site.setdefault("timezone", REPORT_TIMEZONE)
        site.setdefault("capacity_mbps", {})
        site.setdefault("fortigate_key", site["name"].upper().replace(" ", "_"))
        site.setdefault("zabbix_graph_ids", {})
        site.setdefault("demo", {})
    return sites


SITES: list[dict] = load_sites()
SITE_ORDER: list[str] = [site["name"] for site in SITES]
SITES_BY_NAME: dict[str, dict] = {site["name"]: site for site in SITES}

# --- Zabbix -------------------------------------------------------------------
ZABBIX_API_URL = os.getenv("ZABBIX_API_URL")  # e.g. https://zabbix.example.com/api_jsonrpc.php
ZABBIX_API_TOKEN = os.getenv("ZABBIX_API_TOKEN")
ZABBIX_VERIFY_SSL = _env_bool("ZABBIX_VERIFY_SSL", True)
# "header" = Authorization: Bearer (Zabbix 6.4+), "body" = legacy "auth" field
ZABBIX_AUTH_MODE = os.getenv("ZABBIX_AUTH_MODE", "header").strip().lower()

# Web UI login, only needed for GRAPH_MODE=zabbix screenshots.
ZABBIX_WEB_URL = os.getenv("ZABBIX_WEB_URL")  # e.g. https://zabbix.example.com
ZABBIX_WEB_USERNAME = os.getenv("ZABBIX_WEB_USERNAME")
ZABBIX_WEB_PASSWORD = os.getenv("ZABBIX_WEB_PASSWORD")

# Item names on every site host, one per link + direction.
ZABBIX_ITEM_NAMES: dict[tuple[str, str], str] = {
    ("Primary", "Inbound"): os.getenv("ZABBIX_ITEM_PRIMARY_IN", "Primary link utilization inbound"),
    ("Primary", "Outbound"): os.getenv("ZABBIX_ITEM_PRIMARY_OUT", "Primary link utilization outbound"),
    ("Secondary", "Inbound"): os.getenv("ZABBIX_ITEM_SECONDARY_IN", "Secondary link utilization inbound"),
    ("Secondary", "Outbound"): os.getenv("ZABBIX_ITEM_SECONDARY_OUT", "Secondary link utilization outbound"),
}

# --- FortiGate ----------------------------------------------------------------
FORTIGATE_VIEW_PATH = os.getenv("FORTIGATE_VIEW_PATH", "/ng/fortiview/sources")
FORTIGATE_TABLE_ROW_SELECTOR = os.getenv("FORTIGATE_TABLE_ROW_SELECTOR", "table tbody tr")


def fortigate_credentials(site: dict) -> dict:
    key = site["fortigate_key"]
    return {
        "url": os.getenv(f"FORTIGATE_{key}_URL"),
        "username": os.getenv(f"FORTIGATE_{key}_USERNAME"),
        "password": os.getenv(f"FORTIGATE_{key}_PASSWORD"),
    }


# Kept under the original name so older scripts keep working.
FORTIGATE_SITE_CONFIG: dict[str, dict] = {site["name"]: fortigate_credentials(site) for site in SITES}
