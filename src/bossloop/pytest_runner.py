"""Run the frozen acceptance suite in an isolated workspace and parse the facts."""

from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from bossloop.models import TestCaseResult, TestReport

PYTEST_TIMEOUT_SECONDS = 30
OUTPUT_LIMIT = 4000
MESSAGE_LIMIT = 500


def materialize_workspace(
    workspace: Path,
    module_name: str,
    module_code: str,
    test_code: str,
) -> Path:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / f"{module_name}.py").write_text(module_code, encoding="utf-8")
    test_path = workspace / f"test_{module_name}.py"
    test_path.write_text(test_code, encoding="utf-8")
    (workspace / "pytest.ini").write_text("[pytest]\ntestpaths = .\n", encoding="utf-8")
    return test_path


def run_acceptance_suite(
    workspace: Path,
    module_name: str,
    module_code: str,
    test_code: str,
) -> TestReport:
    test_path = materialize_workspace(workspace, module_name, module_code, test_code)
    xml_path = workspace / "junit.xml"
    if xml_path.exists():
        xml_path.unlink()
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        str(workspace / "pytest.ini"),
        "--rootdir",
        str(workspace),
        "-q",
        "--tb=line",
        f"--junitxml={xml_path}",
        str(test_path),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=PYTEST_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _as_text(exc.stdout)
        stderr = _as_text(exc.stderr)
        output = _clip(f"{stdout}\n{stderr}")
        return TestReport(
            passed=False,
            tests=0,
            failures=0,
            errors=1,
            summary="pytest timed out",
            output=output,
            cases=[
                TestCaseResult(
                    name="pytest",
                    passed=False,
                    message=f"Timed out after {PYTEST_TIMEOUT_SECONDS}s",
                )
            ],
        )

    output = _clip(f"{completed.stdout}\n{completed.stderr}").replace(str(workspace), ".")
    if xml_path.exists():
        report = parse_junit(xml_path.read_text(encoding="utf-8"))
        report.output = output
        if completed.returncode == 0 and not report.passed:
            report.passed = False
        return report

    return TestReport(
        passed=False,
        tests=0,
        failures=0,
        errors=1,
        summary="pytest did not produce a report",
        output=output,
        cases=[
            TestCaseResult(
                name="pytest",
                passed=False,
                message="No junit report was written.",
            )
        ],
    )


def parse_junit(xml_text: str) -> TestReport:
    root = ET.fromstring(xml_text)
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    cases: list[TestCaseResult] = []
    tests = failures = errors = 0
    for suite in suites:
        tests += int(suite.attrib.get("tests", 0))
        failures += int(suite.attrib.get("failures", 0))
        errors += int(suite.attrib.get("errors", 0))
        for case in suite.findall("testcase"):
            classname = case.attrib.get("classname", "")
            name = case.attrib.get("name", "case")
            label = f"{classname}::{name}" if classname else name
            failure = case.find("failure")
            error = case.find("error")
            problem = failure if failure is not None else error
            if problem is None:
                cases.append(TestCaseResult(name=label, passed=True))
                continue
            detail = problem.attrib.get("message") or (problem.text or "")
            cases.append(
                TestCaseResult(
                    name=label,
                    passed=False,
                    message=_clip(detail.strip(), MESSAGE_LIMIT),
                )
            )
    if tests == 0:
        tests = len(cases)
        failures = sum(1 for case in cases if not case.passed)
    passed = failures == 0 and errors == 0 and tests > 0
    return TestReport(
        passed=passed,
        tests=tests,
        failures=failures,
        errors=errors,
        summary=_summary(tests, failures, errors, passed),
        cases=cases,
    )


def _summary(tests: int, failures: int, errors: int, passed: bool) -> str:
    if passed:
        noun = "test" if tests == 1 else "tests"
        return f"{tests} {noun} passed"
    parts: list[str] = []
    if failures:
        parts.append(f"{failures} failed")
    if errors:
        parts.append(f"{errors} errors")
    green = max(tests - failures - errors, 0)
    parts.append(f"{green} passed")
    parts.append(f"{tests} total")
    return ", ".join(parts)


def _clip(text: str, limit: int = OUTPUT_LIMIT) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[-limit:]


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
