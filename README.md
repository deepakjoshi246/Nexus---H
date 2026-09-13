# NEXUS-H

**Context-aware human escalation and resolution engine.**

NEXUS-H is an AI-to-human control layer for billing support. It knows when an agent can continue, when it needs clarification or approval, and when a specialist should take over. The dashboard makes the evidence, decision boundary, route, human brief, and audit trail visible without exposing chain-of-thought.

This repository is a deterministic MVP using synthetic data. Strands retrieves and interprets context, while deterministic business guardrails remain authoritative for the final safety decision.

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

Open `http://127.0.0.1:5000` for the dashboard. The Strands Agents SDK is a
required runtime dependency. NEXUS-H defaults to Amazon Nova 2 Lite in
`ap-south-1` (Asia Pacific - Mumbai). Local or deployed analysis runs need AWS
credentials with permission to invoke the configured Bedrock model.

## API

`GET /api/health`, `/api/cases`, `/api/scenarios`, `/api/queue`, `GET /api/handoffs/<id>`, and `POST /api/cases/<id>/analyze` (or `/api/analyze-case` with `{"case_id":"case-100"}`). Decisions are `CONTINUE`, `CLARIFY`, `APPROVAL`, or `HANDOFF`.

## Strands usage

`nexus_h/agent.py` constructs the required Strands `Agent` with retrieval tools
from `nexus_h/tools.py`. Model output is advisory only: deterministic
guardrails and typed decision handling remain in control. Configure
`NEXUS_H_MODEL_ID` and `AWS_REGION`, and grant the runtime role
`bedrock:InvokeModel` for the selected model.

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
- Environment: `AWS_REGION=ap-south-1`
- Environment: `NEXUS_H_MODEL_ID=amazon.nova-2-lite-v1:0`

The MVP stores handoffs and audit events in SQLite, so local container storage
is ephemeral. Use a managed database before production use. Attach an App
Runner instance role granting `bedrock:InvokeModel` instead of committing
AWS access keys.

## AWS Lightsail deployment

The current public deployment runs on an AWS Lightsail instance in Mumbai
(`ap-south-1`). Open the live dashboard at
`http://65.0.130.235`. The instance runs Amazon Linux 2023, Python 3.11,
Gunicorn, and Nginx, with `NEXUS_H_MODEL_ID=amazon.nova-2-lite-v1:0`.

For production use, add HTTPS with a domain and certificate, attach an IAM
role or another secure AWS credential mechanism for Bedrock, and replace the
ephemeral SQLite database with managed persistence.

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
the dashboard and deterministic workflows are local, but Strands-backed
analysis requires AWS credentials with `bedrock:InvokeModel` permission.

## Install as an app

The hosted dashboard is also a Progressive Web App (PWA), so the same link works
across iOS, Android, macOS, and Windows:

- **iPhone/iPad:** open the link in Safari, tap **Share**, then **Add to Home Screen**.
- **Android:** open it in Chrome, tap the menu, then **Install app** or **Add to Home screen**.
- **macOS/Windows:** open it in Chrome or Edge and use the install icon in the address bar, or choose **Install NEXUS-H** from the browser menu.

The app shell is cached for faster repeat launches. Live case data still requires
an internet connection.

The dashboard header includes a **Download app** button. On supported browsers it
opens the native install prompt; on iOS and other browsers it shows the matching
manual installation instruction.
