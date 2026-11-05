"""Command line for the crew: demo, run, resume, show, and the dashboard."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bossloop import __version__
from bossloop.llm import MissingKeyError, ProviderError, build_provider
from bossloop.models import LoopState
from bossloop.persistence import list_states, load_state, runs_root_from_env
from bossloop.runner import resume, run_demo, run_task


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bossloop",
        description="A strict boss, a coder, and a tester. They loop until the tests pass.",
    )
    parser.add_argument("--version", action="version", version=f"bossloop {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="Run the rehearsed textkit job offline.")
    _add_run_flags(demo)
    demo.add_argument(
        "--publish",
        type=Path,
        default=None,
        help="Also copy the final checkpoint to this path.",
    )

    run = sub.add_parser("run", help="Run a work order. Uses a live model when a key is set.")
    run.add_argument("task", help="What the crew should build.")
    run.add_argument(
        "--provider",
        choices=["auto", "mock", "openai", "gemini"],
        default="auto",
    )
    _add_run_flags(run)

    resume_cmd = sub.add_parser("resume", help="Continue a halted run from its checkpoint.")
    resume_cmd.add_argument("run_id")
    resume_cmd.add_argument(
        "--provider",
        choices=["auto", "mock", "openai", "gemini"],
        default="auto",
    )
    _add_run_flags(resume_cmd, include_iterations=False)

    listing = sub.add_parser("list", help="List checkpoints.")
    _add_runs_dir(listing)

    show = sub.add_parser("show", help="Print one checkpoint as JSON.")
    show.add_argument("run_id")
    _add_runs_dir(show)

    dash = sub.add_parser("dashboard", help="Serve the loop timeline.")
    dash.add_argument("--host", default="127.0.0.1")
    dash.add_argument("--port", type=int, default=8000)
    _add_runs_dir(dash)

    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except (ProviderError, MissingKeyError, FileNotFoundError, ValueError) as exc:
        print(f"bossloop: {exc}", file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "dashboard":
        return _dashboard(args)
    root = runs_root_from_env(args.runs_dir)
    if args.command == "list":
        return _list(root)
    if args.command == "show":
        state = load_state(root, args.run_id)
        print(json.dumps(state.model_dump(mode="json"), indent=2))
        return 0
    if args.command == "demo":
        _load_env()
        state = run_demo(
            build_provider("mock"),
            root,
            max_iterations=args.max_iterations,
        )
        if args.publish:
            _publish(state, args.publish)
        return _finish(state, root)
    if args.command == "run":
        _load_env()
        provider = build_provider(args.provider)
        state = run_task(
            args.task,
            provider,
            root,
            max_iterations=args.max_iterations,
        )
        return _finish(state, root)
    if args.command == "resume":
        _load_env()
        existing = load_state(root, args.run_id)
        choice = args.provider
        if choice == "auto" and existing.provider == "mock":
            choice = "mock"
        state = resume(args.run_id, build_provider(choice), root)
        return _finish(state, root)
    raise AssertionError(args.command)


def _finish(state: LoopState, root: Path) -> int:
    print(render_transcript(state))
    print(f"checkpoint: {root / state.run_id / 'state.json'}")
    return 0 if state.status == "done" else 1


def render_transcript(state: LoopState) -> str:
    lines = [
        f"BossLoop {state.run_id}",
        f"status: {state.status}    iterations: {state.iteration}    provider: {state.provider}",
        "",
    ]
    for entry in state.transcript:
        note = "    policy gate" if entry.override else ""
        lines.append(f"— {entry.agent} · {entry.title} · iteration {entry.iteration}{note}")
        lines.append(entry.body)
        lines.append("")
    if state.last_report is not None:
        lines.append(f"final suite: {state.last_report.summary}")
    return "\n".join(lines).rstrip() + "\n"


def _publish(state: LoopState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )


def _list(root: Path) -> int:
    states = list_states(root)
    if not states:
        print(f"No runs in {root}")
        return 0
    for state in states:
        print(
            f"{state.run_id}  {state.status:8}  iter {state.iteration}  "
            f"{state.provider:8}  {state.updated_at}"
        )
    return 0


def _dashboard(args: argparse.Namespace) -> int:
    _load_env()
    if args.runs_dir is not None:
        import os

        os.environ["BOSSLOOP_RUNS_DIR"] = str(args.runs_dir)
    import uvicorn

    uvicorn.run("bossloop.server:app", host=args.host, port=args.port)
    return 0


def _add_run_flags(parser: argparse.ArgumentParser, *, include_iterations: bool = True) -> None:
    _add_runs_dir(parser)
    if include_iterations:
        parser.add_argument("--max-iterations", type=int, default=4)


def _add_runs_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=None,
        help="Checkpoint directory. Defaults to ./runs or BOSSLOOP_RUNS_DIR.",
    )


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(override=False)
