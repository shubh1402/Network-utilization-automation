from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

INPUT_DIR = BASE_DIR / "input"
INPUT_LOGS_DIR = INPUT_DIR / "logs"
INPUT_SCREENSHOTS_DIR = INPUT_DIR / "screenshots"

OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_REPORTS_DIR = OUTPUT_DIR / "reports"
OUTPUT_MESSAGES_DIR = OUTPUT_DIR / "messages"
RUN_LOG_FILE = OUTPUT_DIR / "run_logs" / "automation.log"

SITE_ORDER = [
"Location_1",
"Location_2",
"Location_3",
"Location_4",
"Location_5",
"Location_6"
]

DATA_SOURCE = os.getenv("DATA_SOURCE", "txt").lower()

ZABBIX_API_URL = os.getenv("ZABBIX_API_URL")
ZABBIX_API_TOKEN = os.getenv("ZABBIX_API_TOKEN")
ZABBIX_VERIFY_SSL = os.getenv("ZABBIX_VERIFY_SSL", "true").lower() == "true"
FORTIGATE_SITE_CONFIG = {
    
    "Chennai": {
        "url": os.getenv("FORTIGATE_CHENNAI_URL"),
        "username": os.getenv("FORTIGATE_CHENNAI_USERNAME"),
        "password": os.getenv("FORTIGATE_CHENNAI_PASSWORD"),
    },
    "Colombes": {
        "url": os.getenv("FORTIGATE_COLOMBES_URL"),
        "username": os.getenv("FORTIGATE_COLOMBES_USERNAME"),
        "password": os.getenv("FORTIGATE_COLOMBES_PASSWORD"),
    },
    "Illkirch": {
        "url": os.getenv("FORTIGATE_ILLKIRCH_URL"),
        "username": os.getenv("FORTIGATE_ILLKIRCH_USERNAME"),
        "password": os.getenv("FORTIGATE_ILLKIRCH_PASSWORD"),
    },
    "Brest": {
        "url": os.getenv("FORTIGATE_BREST_URL"),
        "username": os.getenv("FORTIGATE_BREST_USERNAME"),
        "password": os.getenv("FORTIGATE_BREST_PASSWORD"),
    },
    "Thousand Oaks": {
        "url": os.getenv("FORTIGATE_THOUSAND_OAKS_URL"),
        "username": os.getenv("FORTIGATE_THOUSAND_OAKS_USERNAME"),
        "password": os.getenv("FORTIGATE_THOUSAND_OAKS_PASSWORD"),
    },
    "Bangalore": {
        "url": os.getenv("FORTIGATE_BANGALORE_URL"),
        "username": os.getenv("FORTIGATE_BANGALORE_USERNAME"),
        "password": os.getenv("FORTIGATE_BANGALORE_PASSWORD"),
    },
    "Shanghai": {
        "url": os.getenv("FORTIGATE_SHANGHAI_URL"),
        "username": os.getenv("FORTIGATE_SHANGHAI_USERNAME"),
        "password": os.getenv("FORTIGATE_SHANGHAI_PASSWORD"),
    },
}