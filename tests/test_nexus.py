from pathlib import Path
from nexus_h.service import NexusService

def test_decisions_are_deterministic(tmp_path):
    service = NexusService(tmp_path / "test.db")
    expected = {
        "case-100": "CONTINUE", "case-200": "APPROVAL", "case-300": "HANDOFF", "case-400": "CLARIFY",
        "case-401": "HANDOFF", "case-402": "HANDOFF", "case-403": "APPROVAL",
        "case-404": "CONTINUE", "case-405": "APPROVAL", "case-406": "CONTINUE",
        "case-407": "HANDOFF", "case-408": "HANDOFF", "case-409": "CONTINUE", "case-410": "APPROVAL",
    }
    for case_id, action in expected.items():
        assert service.analyze_case(case_id)["action"] == action

def test_handoff_is_idempotent(tmp_path):
    service = NexusService(tmp_path / "test.db")
    first = service.analyze_case("case-300")
    second = service.analyze_case("case-300")
    assert first["handoff"]["id"] == second["handoff"]["id"] == "handoff-case-300"
    assert len(service.queue()) == 1

def test_api_endpoints():
    from app import app
    client = app.test_client()
    assert client.get("/api/health").status_code == 200
    assert len(client.get("/api/cases").json["cases"]) == 14
    assert client.post("/api/cases/case-100/analyze").json["action"] == "CONTINUE"

def test_duplicate_charge_exposes_decision_ready_handoff(tmp_path):
    result = NexusService(tmp_path / "hero.db").analyze_case("case-401")
    assert result["decision"]["decision"] == "HANDOFF"
    assert result["decision"]["risk_level"] == "HIGH"
    assert result["decision"]["confidence"] == 0.94
    assert "Duplicate settled charges detected" in result["decision"]["stop_reasons"]
    assert result["brief"]["evidence_summary"] == result["decision"]["stop_reasons"]
