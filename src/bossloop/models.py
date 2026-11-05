"""Pydantic contracts for crew state and every agent's input and output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AgentName = Literal["boss", "coder", "tester"]
Phase = Literal["plan", "code", "test", "review", "done", "failed"]
RunStatus = Literal["running", "done", "failed"]
Verdict = Literal["accept", "revise", "abort"]


class TranscriptEntry(BaseModel):
    id: int
    agent: AgentName
    phase: Phase
    iteration: int
    title: str
    body: str
    created_at: str
    override: bool = False


class TestCaseResult(BaseModel):
    name: str
    passed: bool
    message: str = ""


class TestReport(BaseModel):
    passed: bool
    tests: int = 0
    failures: int = 0
    errors: int = 0
    summary: str
    output: str = ""
    cases: list[TestCaseResult] = Field(default_factory=list)


class IterationSnapshot(BaseModel):
    iteration: int
    module_code: str
    report: TestReport


class LoopState(BaseModel):
    """Full checkpoint. Written to disk after every node so a run can resume."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    run_id: str
    task: str
    provider: str
    phase: Phase = "plan"
    status: RunStatus = "running"
    iteration: int = 0
    max_iterations: int = 4
    plan: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    module_name: str = "textkit"
    module_code: str = ""
    test_code: str = ""
    tests_frozen: bool = False
    fix_instructions: str = ""
    last_report: TestReport | None = None
    transcript: list[TranscriptEntry] = Field(default_factory=list)
    snapshots: list[IterationSnapshot] = Field(default_factory=list)
    error: str = ""
    halted: bool = False
    step: int = 0
    created_at: str
    updated_at: str


class PlanOutput(BaseModel):
    module_name: str
    plan: str
    acceptance_criteria: list[str]
    test_code: str
    message: str


class CodeRequest(BaseModel):
    task: str
    plan: str
    acceptance_criteria: list[str]
    module_name: str
    test_code: str
    iteration: int
    previous_code: str = ""
    fix_instructions: str = ""
    last_report: TestReport | None = None


class CodeOutput(BaseModel):
    module_code: str
    message: str


class ReviewRequest(BaseModel):
    task: str
    plan: str
    acceptance_criteria: list[str]
    module_name: str
    iteration: int
    max_iterations: int
    report: TestReport
    fix_instructions: str = ""


class ReviewOutput(BaseModel):
    proposed_verdict: Verdict
    message: str
    fix_instructions: str = ""
