from bossloop.models import ReviewOutput
from bossloop.models import TestCaseResult as CaseResult
from bossloop.models import TestReport as Report
from bossloop.policy import compose_review, decide_verdict


def _report(passed: bool) -> Report:
    return Report(
        passed=passed,
        tests=1,
        failures=0 if passed else 1,
        errors=0,
        summary="1 test passed" if passed else "1 failed, 0 passed, 1 total",
        cases=[
            CaseResult(
                name="test_textkit::test_word_count",
                passed=passed,
                message="" if passed else "assert 1 == 2",
            )
        ],
    )


def test_red_suite_cannot_be_accepted():
    verdict, message, fix, override = compose_review(
        ReviewOutput(proposed_verdict="accept", message="Ship it.", fix_instructions=""),
        _report(False),
        iteration=1,
        max_iterations=4,
    )
    assert verdict == "revise"
    assert override is True
    assert "Policy gate" in message
    assert "test_word_count" in fix


def test_green_suite_cannot_be_rejected():
    verdict, message, _fix, override = compose_review(
        ReviewOutput(proposed_verdict="revise", message="One more pass.", fix_instructions="tweak"),
        _report(True),
        iteration=2,
        max_iterations=4,
    )
    assert verdict == "accept"
    assert override is True
    assert "green" in message


def test_cap_aborts_a_red_suite():
    assert decide_verdict(_report(False), iteration=4, max_iterations=4) == "abort"
    verdict, message, _fix, override = compose_review(
        ReviewOutput(proposed_verdict="revise", message="Keep going.", fix_instructions=""),
        _report(False),
        iteration=4,
        max_iterations=4,
    )
    assert verdict == "abort"
    assert override is True
    assert "cap" in message
