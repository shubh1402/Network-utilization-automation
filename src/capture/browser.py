"""Headless Chrome factory shared by the Selenium capture modules.

Selenium is imported lazily so demo/render mode never needs a browser.
"""
from __future__ import annotations


def make_driver(headless: bool = True, width: int = 1600, height: int = 1000):
    try:
        from selenium import webdriver
    except ImportError as error:  # pragma: no cover - depends on environment
        raise RuntimeError("Selenium is not installed. Run: pip install selenium") from error

    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument(f"--window-size={width},{height}")
    options.add_argument("--ignore-certificate-errors")  # firewalls often use self-signed certs
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    driver = webdriver.Chrome(options=options)  # Selenium Manager resolves chromedriver
    driver.set_page_load_timeout(60)
    return driver
