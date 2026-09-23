"""The utilization pipeline as a reusable object.

Stages (same order as the original production script):
    1. collect    - pull per-minute data from Zabbix / TXT exports / simulator
    2. summarize  - merge in/out, count threshold minutes, find breach periods
    3. validate   - accuracy checks on the raw input and on the summary
    4. graphs     - render (or screenshot) one graph per site
    5. fortigate  - top-talker captures for sites that crossed 70%
    6. report     - text report + short team message
    7. excel      - workbook with summary, periods, heatmap, graphs, checks

The CLI (src/main.py) and the web API (src/api/app.py) both run this, so the
dashboard always shows exactly what the scheduled job would have produced.
"""
from __future__ import annotations

import copy
import json
import secrets
import threading
import time
import traceback
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from src import config
from src.capture.fortigate_capture import fortigate_configured, run_fortigate_capture
from src.capture.graph_renderer import render_all_graphs
from src.excel.report_generator import save_excel_report
from src.messages.message_builder import build_message
from src.messages.message_service import save_message
from src.messages.report_builder import build_summary
from src.services.report_service import save_report
from src.services.utilization_service import (
    build_headline,
    build_series,
    get_sites_above_70,
    site_status,
    sort_site_data,
    summarize_records,
)
from src.utils.date_utils import now_local, period_bounds
from src.utils.logger import get_logger, setup_logger
from src.validation.accuracy_checker import evaluate_txt
from src.validation.report_accuracy_checker import evaluate_report

STAGES = [
    ("collect", "Collect utilization data"),
    ("summarize", "Count threshold minutes"),
    ("validate", "Run accuracy checks"),
    ("graphs", "Draw site graphs"),
    ("fortigate", "Capture FortiGate top talkers"),
    ("report", "Write report and team message"),
    ("excel", "Export Excel workbook"),
]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def _series_step(start: datetime, end: datetime) -> int:
    days = (end - start).total_seconds() / 86400
    return 5 if days <= 2 else 15 if days <= 8 else 60


def new_run_id(now: datetime | None = None) -> str:
    return f"{(now or now_local()).strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


