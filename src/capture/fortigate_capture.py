"""Capture the FortiGate top-talker view for a site that crossed 70%.

When a link is congested, the next question is always "who was using it?".
This logs into the site's FortiGate web UI, opens the FortiView page set by
FORTIGATE_VIEW_PATH and screenshots the top rows (source_row_indices).

Login field ids and the view path differ between FortiOS versions, so they
are configurable in .env; verify them once against your firewall.
"""
from __future__ import annotations

import os
from pathlib import Path

from src.capture.browser import make_driver
from src.capture.graph_renderer import safe_name
from src.config import (
    FORTIGATE_SITE_CONFIG,
    FORTIGATE_TABLE_ROW_SELECTOR,
    FORTIGATE_VIEW_PATH,
    INPUT_SCREENSHOTS_DIR,
)

LOGIN_USER_FIELD = os.getenv("FORTIGATE_LOGIN_USER_FIELD", "username")
LOGIN_PASSWORD_FIELD = os.getenv("FORTIGATE_LOGIN_PASSWORD_FIELD", "secretkey")
LOGIN_BUTTON = os.getenv("FORTIGATE_LOGIN_BUTTON", "login_button")


def fortigate_configured(site_name: str) -> bool:
    creds = FORTIGATE_SITE_CONFIG.get(site_name, {})
    return all(creds.get(k) for k in ("url", "username", "password"))


def run_fortigate_capture(
    headless: bool = True,
    source_row_indices: list[int] | None = None,
    site_name: str = "",
    output_dir: Path = INPUT_SCREENSHOTS_DIR,
) -> list[Path]:
    """Screenshot the full view plus each requested table row. Raises on failure."""
    creds = FORTIGATE_SITE_CONFIG.get(site_name)
    if not creds or not fortigate_configured(site_name):
        raise RuntimeError(f"No FortiGate credentials configured for {site_name}")

    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    rows = source_row_indices if source_row_indices is not None else [0, 1, 2, 3]
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    base = creds["url"].rstrip("/")
    saved: list[Path] = []

    driver = make_driver(headless)
    try:
        wait = WebDriverWait(driver, 40)
        driver.get(base + "/login")
        wait.until(EC.presence_of_element_located((By.ID, LOGIN_USER_FIELD))).send_keys(creds["username"])
        driver.find_element(By.ID, LOGIN_PASSWORD_FIELD).send_keys(creds["password"])
        driver.find_element(By.ID, LOGIN_BUTTON).click()
        wait.until(lambda d: "/login" not in d.current_url)

        driver.get(base + FORTIGATE_VIEW_PATH)
        table_rows = wait.until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, FORTIGATE_TABLE_ROW_SELECTOR))
        )
        full = output_dir / f"FortiGate_{safe_name(site_name)}_view.png"
        driver.save_screenshot(str(full))
        saved.append(full)
        for index in rows:
            if index < len(table_rows):
                target = output_dir / f"FortiGate_{safe_name(site_name)}_row{index + 1}.png"
                table_rows[index].screenshot(str(target))
                saved.append(target)
    finally:
        driver.quit()
    return saved
