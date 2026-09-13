# Architecture

The Flask application is a thin HTTP layer over `NexusService`. `fixtures.py` supplies stable synthetic entities; `models.py` contains stdlib dataclasses; `guardrails.py` is a pure deterministic policy function. `service.py` coordinates lookups and persists handoffs/audit events in SQLite using unique keys for idempotency. `agent.py` initializes the required Strands Agents SDK with retrieval tools. Strands retrieves and interprets context, while deterministic guardrails enforce the final safety decision. The frontend is not part of this backend change.