class PipelineRun:
    def __init__(
        self,
        period: dict,
        data_source: str | None = None,
        run_id: str | None = None,
        runs_dir: Path | None = None,
        now: datetime | None = None,
        logs_dir: Path | None = None,
        echo: Callable[[str, str], None] | None = None,
    ) -> None:
        self.period = period
        self.data_source = (data_source or config.DATA_SOURCE).lower()
        if self.data_source not in config.SUPPORTED_DATA_SOURCES:
            raise ValueError(f"Unknown data source '{self.data_source}'")
        self.now = now
        self.logs_dir = Path(logs_dir or config.INPUT_LOGS_DIR)
        self.run_id = run_id or new_run_id(now)
        self.run_dir = Path(runs_dir or config.OUTPUT_RUNS_DIR) / self.run_id
        self.echo = echo
        self.logger = setup_logger(config.RUN_LOG_FILE)
        self._lock = threading.Lock()
        self.state: dict = {
            "id": self.run_id,
            "status": "queued",
            "error": None,
            "created_at": _iso(now_local()),
            "started_at": None,
            "finished_at": None,
            "duration_s": None,
            "data_source": self.data_source,
            "graph_mode": config.GRAPH_MODE,
            "timezone": config.REPORT_TIMEZONE,
            "period": {
                "mode": period["mode"],
                "from_date": period["from_date"].isoformat(),
                "to_date": period["to_date"].isoformat(),
                "label": period["label"],
                "is_partial": period["is_partial"],
            },
            "window": None,
            "stages": [
                {"key": k, "name": n, "status": "pending", "started_at": None, "duration_s": None, "detail": ""}
                for k, n in STAGES
            ],
            "logs": [],
            "result": None,
            "artifacts": {},
        }

    # -- state helpers -------------------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self.state)

    def log(self, message: str, level: str = "info") -> None:
        getattr(self.logger, level if level != "warn" else "warning")(f"[{self.run_id}] {message}")
        with self._lock:
            self.state["logs"].append({"t": now_local().strftime("%H:%M:%S"), "level": level, "msg": message})
        if self.echo:
            self.echo(level, message)

    def _stage(self, key: str) -> dict:
        return next(s for s in self.state["stages"] if s["key"] == key)

    def set_stage(self, key: str, **changes) -> None:
        with self._lock:
            self._stage(key).update(changes)

    @contextmanager
    def stage(self, key: str):
        started = time.perf_counter()
        self.set_stage(key, status="running", started_at=_iso(now_local()))
        try:
            yield
        except Exception:
            self.set_stage(key, status="failed", duration_s=round(time.perf_counter() - started, 2))
            raise
        stage = self._stage(key)
        status = "skipped" if stage["status"] == "skipped" else "done"
        self.set_stage(key, status=status, duration_s=round(time.perf_counter() - started, 2))

    def save(self) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        path = self.run_dir / "run.json"
        path.write_text(json.dumps(self.snapshot(), indent=1, default=str), encoding="utf-8")
        return path

    # -- the pipeline --------------------------------------------------------
    def execute(self) -> dict:
        t0 = time.perf_counter()
        with self._lock:
            self.state["status"] = "running"
            self.state["started_at"] = _iso(now_local())
        start, end = period_bounds(self.period, self.now)
        step = _series_step(start, end)
        expected = int((end - start).total_seconds() // 60)
        with self._lock:
            self.state["window"] = {"start": _iso(start), "end": _iso(end), "expected_minutes": expected, "step_minutes": step}

        self.log(
            f"Utilization report started | source: {self.data_source} | period: {self.period['label']}"
            f"{' (so far)' if self.period['is_partial'] else ''} | {expected} minutes expected per link"
        )
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            result = self._run_stages(start, end, step, expected)
            with self._lock:
                self.state["result"] = result
                self.state["status"] = "succeeded"
            self.log(f"Report ready in {time.perf_counter() - t0:.1f}s")
        except Exception as error:
            with self._lock:
                self.state["status"] = "failed"
                self.state["error"] = str(error)
                for stage in self.state["stages"]:
                    if stage["status"] == "pending":
                        stage["status"] = "skipped"
            self.log(f"Pipeline failed: {error}", "error")
            get_logger().debug(traceback.format_exc())
        finally:
            with self._lock:
                self.state["finished_at"] = _iso(now_local())
                self.state["duration_s"] = round(time.perf_counter() - t0, 2)
            self.save()
        return self.snapshot()

    def _collect(self, start: datetime, end: datetime):
        file_summaries: list[dict] = []
        source_stats: list[dict] = []
        pf, pt = self.period["from_date"], self.period["to_date"]

        if self.data_source == "demo":
            from src.sources.demo_source import fetch_demo_records_with_stats

            records, source_stats = fetch_demo_records_with_stats(pf, pt, now=end)
            self.log(f"Simulated {len(records)} merged samples for {len(source_stats)} sites")

        elif self.data_source == "zabbix":
            from src.clients.zabbix_client import ZabbixClient
            from src.sources.zabbix_source import fetch_all_site_records_with_stats

            if not config.ZABBIX_API_URL or not config.ZABBIX_API_TOKEN:
                raise RuntimeError("Set ZABBIX_API_URL and ZABBIX_API_TOKEN in .env to use DATA_SOURCE=zabbix")
            client = ZabbixClient(config.ZABBIX_API_URL, config.ZABBIX_API_TOKEN,
                                  verify_ssl=config.ZABBIX_VERIFY_SSL, auth_mode=config.ZABBIX_AUTH_MODE)
            self.log(f"Connected to Zabbix API {client.api_version()}")
            records, source_stats = fetch_all_site_records_with_stats(client, pf, pt)
            self.log(f"Zabbix records fetched successfully: {len(records)}")

        else:
            from src.sources.txt_source import fetch_txt_records

            records, file_summaries = fetch_txt_records(self.logs_dir)
            if not file_summaries:
                raise RuntimeError(f"No TXT log files found in {self.logs_dir}")
            for item in file_summaries:
                self.log(
                    f"Parsed {item['file_name']} | site {item['site']} | matched {item['matched_lines']} | "
                    f"unmatched {item['unmatched_lines']} | duplicates {item['duplicate_lines']}",
                    "warn" if item["site"] == "Unknown" or item["unmatched_lines"] else "info",
                )
            inside = [r for r in records if start <= r.timestamp < end]
            if len(inside) < len(records):
                self.log(f"Ignored {len(records) - len(inside)} samples outside the report period", "warn")
            records = inside

        for item in source_stats:
            if item.get("error"):
                self.log(f"{item['site']}: {item['error']}", "warn")
            else:
                self.log(
                    f"{item['site']}: primary in/out {item['primary_in_rows']}/{item['primary_out_rows']}, "
                    f"secondary in/out {item['secondary_in_rows']}/{item['secondary_out_rows']} "
                    f"-> {item['total_records']} merged minutes"
                )
        return records, source_stats, file_summaries

    def _run_stages(self, start: datetime, end: datetime, step: int, expected: int) -> dict:
        label = self.period["label"]
        images_dir = self.run_dir / "images"

        with self.stage("collect"):
            records, source_stats, file_summaries = self._collect(start, end)
            self.set_stage("collect", detail=f"{len(records):,} merged samples")

        with self.stage("summarize"):
            site_data = sort_site_data(summarize_records(records))
            series = build_series(records, start, end, step)
            for site in site_data:
                series.setdefault(site, {link: [None] * max(1, int((end - start).total_seconds() // 60 // step))
                                         for link in config.LINK_TYPES})
            eligible = get_sites_above_70(site_data)
            headline = build_headline(site_data)
            self.log(headline)
            self.set_stage("summarize", detail=f"{len(eligible)} of {len(site_data)} sites above 70%")

        with self.stage("validate"):
            checks = [c.to_dict() for c in evaluate_report(site_data, expected)]
            if self.data_source == "txt":
                checks = [c.to_dict() for c in evaluate_txt(file_summaries, site_data)] + checks
            for check in checks:
                if not check["passed"]:
                    self.log(f"Check '{check['name']}': {check['detail']}", "warn")
            passed = sum(c["passed"] for c in checks)
            self.log(f"Accuracy checks: {passed} of {len(checks)} passed")
            self.set_stage("validate", detail=f"{passed} of {len(checks)} passed")

        with self.stage("graphs"):
            if config.GRAPH_MODE == "zabbix" and self.data_source == "zabbix":
                from src.capture.zabbix_graph_capture import run_graph_capture, write_capture_summary

                graphs = run_graph_capture(label, start, end, output_dir=images_dir)
                write_capture_summary(graphs, images_dir)
            else:
                suffix = self.period["from_date"].strftime("%d %b %Y") if self.period["from_date"] == self.period["to_date"] \
                    else f"{self.period['from_date']:%d %b} to {self.period['to_date']:%d %b %Y}"
                with_data = {site: series[site] for site in site_data if site_status(site_data[site]) != "no-data"}
                graphs = render_all_graphs(with_data, start, step, images_dir, title_suffix=suffix)
            ok = sum(g["status"] == "SUCCESS" for g in graphs)
            for g in graphs:
                if g["status"] != "SUCCESS":
                    self.log(f"Graph failed | {g['site']} | {g['error']}", "warn")
            self.log(f"Graphs completed | success={ok} | failed={len(graphs) - ok}")
            self.set_stage("graphs", detail=f"{ok} of {len(graphs)} graphs")

        with self.stage("fortigate"):
            fortigate: list[dict] = []
            self.log(f"Sites eligible for FortiGate captures: {eligible or 'none'}")
            for site in eligible:
                if self.data_source == "demo":
                    fortigate.append({"site": site, "status": "SKIPPED", "error": "Demo data has no firewall to log into"})
                    continue
                if not fortigate_configured(site):
                    fortigate.append({"site": site, "status": "SKIPPED", "error": "No FortiGate credentials in .env"})
                    continue
                try:
                    run_fortigate_capture(headless=config.HEADLESS, source_row_indices=[0, 1, 2, 3],
                                          site_name=site, output_dir=images_dir)
                    fortigate.append({"site": site, "status": "SUCCESS", "error": ""})
                    self.log(f"FortiGate capture succeeded for {site}")
                except Exception as error:
                    fortigate.append({"site": site, "status": "FAILED", "error": str(error)})
                    self.log(f"FortiGate capture failed for {site}: {error}", "warn")
            captured = sum(f["status"] == "SUCCESS" for f in fortigate)
            if not eligible:
                self.set_stage("fortigate", status="skipped", detail="No site crossed 70%")
            elif captured == 0:
                self.set_stage("fortigate", status="skipped",
                               detail=f"{len(eligible)} sites queued, none captured ({fortigate[0]['error'].lower()})")
            else:
                self.set_stage("fortigate", detail=f"{captured} of {len(eligible)} sites captured")

        with self.stage("report"):
            report_text = build_summary(label, site_data, len(file_summaries), self.data_source, checks)
            message_text = build_message(label, site_data)
            report_file = save_report(self.run_dir, label, report_text)
            message_file = save_message(self.run_dir, label, message_text)
            self.log(f"Report saved: {report_file.name}")
            self.log(f"Message saved: {message_file.name}")
            self.set_stage("report", detail=f"{len(message_text.splitlines())}-line team message")

        with self.stage("excel"):
            excel_file = save_excel_report(
                self.run_dir, label, site_data, images_dir, series=series, series_start=start,
                step_minutes=step, checks=checks,
                meta={"generated_at": now_local().strftime("%d-%m-%Y %H:%M"), "data_source": self.data_source},
            )
            self.log(f"Excel saved: {excel_file.name}")
            self.set_stage("excel", detail=f"{excel_file.stat().st_size // 1024} KB workbook")

        with self._lock:
            self.state["artifacts"] = {
                "excel": excel_file.name,
                "report": report_file.name,
                "message": message_file.name,
            }

        statuses = {site: site_status(links) for site, links in site_data.items()}
        return {
            "headline": headline,
            "site_status": statuses,
            "site_data": site_data,
            "series": series,
            "checks": checks,
            "eligible_sites": eligible,
            "graphs": [{k: v for k, v in g.items() if k != "path"} for g in graphs],
            "fortigate": fortigate,
            "source_stats": source_stats,
            "file_summaries": file_summaries,
            "message_text": message_text,
            "counts": {
                "sites": len(site_data),
                "sites_over_70": len(eligible),
                "critical": sum(s == "critical" for s in statuses.values()),
                "high": sum(s == "high" for s in statuses.values()),
                "elevated": sum(s == "elevated" for s in statuses.values()),
                "no_data": sum(s == "no-data" for s in statuses.values()),
                "checks_passed": sum(c["passed"] for c in checks),
                "checks_total": len(checks),
            },
        }


def summarize_run(state: dict) -> dict:
    """Small version of a run for history lists."""
    result = state.get("result") or {}
    return {
        "id": state["id"],
        "status": state["status"],
        "created_at": state["created_at"],
        "duration_s": state.get("duration_s"),
        "data_source": state["data_source"],
        "period": state["period"],
        "headline": result.get("headline"),
        "counts": result.get("counts"),
        "error": state.get("error"),
    }
