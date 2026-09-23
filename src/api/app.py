"""Web API + dashboard.

    uvicorn src.api.app:app --reload        ->  http://127.0.0.1:8000
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src import config
from src.services.run_store import RunInProgress, RunStore
from src.utils.date_utils import build_report_period, now_local

VERSION = "2.0.0"

app = FastAPI(title="Network Utilization Automation", version=VERSION)
store = RunStore()

ARTIFACT_TYPES = {
    "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "report": "text/plain; charset=utf-8",
    "message": "text/plain; charset=utf-8",
}


class RunRequest(BaseModel):
    mode: str = Field("yesterday", description="yesterday | today | date | range")
    date: str | None = Field(None, description="DD-MM-YYYY or YYYY-MM-DD for mode=date")
    from_date: str | None = None
    to_date: str | None = None
    source: str | None = Field(None, description="demo | zabbix | txt (default from .env)")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": VERSION, "data_source": config.DATA_SOURCE, "running": store.is_running()}


@app.get("/api/config")
def get_config() -> dict:
    return {
        "version": VERSION,
        "data_source": config.DATA_SOURCE,
        "data_sources": list(config.SUPPORTED_DATA_SOURCES),
        "graph_mode": config.GRAPH_MODE,
        "timezone": config.REPORT_TIMEZONE,
        "today": now_local().date().isoformat(),
        "thresholds": list(config.THRESHOLDS),
        "zabbix_configured": bool(config.ZABBIX_API_URL and config.ZABBIX_API_TOKEN),
        "sites": [
            {"name": s["name"], "timezone": s["timezone"], "zabbix_host": s["zabbix_host"],
             "capacity_mbps": s.get("capacity_mbps", {})}
            for s in config.SITES
        ],
    }


@app.get("/api/runs")
def list_runs() -> list[dict]:
    return store.list()


@app.post("/api/runs", status_code=202)
def create_run(request: RunRequest) -> dict:
    source = (request.source or config.DATA_SOURCE).lower()
    if source not in config.SUPPORTED_DATA_SOURCES:
        raise HTTPException(422, f"Unknown data source '{source}'")
    try:
        period = build_report_period(request.mode, request.date or request.from_date, request.to_date)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    try:
        state = store.start(period, data_source=source)
    except RunInProgress as error:
        raise HTTPException(409, f"Run {error} is still in progress. Wait for it to finish.") from error
    return {"id": state["id"], "status": state["status"], "period": state["period"]}


@app.get("/api/runs/latest")
def latest_run():
    state = store.latest_succeeded()
    if state is None:
        return JSONResponse({"detail": "No finished runs yet"}, status_code=404)
    return state


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    state = store.get(run_id)
    if state is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return state


@app.get("/api/runs/{run_id}/files/{kind}")
def download(run_id: str, kind: str):
    state = store.get(run_id)
    if state is None or kind not in ARTIFACT_TYPES:
        raise HTTPException(404, "File not found")
    name = state.get("artifacts", {}).get(kind)
    path = store.artifact_path(run_id, name) if name else None
    if path is None:
        raise HTTPException(404, "This run has no such file")
    return FileResponse(path, media_type=ARTIFACT_TYPES[kind], filename=name)


@app.get("/api/runs/{run_id}/images/{name}")
def image(run_id: str, name: str):
    path = store.artifact_path(run_id, f"images/{name}")
    if path is None or path.suffix.lower() != ".png":
        raise HTTPException(404, "Image not found")
    return FileResponse(path, media_type="image/png")


app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")
