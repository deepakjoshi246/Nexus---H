# Architecture

The Flask application is an HTTP layer over `NexusService`. `fixtures.py` supplies stable synthetic entities; `models.py` contains stdlib dataclasses; `guardrails.py` is a pure deterministic policy function. `service.py` coordinates lookups and persists handoffs/audit events in SQLite using unique keys for idempotency. `agent.py` initializes the required Strands Agents SDK with retrieval tools. Model advisories are opt-in and, when enabled, appear separately; deterministic guardrails always choose the final decision.

`alexa_mcp_server.py` exposes read-only Streamable HTTP tools for synthetic case context and deterministic previews. `nexus_h/integrations/ring.py` performs Ring Partner API token exchange, nonce-verified account linking, encrypted token persistence, and authorized device lookup. Cognito OIDC protects Ring account linking and device access; the synthetic billing dashboard endpoints remain a demo surface and are not production-authenticated.
