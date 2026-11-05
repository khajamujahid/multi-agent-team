"""LangGraph cycle: plan → code → test → review → code … until the boss can close it."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from bossloop.llm import Provider, ProviderError
from bossloop.models import (
    CodeRequest,
    IterationSnapshot,
    LoopState,
    ReviewRequest,
    TranscriptEntry,
)
from bossloop.persistence import save_state, utcnow
from bossloop.policy import compose_review
from bossloop.pytest_runner import run_acceptance_suite


class GraphState(TypedDict, total=False):
    schema_version: int
    run_id: str
    task: str
    provider: str
    phase: str
    status: str
    iteration: int
    max_iterations: int
    plan: str
    acceptance_criteria: list
    module_name: str
    module_code: str
    test_code: str
    tests_frozen: bool
    fix_instructions: str
    last_report: dict | None
    transcript: list
    snapshots: list
    error: str
    halted: bool
    step: int
    created_at: str
    updated_at: str


def build_graph(provider: Provider, runs_root: Path, *, step_limit: int | None = None):
    """Compile the crew graph.

    step_limit pauses after that many nodes by setting halted. The saved phase
    is the node to run on resume. The policy gate inside review is what ends a run.
    """

    budget = {"n": 0}

    def wrap(node_name: str, fn):
        def inner(state: GraphState) -> GraphState:
            updated = fn(dict(state))
            budget["n"] += 1
            updated["step"] = int(updated.get("step", 0)) + 1
            updated["updated_at"] = utcnow()
            updated["halted"] = step_limit is not None and budget["n"] >= step_limit
            model = LoopState.model_validate(updated)
            save_state(runs_root, model, node=node_name)
            return model.model_dump(mode="json")

        return inner

    def plan_node(raw: dict) -> dict:
        state = LoopState.model_validate(raw)
        try:
            plan = provider.plan(state.task)
        except ProviderError as exc:
            return _fail(state, str(exc))
        state.module_name = plan.module_name
        state.plan = plan.plan.strip()
        state.acceptance_criteria = [item.strip() for item in plan.acceptance_criteria if item.strip()]
        state.test_code = plan.test_code
        state.tests_frozen = True
        state.phase = "code"
        _say(
            state,
            agent="boss",
            phase="plan",
            title="Contract frozen",
            body=_plan_body(state, plan.message),
        )
        return state.model_dump(mode="json")

    def code_node(raw: dict) -> dict:
        state = LoopState.model_validate(raw)
        state.iteration += 1
        request = CodeRequest(
            task=state.task,
            plan=state.plan,
            acceptance_criteria=state.acceptance_criteria,
            module_name=state.module_name,
            test_code=state.test_code,
            iteration=state.iteration,
            previous_code=state.module_code,
            fix_instructions=state.fix_instructions,
            last_report=state.last_report,
        )
        try:
            written = provider.code(request)
        except ProviderError as exc:
            return _fail(state, str(exc))
        state.module_code = written.module_code
        state.phase = "test"
        title = "Module submitted" if state.iteration == 1 else f"Revision {state.iteration} submitted"
        _say(state, agent="coder", phase="code", title=title, body=written.message.strip())
        return state.model_dump(mode="json")

    def test_node(raw: dict) -> dict:
        state = LoopState.model_validate(raw)
        workspace = runs_root / state.run_id / "workspace"
        report = run_acceptance_suite(
            workspace,
            state.module_name,
            state.module_code,
            state.test_code,
        )
        state.last_report = report
        state.snapshots.append(
            IterationSnapshot(
                iteration=state.iteration,
                module_code=state.module_code,
                report=report,
            )
        )
        state.phase = "review"
        title = "Suite green" if report.passed else "Suite red"
        _say(state, agent="tester", phase="test", title=title, body=_tester_body(report))
        return state.model_dump(mode="json")

    def review_node(raw: dict) -> dict:
        state = LoopState.model_validate(raw)
        if state.last_report is None:
            return _fail(state, "Review started with no test report.")
        request = ReviewRequest(
            task=state.task,
            plan=state.plan,
            acceptance_criteria=state.acceptance_criteria,
            module_name=state.module_name,
            iteration=state.iteration,
            max_iterations=state.max_iterations,
            report=state.last_report,
        )
        try:
            proposed = provider.review(request)
        except ProviderError as exc:
            return _fail(state, str(exc))
        verdict, message, fix, override = compose_review(
            proposed,
            state.last_report,
            state.iteration,
            state.max_iterations,
        )
        if verdict == "accept":
            state.phase = "done"
            state.status = "done"
            state.fix_instructions = ""
            title = "Accepted"
        elif verdict == "abort":
            state.phase = "failed"
            state.status = "failed"
            state.error = state.last_report.summary
            state.fix_instructions = ""
            title = "Stopped"
        else:
            state.phase = "code"
            state.fix_instructions = fix
            title = "Revise the module"
        _say(
            state,
            agent="boss",
            phase="review",
            title=title,
            body=message,
            override=override,
        )
        return state.model_dump(mode="json")

    builder = StateGraph(GraphState)
    builder.add_node("plan", wrap("plan", plan_node))
    builder.add_node("code", wrap("code", code_node))
    builder.add_node("test", wrap("test", test_node))
    builder.add_node("review", wrap("review", review_node))
    builder.add_conditional_edges(
        START,
        _entry,
        {"plan": "plan", "code": "code", "test": "test", "review": "review", "end": END},
    )
    builder.add_conditional_edges("plan", _after_plan, {"code": "code", "end": END})
    builder.add_conditional_edges("code", _after_code, {"test": "test", "end": END})
    builder.add_conditional_edges("test", _after_test, {"review": "review", "end": END})
    builder.add_conditional_edges("review", _after_review, {"code": "code", "end": END})
    return builder.compile()


def _entry(state: GraphState) -> str:
    phase = state.get("phase", "plan")
    if phase in {"plan", "code", "test", "review"}:
        return phase
    return "end"


def _after_plan(state: GraphState) -> str:
    if state.get("halted") or state.get("phase") != "code":
        return "end"
    return "code"


def _after_code(state: GraphState) -> str:
    if state.get("halted") or state.get("phase") != "test":
        return "end"
    return "test"


def _after_test(state: GraphState) -> str:
    if state.get("halted") or state.get("phase") != "review":
        return "end"
    return "review"


def _after_review(state: GraphState) -> str:
    if state.get("halted"):
        return "end"
    if state.get("phase") == "code":
        return "code"
    return "end"


def _say(
    state: LoopState,
    *,
    agent: str,
    phase: str,
    title: str,
    body: str,
    override: bool = False,
) -> None:
    state.transcript.append(
        TranscriptEntry(
            id=len(state.transcript) + 1,
            agent=agent,  # type: ignore[arg-type]
            phase=phase,  # type: ignore[arg-type]
            iteration=state.iteration,
            title=title,
            body=body.strip(),
            created_at=utcnow(),
            override=override,
        )
    )


def _fail(state: LoopState, message: str) -> dict[str, Any]:
    state.status = "failed"
    state.phase = "failed"
    state.error = message
    _say(state, agent="boss", phase="failed", title="Stopped", body=message)
    return state.model_dump(mode="json")


def _plan_body(state: LoopState, message: str) -> str:
    criteria = "\n".join(f"- {item}" for item in state.acceptance_criteria)
    return f"{message.strip()}\n\nPlan: {state.plan}\n\nAcceptance criteria:\n{criteria}"


def _tester_body(report) -> str:
    lines = [
        f"I ran the frozen acceptance suite in a clean workspace. {report.summary}.",
        "",
    ]
    for case in report.cases:
        mark = "PASS" if case.passed else "FAIL"
        lines.append(f"[{mark}] {case.name}")
        if case.message:
            lines.append(f"    {case.message.splitlines()[0][:300]}")
    return "\n".join(lines)
