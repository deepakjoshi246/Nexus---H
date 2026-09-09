# NEXUS-H

**Context-aware human escalation and resolution engine.**

NEXUS-H is an AI-to-human control layer for billing support. It knows when an agent can continue, when it needs clarification or approval, and when a specialist should take over. The dashboard makes the evidence, decision boundary, route, human brief, and audit trail visible without exposing chain-of-thought.

This repository is a deterministic MVP using synthetic data. The business guardrails remain authoritative; the optional Strands adapter is enabled only when the SDK and model credentials are configured.

## What is implemented

- Case inbox and deterministic demo scenarios
- Tool-driven retrieval of case, conversation, customer, transaction, and policy context
- Four autonomy states: `CONTINUE`, `CLARIFY`, `APPROVAL`, and `HANDOFF`
- Risk/uncertainty/policy/emotion/complexity/authority signals
- Skill-aware specialist routing and idempotent handoffs
- Decision-ready human brief and sanitized audit timeline
- SQLite persistence for local handoffs and audit events
- Unit/API tests for the guardrail workflow

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000` for the dashboard. No credentials are required for deterministic demo mode. The optional Strands adapter reports its status at `/api/health`; it never fabricates model output when unavailable.

## API

`GET /api/health`, `/api/cases`, `/api/scenarios`, `/api/queue`, `GET /api/handoffs/<id>`, and `POST /api/cases/<id>/analyze` (or `/api/analyze-case` with `{"case_id":"case-100"}`). Decisions are `CONTINUE`, `CLARIFY`, `APPROVAL`, or `HANDOFF`.

## Strands usage

When enabled, `nexus_h/agent.py` constructs a Strands `Agent` with retrieval tools from `nexus_h/tools.py`. Model output is advisory only: deterministic guardrails and typed decision handling remain in control. Without a configured deployment, the same tool-backed deterministic workflow powers the demo.

## Demo story

Choose **Suspected fraud**, run analysis, and show the agent retrieving five evidence sources before it stops, routes to `fraud_specialist`, creates a human brief, and records the audit event. Try **Standard refund**, **Large refund**, and **Missing context** to demonstrate the other autonomy states.

## Tests

```powershell
python -m pytest -q
```

## AWS App Runner deployment

The repository includes a production WSGI container in `Dockerfile`. To deploy
with AWS App Runner, push this repository to a source repository and create an
App Runner service from that repository with:

- Port: `8080`
- Start command: the Dockerfile default command
- Health check path: `/api/health`
- Environment: `NEXUS_H_DB_PATH=/tmp/nexus_h.db`

The MVP stores handoffs and audit events in SQLite, so local container storage
is ephemeral. Use a managed database before production use. The deterministic
demo does not require secrets. If enabling Strands, configure credentials using
AWS IAM/role configuration rather than committing them.

## Render deployment

This repository includes `render.yaml`. Push the project to GitHub, choose
**New > Blueprint** in Render, select the repository, and deploy. Render will
build the Docker image, expose port `8080`, and use `/api/health` for health
checks. The resulting HTTPS URL can be opened by anyone on a phone or laptop.

## Sharing a downloadable copy

For offline/local use, share the project ZIP. The recipient needs Python 3.10+
and runs:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

They then open `http://127.0.0.1:5000`. This local copy uses synthetic data and
does not require cloud credentials.
