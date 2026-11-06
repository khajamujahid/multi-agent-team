from fastapi.testclient import TestClient

from bossloop.cli import main
from bossloop.server import create_app


def test_cli_demo_exits_green(tmp_path, capsys):
    code = main(["demo", "--runs-dir", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 0
    assert "Accepted" in captured.out
    assert "status: done" in captured.out
    listed = main(["list", "--runs-dir", str(tmp_path)])
    listing = capsys.readouterr().out
    assert listed == 0
    assert "done" in listing


def test_cli_demo_can_publish(tmp_path):
    target = tmp_path / "site" / "sample_run.json"
    code = main(["demo", "--runs-dir", str(tmp_path / "runs"), "--publish", str(target)])
    assert code == 0
    text = target.read_text()
    assert '"status": "done"' in text


def test_dashboard_api_runs_the_demo(tmp_path, monkeypatch):
    monkeypatch.setenv("BOSSLOOP_RUNS_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = TestClient(create_app())
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True
    page = client.get("/")
    assert page.status_code == 200
    assert "BossLoop" in page.text
    script = client.get("/playback.js")
    assert script.status_code == 200
    assert "playbackFinished" in script.text
    started = client.post("/api/runs", json={"demo": True, "max_iterations": 4})
    assert started.status_code == 200
    body = started.json()
    assert body["status"] == "done"
    assert body["last_report"]["passed"] is True
    fetched = client.get(f"/api/runs/{body['run_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["iteration"] == 2
