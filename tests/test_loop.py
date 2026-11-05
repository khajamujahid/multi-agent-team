import json

from bossloop.demo_content import DEMO_TASK
from bossloop.llm import MockProvider, OfflineTaskError, build_provider
from bossloop.models import CodeOutput, CodeRequest, PlanOutput, ReviewOutput, ReviewRequest
from bossloop.persistence import load_state
from bossloop.runner import resume, run_demo, run_task


def test_auto_provider_is_mock_without_keys(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert build_provider("auto").name == "mock"


def test_offline_demo_fails_then_passes(tmp_path):
    provider = MockProvider()
    state = run_demo(provider, tmp_path)

    assert state.status == "done"
    assert state.iteration == 2
    assert state.last_report is not None
    assert state.last_report.passed is True
    assert state.tests_frozen is True
    assert provider.plan_calls == 1
    assert provider.code_calls == 2

    titles = [entry.title for entry in state.transcript]
    assert titles[0] == "Contract frozen"
    assert "Suite red" in titles
    assert "Revise the module" in titles
    assert titles[-2] == "Suite green"
    assert titles[-1] == "Accepted"

    assert state.snapshots[0].report.passed is False
    assert state.snapshots[1].report.passed is True
    assert "def _words" not in state.snapshots[0].module_code
    assert "def _words" in state.snapshots[1].module_code

    reloaded = load_state(tmp_path, state.run_id)
    assert reloaded.status == "done"
    assert (tmp_path / state.run_id / "steps" / "01-plan.json").exists()
    assert (tmp_path / state.run_id / "workspace" / "test_textkit.py").read_text() == state.test_code


def test_iteration_cap_stops_without_calling_it_done(tmp_path):
    state = run_demo(MockProvider(), tmp_path, max_iterations=1)
    assert state.status == "failed"
    assert state.iteration == 1
    assert state.last_report is not None
    assert state.last_report.passed is False
    assert state.transcript[-1].title == "Stopped"
    assert state.phase == "failed"


def test_policy_gate_blocks_a_boss_who_wants_to_ship_red(tmp_path):
    class NaughtyBoss(MockProvider):
        name = "mock"

        def review(self, request: ReviewRequest) -> ReviewOutput:
            self.review_calls += 1
            return ReviewOutput(
                proposed_verdict="accept",
                message="Ship it. I did not look.",
                fix_instructions="",
            )

    provider = NaughtyBoss()
    state = run_demo(provider, tmp_path)
    assert state.status == "done"
    assert state.iteration == 2
    revise = next(entry for entry in state.transcript if entry.title == "Revise the module")
    assert revise.override is True
    assert "Policy gate" in revise.body


def test_resume_continues_from_the_checkpoint(tmp_path):
    provider = MockProvider()
    paused = run_demo(provider, tmp_path, step_limit=2)
    assert paused.halted is True
    assert paused.status == "running"
    assert paused.phase == "test"
    assert paused.iteration == 1
    assert provider.plan_calls == 1
    assert provider.code_calls == 1

    follower = MockProvider()
    finished = resume(paused.run_id, follower, tmp_path)
    assert finished.status == "done"
    assert finished.halted is False
    assert finished.last_report is not None
    assert finished.last_report.passed is True
    assert follower.plan_calls == 0
    assert follower.code_calls == 1


def test_unknown_offline_task_fails_cleanly(tmp_path):
    state = run_task("Build a web server.", MockProvider(), tmp_path)
    assert state.status == "failed"
    assert "textkit" in state.error
    assert isinstance(state.error, str)


def test_mock_plan_rejects_unknown_task_directly():
    try:
        MockProvider().plan("something else")
    except OfflineTaskError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("expected OfflineTaskError")


def test_custom_shapes_still_validate():
    plan = PlanOutput(
        module_name="textkit",
        plan="plan",
        acceptance_criteria=["a"],
        test_code="def test_x():\n    assert True\n",
        message="ok",
    )
    code = CodeOutput(module_code="x = 1\n", message="wrote it")
    request = CodeRequest(
        task=DEMO_TASK,
        plan=plan.plan,
        acceptance_criteria=plan.acceptance_criteria,
        module_name="textkit",
        test_code=plan.test_code,
        iteration=1,
    )
    assert request.module_name == "textkit"
    assert "x = 1" in code.module_code


def test_checkpoint_json_is_plain(tmp_path):
    state = run_demo(MockProvider(), tmp_path, max_iterations=1)
    raw = json.loads((tmp_path / state.run_id / "state.json").read_text())
    assert raw["schema_version"] == 1
    assert raw["module_name"] == "textkit"
