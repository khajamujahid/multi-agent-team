"""FastAPI timeline. The same page is a live local board and a static hosted replay."""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from bossloop import __version__
from bossloop.demo_content import DEMO_TASK
from bossloop.llm import MissingKeyError, ProviderError, build_provider
from bossloop.persistence import list_states, load_state, runs_root_from_env
from bossloop.runner import resume, run_task

_LOCK = threading.Lock()


class RunRequest(BaseModel):
    task: str | None = None
    demo: bool = False
    max_iterations: int = Field(default=4, ge=1, le=8)
    provider: str = "auto"


def site_dir() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "site",
        here.parents[1] / "site",
        Path.cwd() / "site",
    ]
    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate
    raise FileNotFoundError("site/index.html was not found. Start the dashboard from the repo.")


def create_app() -> FastAPI:
    app = FastAPI(title="BossLoop", version=__version__)

    @app.get("/api/health")
    def health() -> dict:
        provider = build_provider("auto")
        return {
            "ok": True,
            "version": __version__,
            "provider": provider.name,
            "live_runs": True,
        }

    @app.get("/api/sample")
    def sample() -> dict:
        return _read_sample()

    @app.get("/api/runs")
    def runs() -> list[dict]:
        return [state.model_dump(mode="json") for state in list_states(runs_root_from_env())]

    @app.get("/api/runs/{run_id}")
    def one_run(run_id: str) -> dict:
        try:
            state = load_state(runs_root_from_env(), run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return state.model_dump(mode="json")

    @app.post("/api/runs")
    def start_run(body: RunRequest) -> dict:
        try:
            provider_name = "mock" if body.demo else body.provider
            provider = build_provider(provider_name)
            task = DEMO_TASK if body.demo or not (body.task and body.task.strip()) else body.task
            with _LOCK:
                state = run_task(
                    task or DEMO_TASK,
                    provider,
                    runs_root_from_env(),
                    max_iterations=body.max_iterations,
                )
        except (ProviderError, MissingKeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return state.model_dump(mode="json")

    @app.post("/api/runs/{run_id}/resume")
    def resume_run(run_id: str) -> dict:
        root = runs_root_from_env()
        try:
            existing = load_state(root, run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        choice = "mock" if existing.provider == "mock" else "auto"
        try:
            provider = build_provider(choice)
            with _LOCK:
                state = resume(run_id, provider, root)
        except (ProviderError, MissingKeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return state.model_dump(mode="json")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(site_dir() / "index.html")

    @app.get("/sample_run.json")
    def sample_file() -> FileResponse:
        path = site_dir() / "sample_run.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="sample_run.json is missing")
        return FileResponse(path)

    return app


def _read_sample() -> dict:
    path = site_dir() / "sample_run.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="sample_run.json is missing")
    import json

    return json.loads(path.read_text(encoding="utf-8"))


app = create_app()
