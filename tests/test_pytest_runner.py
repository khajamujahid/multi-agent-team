from bossloop.pytest_runner import parse_junit, run_acceptance_suite

JUNIT = """<?xml version="1.0" ?>
<testsuites>
  <testsuite name="pytest" tests="2" failures="1" errors="0">
    <testcase classname="test_textkit" name="test_ok" time="0.01"></testcase>
    <testcase classname="test_textkit" name="test_bad" time="0.01">
      <failure message="assert 1 == 2">trace</failure>
    </testcase>
  </testsuite>
</testsuites>
"""


def test_parse_junit_counts_failures():
    report = parse_junit(JUNIT)
    assert report.passed is False
    assert report.tests == 2
    assert report.failures == 1
    assert report.cases[0].passed is True
    assert report.cases[1].name == "test_textkit::test_bad"
    assert "1 == 2" in report.cases[1].message


def test_suite_runs_in_an_isolated_workspace(tmp_path):
    report = run_acceptance_suite(
        tmp_path,
        "textkit",
        "def add(a, b):\n    return a + b\n",
        "from textkit import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    )
    assert report.passed is True
    assert report.tests == 1
    assert (tmp_path / "textkit.py").exists()
    assert (tmp_path / "test_textkit.py").exists()
