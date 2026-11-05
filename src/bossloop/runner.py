"""Start a crew run, or resume one from the last checkpoint."""

from __future__ import annotations

from pathlib import Path

from bossloop.demo_content import DEMO_TASK
from bossloop.graph import build_graph
from bossloop.llm import Provider
from bossloop.models import LoopState
from bossloop.persistence import load_state, new_run_id, save_state, utcnow


def fresh_state(
    task: str,
    provider_name: str,
    *,
    max_iterations: int = 4,
    run_id: str | None = None,
) -> LoopState:
    if not task.strip():
        raise ValueError("A work order is required.")
    if len(task) > 8000:
        raise ValueError("Work order is too long.")
    bounded = min(max(max_iterations, 1), 8)
    now = utcnow()
    return LoopState(
        run_id=run_id or new_run_id(),
        task=task.strip(),
        provider=provider_name,
        max_iterations=bounded,
        created_at=now,
        updated_at=now,
    )


def execute(
    state: LoopState,
    provider: Provider,
    runs_root: Path,
    *,
    step_limit: int | None = None,
) -> LoopState:
    runs_root.mkdir(parents=True, exist_ok=True)
    state.halted = False
    save_state(runs_root, state)
    graph = build_graph(provider, runs_root, step_limit=step_limit)
    recursion_limit = (state.max_iterations + 2) * 6
    result = graph.invoke(
        state.model_dump(mode="json"),
        {"recursion_limit": recursion_limit},
    )
    final = LoopState.model_validate(result)
    save_state(runs_root, final)
    return final


def run_task(
    task: str,
    provider: Provider,
    runs_root: Path,
    *,
    max_iterations: int = 4,
    step_limit: int | None = None,
    run_id: str | None = None,
) -> LoopState:
    state = fresh_state(
        task,
        provider.name,
        max_iterations=max_iterations,
        run_id=run_id,
    )
    return execute(state, provider, runs_root, step_limit=step_limit)


def run_demo(
    provider: Provider,
    runs_root: Path,
    *,
    max_iterations: int = 4,
    step_limit: int | None = None,
) -> LoopState:
    return run_task(
        DEMO_TASK,
        provider,
        runs_root,
        max_iterations=max_iterations,
        step_limit=step_limit,
    )


def resume(
    run_id: str,
    provider: Provider,
    runs_root: Path,
    *,
    step_limit: int | None = None,
) -> LoopState:
    state = load_state(runs_root, run_id)
    if state.status in {"done", "failed"} and not state.halted:
        return state
    state.status = "running"
    state.phase = state.phase if state.phase in {"plan", "code", "test", "review"} else "plan"
    return execute(state, provider, runs_root, step_limit=step_limit)
