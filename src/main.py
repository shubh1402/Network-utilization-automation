"""Command-line entry point.

    python -m src.main                      # asks for the period (like the original script)
    python -m src.main --mode yesterday     # non-interactive, for cron / Task Scheduler
    python -m src.main --mode date --date 17-03-2026 --source txt
    python -m src.main --mode range --from 15-09-2026 --to 21-09-2026
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):  # allow `python src/main.py` as in the original README
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DATA_SOURCE, SUPPORTED_DATA_SOURCES  # noqa: E402
from src.services.pipeline import PipelineRun  # noqa: E402
from src.utils.date_utils import MODES, ask_report_period, build_report_period  # noqa: E402

PREFIX = {"info": "[INFO]", "warn": "[WARN]", "error": "[FAIL]"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Network utilization report")
    parser.add_argument("--mode", choices=MODES, help="report period (default: ask)")
    parser.add_argument("--date", help="DD-MM-YYYY for --mode date")
    parser.add_argument("--from", dest="from_date", help="DD-MM-YYYY start for --mode range")
    parser.add_argument("--to", dest="to_date", help="DD-MM-YYYY end for --mode range")
    parser.add_argument("--source", choices=SUPPORTED_DATA_SOURCES, default=DATA_SOURCE,
                        help=f"data source (default from .env: {DATA_SOURCE})")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.mode:
            period = build_report_period(args.mode, args.date or args.from_date, args.to_date)
        else:
            period = ask_report_period()
    except ValueError as error:
        print(error)
        return 2

    run = PipelineRun(period, data_source=args.source, echo=lambda level, msg: print(PREFIX[level], msg))
    state = run.execute()

    print()
    for stage in state["stages"]:
        took = f"{stage['duration_s']:.2f}s" if stage["duration_s"] is not None else ""
        print(f"  {stage['status']:<8} {stage['name']:<32} {took:>7}  {stage['detail']}")
    if state["status"] != "succeeded":
        print(f"\nPipeline failed: {state['error']}")
        return 1

    print(f"\nOutputs in {run.run_dir}")
    for kind, name in state["artifacts"].items():
        print(f"  {kind:<8} {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
