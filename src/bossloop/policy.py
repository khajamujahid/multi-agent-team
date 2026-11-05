"""The boss may propose. The gate disposes.

A red acceptance suite cannot be marked done, and a green suite cannot be
rejected. That rule lives in code so a model's wording cannot overrule it.
"""

from __future__ import annotations

from bossloop.models import ReviewOutput, TestReport, Verdict


def decide_verdict(report: TestReport, iteration: int, max_iterations: int) -> Verdict:
    if report.passed:
        return "accept"
    if iteration >= max_iterations:
        return "abort"
    return "revise"


def compose_review(
    proposed: ReviewOutput,
    report: TestReport,
    iteration: int,
    max_iterations: int,
) -> tuple[Verdict, str, str, bool]:
    verdict = decide_verdict(report, iteration, max_iterations)
    override = proposed.proposed_verdict != verdict
    message = proposed.message.strip() or "Review recorded."
    if override and verdict == "revise":
        message += (
            "\n\nPolicy gate: a red suite cannot be accepted. "
            "The coder will revise the module. The tests stay frozen."
        )
    elif override and verdict == "abort":
        message += (
            "\n\nPolicy gate: the iteration cap is spent and the suite is still red. "
            "This run is stopped, and it is not done."
        )
    elif override and verdict == "accept":
        message += (
            "\n\nPolicy gate: the frozen suite is green, so the work is accepted."
        )

    fix = proposed.fix_instructions.strip()
    if verdict == "revise" and not fix:
        failed = [case for case in report.cases if not case.passed]
        lines = [report.summary]
        for case in failed:
            detail = case.message.splitlines()[0] if case.message else ""
            lines.append(f"- {case.name}: {detail}".rstrip())
        fix = "\n".join(lines)
    return verdict, message, fix, override
