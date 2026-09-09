# Architecture

The Flask application is a thin HTTP layer over `NexusService`. `fixtures.py` supplies stable synthetic entities; `models.py` contains stdlib dataclasses; `guardrails.py` is a pure deterministic policy function. `service.py` coordinates lookups and persists handoffs/audit events in SQLite using unique keys for idempotency. `agent.py` is an honest optional Strands Agents adapter: status is exposed, but no response is invented without a configured deployment. The frontend is not part of this backend change.
