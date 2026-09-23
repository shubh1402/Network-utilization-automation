"""Keeps track of pipeline runs for the web API (one run at a time)."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from src import config
from src.services.pipeline import PipelineRun, summarize_run


class RunInProgress(RuntimeError):
    pass


class RunStore:
    def __init__(self, runs_dir: Path | None = None, history_limit: int = 50) -> None:
        self.runs_dir = Path(runs_dir or config.OUTPUT_RUNS_DIR)
        self.history_limit = history_limit
        self._active: PipelineRun | None = None
        self._lock = threading.Lock()

    def _load(self, run_id: str) -> dict | None:
        path = self.runs_dir / run_id / "run.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def get(self, run_id: str) -> dict | None:
        active = self._active
        if active is not None and active.run_id == run_id:
            return active.snapshot()
        if "/" in run_id or "\\" in run_id or run_id.startswith("."):
            return None
        return self._load(run_id)

    def list(self) -> list[dict]:
        runs = []
        if self.runs_dir.exists():
            for folder in sorted(self.runs_dir.iterdir(), reverse=True)[: self.history_limit]:
                state = self.get(folder.name)
                if state:
                    runs.append(summarize_run(state))
        active = self._active
        if active is not None and not any(r["id"] == active.run_id for r in runs):
            runs.insert(0, summarize_run(active.snapshot()))
        return runs

    def latest_succeeded(self) -> dict | None:
        for summary in self.list():
            if summary["status"] == "succeeded":
                return self.get(summary["id"])
        return None

    def is_running(self) -> bool:
        return self._active is not None and self._active.state["status"] in ("queued", "running")

    def start(self, period: dict, data_source: str | None = None, wait: bool = False) -> dict:
        with self._lock:
            if self.is_running():
                raise RunInProgress(self._active.run_id)
            run = PipelineRun(period, data_source=data_source, runs_dir=self.runs_dir)
            self._active = run
        run.save()
        if wait:
            run.execute()
        else:
            threading.Thread(target=run.execute, name=f"run-{run.run_id}", daemon=True).start()
        return run.snapshot()

    def artifact_path(self, run_id: str, name: str) -> Path | None:
        state = self.get(run_id)
        if not state:
            return None
        folder = (self.runs_dir / run_id).resolve()
        path = (folder / name).resolve()
        if folder not in path.parents or not path.is_file():
            return None
        return path
