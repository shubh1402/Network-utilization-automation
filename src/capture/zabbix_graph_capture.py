"""Screenshot per-link graphs from the Zabbix web UI (GRAPH_MODE=zabbix).

Each site in config/sites.json lists its graph ids:
    "zabbix_graph_ids": {"Primary": 1234, "Secondary": 1235}
Zabbix renders a graph as a PNG at chart2.php, so after logging in we open
that URL for the report period and screenshot the image element.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from src.capture.browser import make_driver
from src.capture.graph_renderer import safe_name
from src.config import (
    HEADLESS,
    INPUT_SCREENSHOTS_DIR,
    SITES,
    ZABBIX_WEB_PASSWORD,
    ZABBIX_WEB_URL,
    ZABBIX_WEB_USERNAME,
)


def _login(driver, wait) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC

    driver.get(ZABBIX_WEB_URL.rstrip("/") + "/index.php")
    wait.until(EC.presence_of_element_located((By.ID, "name"))).send_keys(ZABBIX_WEB_USERNAME)
    driver.find_element(By.ID, "password").send_keys(ZABBIX_WEB_PASSWORD)
    driver.find_element(By.ID, "enter").click()
    wait.until(lambda d: "index.php" not in d.current_url or "zbx_session" in {c["name"] for c in d.get_cookies()})


def graph_url(graph_id: int, start: datetime, end: datetime, width: int = 1400, height: int = 320) -> str:
    query = urlencode({
        "graphid": graph_id,
        "from": start.strftime("%Y-%m-%d %H:%M:%S"),
        "to": end.strftime("%Y-%m-%d %H:%M:%S"),
        "width": width,
        "height": height,
        "profileIdx": "web.charts.filter",
    })
    return f"{ZABBIX_WEB_URL.rstrip('/')}/chart2.php?{query}"


def run_graph_capture(
    report_period: str,
    start: datetime | None = None,
    end: datetime | None = None,
    output_dir: Path = INPUT_SCREENSHOTS_DIR,
    headless: bool = HEADLESS,
) -> list[dict]:
    """Capture every configured graph. Returns one result dict per graph."""
    if not (ZABBIX_WEB_URL and ZABBIX_WEB_USERNAME and ZABBIX_WEB_PASSWORD):
        raise RuntimeError("Set ZABBIX_WEB_URL, ZABBIX_WEB_USERNAME and ZABBIX_WEB_PASSWORD for graph capture")

    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    driver = make_driver(headless)
    try:
        wait = WebDriverWait(driver, 30)
        _login(driver, wait)
        for site in SITES:
            for link, graph_id in site.get("zabbix_graph_ids", {}).items():
                target = output_dir / f"{safe_name(site['name'])}_{link}_{safe_name(report_period)}.png"
                try:
                    driver.get(graph_url(graph_id, start, end))
                    wait.until(lambda d: d.find_elements(By.TAG_NAME, "img"))
                    driver.find_element(By.TAG_NAME, "img").screenshot(str(target))
                    results.append({"site": site["name"], "link": link, "status": "SUCCESS", "path": str(target), "error": ""})
                except Exception as error:
                    results.append({"site": site["name"], "link": link, "status": "FAILED", "path": "", "error": str(error)})
    finally:
        driver.quit()
    return results


def write_capture_summary(capture_results: list[dict], output_dir: Path = INPUT_SCREENSHOTS_DIR) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "capture_summary.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["site", "link", "status", "path", "error"])
        writer.writeheader()
        writer.writerows(capture_results)
    return path
