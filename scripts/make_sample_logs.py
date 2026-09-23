"""Write demo data as Zabbix plain-text history exports, to try DATA_SOURCE=txt.

    python scripts/make_sample_logs.py --date 22-09-2026 --sites Pune Hyderabad
    python -m src.main --source txt --mode date --date 22-09-2026
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import INPUT_LOGS_DIR, SITES_BY_NAME  # noqa: E402
from src.sources.demo_source import simulate_site_day  # noqa: E402
from src.sources.txt_source import write_zabbix_export  # noqa: E402
from src.utils.date_utils import parse_date  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", required=True, help="DD-MM-YYYY")
    parser.add_argument("--sites", nargs="+", default=list(SITES_BY_NAME), help="site names (default: all)")
    parser.add_argument("--out", type=Path, default=INPUT_LOGS_DIR)
    args = parser.parse_args()

    day = parse_date(args.date)
    start = datetime.combine(day, datetime.min.time())
    for name in args.sites:
        site = SITES_BY_NAME[name]
        for link in ("Primary", "Secondary"):
            rows = []
            for (link_type, direction), values in simulate_site_day(site, day).items():
                if link_type != link:
                    continue
                label = f"{link} link utilization {direction.lower()}"
                rows += [(start + timedelta(minutes=i), float(v), label) for i, v in enumerate(values) if not np.isnan(v)]
            rows.sort(key=lambda r: (r[0], r[2]))
            path = args.out / f"{name}_{link}.txt"
            write_zabbix_export(path, f"{name} {link}", rows)
            print(f"wrote {path} ({len(rows)} lines)")


if __name__ == "__main__":
    main()
