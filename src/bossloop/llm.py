"""Model providers. Mock is the default. OpenAI and Gemini are used only when a key is set."""

from __future__ import annotations

import ast
import json
import os
import re
from typing import Protocol

import httpx

from bossloop.demo_content import (
    ACCEPTANCE_TESTS,
    BUGGY_MODULE,
    CODER_DRAFT_MESSAGE,
    CODER_FIX_MESSAGE,
    DEMO_BOSS_MESSAGE,
    DEMO_CRITERIA,
    DEMO_PLAN,
    FIXED_MODULE,
    is_demo_task,
)
from bossloop.models import (
    CodeOutput,
    CodeRequest,
    PlanOutput,
    ReviewOutput,
    ReviewRequest,
)
from bossloop.policy import decide_verdict

_MODULE_NAME = re.compile(r"[a-z_][a-z0-9_]{0,30}")
_RESERVED = {"os", "sys", "pytest", "pathlib", "json", "re", "ast", "subprocess"}


class ProviderError(RuntimeError):
    pass


class OfflineTaskError(ProviderError):
    pass


class MissingKeyError(ProviderError):
    pass


class Provider(Protocol):
    name: str

    def plan(self, task: str) -> PlanOutput: ...

    def code(self, request: CodeRequest) -> CodeOutput: ...

    def review(self, request: ReviewRequest) -> ReviewOutput: ...


class MockProvider:
    """Deterministic crew for the rehearsed textkit job. No network, no key."""

    name = "mock"

    def __init__(self) -> None:
        self.plan_calls = 0
        self.code_calls = 0
        self.review_calls = 0

    def plan(self, task: str) -> PlanOutput:
        self.plan_calls += 1
        if not is_demo_task(task):
            raise OfflineTaskError(
                "Offline mode ships one rehearsed job: the textkit module. "
                "Run `bossloop demo`, or set OPENAI_API_KEY or GEMINI_API_KEY "
                "and use `bossloop run` for a custom work order."
            )
        return PlanOutput(
            module_name="textkit",
            plan=DEMO_PLAN,
            acceptance_criteria=list(DEMO_CRITERIA),
            test_code=ACCEPTANCE_TESTS,
            message=DEMO_BOSS_MESSAGE,
        )

    def code(self, request: CodeRequest) -> CodeOutput:
        self.code_calls += 1
        if request.iteration <= 1:
            return CodeOutput(module_code=BUGGY_MODULE, message=CODER_DRAFT_MESSAGE)
        return CodeOutput(module_code=FIXED_MODULE, message=CODER_FIX_MESSAGE)

    def review(self, request: ReviewRequest) -> ReviewOutput:
        self.review_calls += 1
        verdict = decide_verdict(request.report, request.iteration, request.max_iterations)
        failed = [case.name for case in request.report.cases if not case.passed]
        if verdict == "accept":
            message = (
                f"Accepted. The frozen suite is green on iteration {request.iteration}: "
                f"{request.report.summary}. "
                "word_count, unique_words, and is_palindrome match the contract. "
                "This crew is done."
            )
            return ReviewOutput(proposed_verdict="accept", message=message, fix_instructions="")
        if verdict == "abort":
            message = (
                f"Stopped. Iteration {request.iteration} of {request.max_iterations} "
                f"is still red ({request.report.summary}). I will not call this done."
            )
            return ReviewOutput(proposed_verdict="abort", message=message, fix_instructions="")
        names = ", ".join(failed) if failed else request.report.summary
        message = (
            f"Rejected. The suite is red ({request.report.summary}), so the module is not done. "
            "Coder, fix textkit.py only. The acceptance tests stay frozen."
        )
        fix = (
            "Make the failing cases pass without editing the tests. "
            f"Failing: {names}. "
            "Treat punctuation as a separator, store unique words in lowercase, "
            "and compare palindromes on letters and digits only."
        )
        return ReviewOutput(proposed_verdict="revise", message=message, fix_instructions=fix)


class LiveProvider:
    """OpenAI or Gemini via their JSON HTTP APIs. The key stays in the header or query."""

    def __init__(self, backend: str, api_key: str, model: str) -> None:
        if backend not in {"openai", "gemini"}:
            raise ProviderError(f"Unknown backend {backend}")
        self.name = backend
        self.api_key = api_key
        self.model = model

    def plan(self, task: str) -> PlanOutput:
        return self._complete(
            _PLAN_SYSTEM,
            f"Work order:\n{task}",
            PlanOutput,
            _check_plan,
        )

    def code(self, request: CodeRequest) -> CodeOutput:
        report = ""
        if request.last_report is not None:
            report = (
                f"\nLast test report: {request.last_report.summary}\n"
                f"{request.last_report.output[-1500:]}"
            )
        user = (
            f"Module name: {request.module_name}\n"
            f"Iteration: {request.iteration}\n"
            f"Plan:\n{request.plan}\n\n"
            f"Acceptance criteria:\n- " + "\n- ".join(request.acceptance_criteria) + "\n\n"
            f"Frozen tests (do not modify, do not repeat them as the module):\n{request.test_code}\n\n"
            f"Previous module:\n{request.previous_code}\n\n"
            f"Boss instructions:\n{request.fix_instructions}"
            f"{report}"
        )
        return self._complete(_CODE_SYSTEM, user, CodeOutput, _check_code)

    def review(self, request: ReviewRequest) -> ReviewOutput:
        failed = [
            f"{case.name}: {case.message}"
            for case in request.report.cases
            if not case.passed
        ]
        user = (
            f"Iteration {request.iteration} of {request.max_iterations}.\n"
            f"Suite passed: {request.report.passed}.\n"
            f"Summary: {request.report.summary}\n"
            f"Failures:\n" + ("\n".join(failed) if failed else "(none)") + "\n"
            f"Plan:\n{request.plan}\n"
        )
        return self._complete(_REVIEW_SYSTEM, user, ReviewOutput, None)

    def _complete(self, system: str, user: str, model_cls, check):
        prompt_user = user
        last_error = "no response"
        for _ in range(2):
            raw = self._http(system, prompt_user)
            try:
                parsed = model_cls.model_validate(extract_json(raw))
                if check is not None:
                    check(parsed)
                return parsed
            except (ValueError, json.JSONDecodeError, ProviderError) as exc:
                last_error = str(exc)
                prompt_user = (
                    f"{user}\n\nYour previous reply was rejected: {last_error}\n"
                    "Reply with one JSON object and nothing else."
                )
        raise ProviderError(f"{self.name} returned an unusable reply: {last_error}")

    def _http(self, system: str, user: str) -> str:
        try:
            if self.name == "openai":
                return _openai_chat(self.api_key, self.model, system, user)
            return _gemini_chat(self.api_key, self.model, system, user)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name} request failed: {exc}") from exc


