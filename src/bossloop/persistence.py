"""JSON checkpoints. One state file is the resume point; step files are the timeline."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from bossloop.models import LoopState

_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:6]}"


def runs_root_from_env(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    import os

    raw = os.environ.get("BOSSLOOP_RUNS_DIR", "").strip()
    if raw:
        return Path(raw)
    return Path.cwd() / "runs"


def run_dir(root: Path, run_id: str) -> Path:
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError(f"Invalid run id: {run_id!r}")
    return root / run_id


def save_state(root: Path, state: LoopState, *, node: str | None = None) -> Path:
    folder = run_dir(root, state.run_id)
    folder.mkdir(parents=True, exist_ok=True)
    payload = state.model_dump(mode="json")
    target = folder / "state.json"
    temporary = folder / "state.json.tmp"
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    if node:
        steps = folder / "steps"
        steps.mkdir(exist_ok=True)
        step_path = steps / f"{state.step:02d}-{node}.json"
        step_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def load_state(root: Path, run_id: str) -> LoopState:
    path = run_dir(root, run_id) / "state.json"
    if not path.exists():
        raise FileNotFoundError(f"No checkpoint at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    state = LoopState.model_validate(data)
    if state.schema_version != 1:
        raise ValueError(f"Unsupported checkpoint schema {state.schema_version}")
    return state


def list_states(root: Path) -> list[LoopState]:
    if not root.exists():
        return []
    found: list[LoopState] = []
    for path in sorted(root.glob("*/state.json")):
        try:
            found.append(LoopState.model_validate(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    found.sort(key=lambda state: state.updated_at, reverse=True)
    return found
