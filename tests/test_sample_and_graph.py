import json
from pathlib import Path

from bossloop.graph import build_graph
from bossloop.llm import MockProvider

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_sample_is_a_finished_green_run():
    sample = json.loads((ROOT / "site" / "sample_run.json").read_text(encoding="utf-8"))
    assert sample["status"] == "done"
    assert sample["iteration"] == 2
    assert sample["provider"] == "mock"
    assert sample["last_report"]["passed"] is True
    assert sample["tests_frozen"] is True
    assert sample["snapshots"][0]["report"]["passed"] is False
    assert sample["snapshots"][1]["report"]["passed"] is True
    agents = [entry["agent"] for entry in sample["transcript"]]
    assert agents[:4] == ["boss", "coder", "tester", "boss"]


def test_hosted_health_is_ok_and_does_not_offer_a_runner():
    health = json.loads((ROOT / "site" / "api" / "health.json").read_text(encoding="utf-8"))
    assert health["ok"] is True
    assert health["live_runs"] is False
    page = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    assert 'fetch("/api/health")' in page
    assert "live_runs" in page
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert {"source": "/api/health", "destination": "/api/health.json"} in config["rewrites"]


def test_langgraph_has_the_crew_cycle(tmp_path):
    compiled = build_graph(MockProvider(), tmp_path)
    drawable = compiled.get_graph()
    node_ids = set(drawable.nodes)
    assert {"plan", "code", "test", "review"} <= node_ids
    edges = {(edge.source, edge.target) for edge in drawable.edges}
    assert ("plan", "code") in edges
    assert ("code", "test") in edges
    assert ("test", "review") in edges
    assert ("review", "code") in edges