def build_provider(choice: str = "auto") -> Provider:
    choice = (choice or "auto").strip().lower()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if choice == "mock":
        return MockProvider()
    if choice == "openai":
        if not openai_key:
            raise MissingKeyError("OPENAI_API_KEY is not set.")
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        return LiveProvider("openai", openai_key, model)
    if choice == "gemini":
        if not gemini_key:
            raise MissingKeyError("GEMINI_API_KEY is not set.")
        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
        return LiveProvider("gemini", gemini_key, model)
    if choice != "auto":
        raise ProviderError(f"Unknown provider {choice!r}. Use auto, mock, openai, or gemini.")
    if openai_key:
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        return LiveProvider("openai", openai_key, model)
    if gemini_key:
        model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
        return LiveProvider("gemini", gemini_key, model)
    return MockProvider()


def extract_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object.")
    return value


def _check_plan(plan: PlanOutput) -> None:
    name = plan.module_name.strip()
    if not _MODULE_NAME.fullmatch(name) or name in _RESERVED:
        raise ValueError(f"module_name must be a safe python identifier, got {name!r}.")
    plan.module_name = name
    _parse_python(plan.test_code, "test_code")
    if "def test_" not in plan.test_code:
        raise ValueError("test_code must contain at least one pytest function.")
    if name not in plan.test_code:
        raise ValueError("test_code must import the module it claims to accept.")
    if not plan.plan.strip() or not plan.message.strip():
        raise ValueError("plan and message are required.")
    if not plan.acceptance_criteria:
        raise ValueError("acceptance_criteria must be a non-empty list.")


def _check_code(code: CodeOutput) -> None:
    if len(code.module_code) > 40_000:
        raise ValueError("module_code is too large.")
    _parse_python(code.module_code, "module_code")
    if not code.message.strip():
        raise ValueError("message is required.")


def _parse_python(source: str, label: str) -> None:
    try:
        ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"{label} is not valid Python: {exc.msg} on line {exc.lineno}") from exc


def _openai_chat(api_key: str, model: str, system: str, user: str) -> str:
    response = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=60,
    )
    if response.status_code >= 400:
        raise ProviderError(f"openai HTTP {response.status_code}: {_safe_body(response)}")
    data = response.json()
    return data["choices"][0]["message"]["content"]


def _gemini_chat(api_key: str, model: str, system: str, user: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    response = httpx.post(
        url,
        params={"key": api_key},
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        },
        timeout=60,
    )
    if response.status_code >= 400:
        raise ProviderError(f"gemini HTTP {response.status_code}: {_safe_body(response)}")
    data = response.json()
    parts = data["candidates"][0]["content"]["parts"]
    return "".join(part.get("text", "") for part in parts)


def _safe_body(response: httpx.Response) -> str:
    text = response.text[:300].replace("\n", " ")
    return text


_PLAN_SYSTEM = """You are the boss of a three-person software crew. You do not write the implementation.
You write the contract: a short plan, acceptance criteria, one Python module name, and a pytest file.
The tests will be frozen. The coder cannot edit them. The tester will execute them.
Reply with one JSON object and nothing else, using exactly these keys:
module_name, plan, acceptance_criteria, test_code, message.
module_name is a lowercase python identifier.
test_code is a complete pytest module that imports module_name and defines def test_ functions.
message is what you say to the crew, in plain sentences. Be strict and specific.
"""

_CODE_SYSTEM = """You are the coder on a three-person crew. You write exactly one Python module.
You cannot change the tests, add files, or add dependencies beyond the Python standard library.
On a later iteration, fix the failures the boss describes. Do not claim the tests passed.
Reply with one JSON object and nothing else, using exactly these keys:
module_code, message.
module_code is the full source of the module. message tells the boss what you changed.
"""

_REVIEW_SYSTEM = """You are a strict boss reviewing a test report. You do not rewrite code.
Propose accept only when the suite passed. Propose revise when it failed and iterations remain.
Propose abort when it failed and the iteration cap is reached.
A separate policy gate will overrule you if you propose the wrong verdict.
Reply with one JSON object and nothing else, using exactly these keys:
proposed_verdict, message, fix_instructions.
proposed_verdict is accept, revise, or abort.
message is plain sentences to the crew. fix_instructions tells the coder what to change, or empty when accepting.
"""
