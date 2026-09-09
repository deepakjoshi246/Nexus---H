"""NEXUS-H dashboard API.

The API is intentionally deterministic by default: model-assisted analysis is
opt-in and never substitutes fabricated model output for a missing credential.
"""
import os

from flask import Flask, jsonify, render_template, request

from nexus_h.service import NexusService

app = Flask(__name__)
service = NexusService()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify(service.health())


@app.get("/api/cases")
def cases():
    return jsonify({"cases": [service.case_view(c) for c in service.list_cases()]})


@app.get("/api/cases/<case_id>")
def case(case_id):
    value = service.get_case(case_id)
    if value is None:
        return jsonify({"error": "case_not_found"}), 404
    return jsonify(service.case_view(value))


@app.get("/api/scenarios")
def scenarios():
    return jsonify({"scenarios": [s.to_dict() for s in service.list_scenarios()]})


@app.post("/api/cases/<case_id>/analyze")
def analyze(case_id):
    payload = request.get_json(silent=True) or {}
    result = service.analyze_case(case_id, payload)
    if result is None:
        return jsonify({"error": "case_not_found"}), 404
    return jsonify(result)


@app.post("/api/analyze-case")
def analyze_case():
    payload = request.get_json(silent=True) or {}
    case_id = payload.get("case_id")
    if not case_id:
        return jsonify({"error": "case_id_required"}), 400
    result = service.analyze_case(case_id, payload)
    if result is None:
        return jsonify({"error": "case_not_found"}), 404
    return jsonify(result)


@app.get("/api/queue")
def queue():
    return jsonify({"items": service.queue()})


@app.get("/api/handoffs/<handoff_id>")
def handoff(handoff_id):
    value = service.handoff_detail(handoff_id)
    if value is None:
        return jsonify({"error": "handoff_not_found"}), 404
    return jsonify(value)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
