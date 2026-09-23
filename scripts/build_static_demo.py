"""Build docs/index.html: the dashboard with one real pipeline run baked in.

The page needs no server, so it can be hosted on GitHub Pages as a live demo:
    python scripts/build_static_demo.py
    (GitHub: Settings -> Pages -> Deploy from branch -> main /docs)
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.api.app import VERSION  # noqa: E402
from src.services.pipeline import PipelineRun, summarize_run  # noqa: E402
from src.utils.date_utils import build_report_period, parse_date  # noqa: E402

CHART_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js"


def inline_fonts(css: str, web: Path) -> str:
    def repl(match: re.Match) -> str:
        data = base64.b64encode((web / match.group(1)).read_bytes()).decode()
        return f'url("data:font/woff2;base64,{data}")'
    return re.sub(r'url\("(vendor/fonts/[^"]+\.woff2)"\)', repl, css)


def build(report_date: date, out: Path, local_chart: bool) -> Path:
    period = build_report_period("date", report_date, today=date.fromordinal(report_date.toordinal() + 1))
    with tempfile.TemporaryDirectory() as tmp:
        # "now" = the next morning, so the whole report day is complete
        run = PipelineRun(period, data_source="demo", runs_dir=Path(tmp),
                          now=datetime.combine(report_date + timedelta(days=1), time(9, 0)))
        state = run.execute()
    if state["status"] != "succeeded":
        raise SystemExit(f"Pipeline failed: {state['error']}")

    snapshot = {
        "config": {
            "version": VERSION, "data_source": "demo", "timezone": config.REPORT_TIMEZONE,
            "today": date.fromordinal(report_date.toordinal() + 1).isoformat(),
            "thresholds": list(config.THRESHOLDS),
            "sites": [{"name": s["name"], "timezone": s["timezone"]} for s in config.SITES],
        },
        "runs": [summarize_run(state)],
        "run": state,
    }

    web = config.WEB_DIR
    html = (web / "index.html").read_text(encoding="utf-8")
    css = inline_fonts((web / "styles.css").read_text(encoding="utf-8"), web)
    app_js = (web / "app.js").read_text(encoding="utf-8")
    chart_tag = (f"<script>{(web / 'vendor' / 'chart.umd.js').read_text(encoding='utf-8')}</script>"
                 if local_chart else f'<script src="{CHART_CDN}"></script>')
    data = json.dumps(snapshot, separators=(",", ":"), default=str).replace("</", "<\\/")

    html = html.replace('<link rel="stylesheet" href="styles.css">', f"<style>{css}</style>")
    html = html.replace('<script src="vendor/chart.umd.js"></script>', chart_tag)
    html = html.replace('<script src="app.js"></script>',
                        f"<script>window.NUA_SNAPSHOT={data};</script>\n<script>{app_js}</script>")
    html = html.replace("<title>Network Utilization</title>", "<title>Network Utilization: live demo</title>")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="22-09-2026", help="demo day to bake in (DD-MM-YYYY)")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "index.html")
    parser.add_argument("--local-chart", action="store_true", help="inline Chart.js instead of loading it from jsDelivr")
    args = parser.parse_args()
    path = build(parse_date(args.date), args.out, args.local_chart)
    print(f"wrote {path} ({path.stat().st_size // 1024} KB)")
