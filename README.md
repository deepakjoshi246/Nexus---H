# NEXUS-H

**Context-aware human escalation and resolution engine.**

NEXUS-H is an AI-to-human control layer for billing support. It knows when an agent can continue, when it needs clarification or approval, and when a specialist should take over. The dashboard makes the evidence, decision boundary, route, human brief, and audit trail visible without exposing chain-of-thought.

This repository is a deterministic MVP using synthetic data. Deterministic
business guardrails make the final safety decision; an optional Strands model
advisory can be enabled separately and cannot override that decision.

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
required runtime dependency. Deterministic case analysis works without AWS
credentials. To request an optional Strands model advisory, set
`NEXUS_H_ENABLE_MODEL_ADVISORY=true`; NEXUS-H defaults to Amazon Nova 2 Lite in
`ap-south-1` (Asia Pacific - Mumbai), and enabled advisory requests need AWS
credentials with permission to invoke the configured Bedrock model.

## API

`GET /api/health`, `/api/cases`, `/api/scenarios`, `/api/queue`, `GET /api/handoffs/<id>`, and `POST /api/cases/<id>/analyze` (or `/api/analyze-case` with `{"case_id":"case-100"}`). Decisions are `CONTINUE`, `CLARIFY`, `APPROVAL`, or `HANDOFF`.

Integration routes are `GET /api/integrations`, `POST /api/ring/oauth/token`,
`GET /api/ring/devices`, and `POST /api/ring/webhooks`. Ring account linking
uses `GET /ring/link?time=...&nonce=...`; Cognito sign-in uses
`/auth/login` and `/auth/callback`.

## Strands usage

`nexus_h/agent.py` constructs the required Strands `Agent` with retrieval tools
from `nexus_h/tools.py`. Model calls are disabled by default. Set
`NEXUS_H_ENABLE_MODEL_ADVISORY=true` to invoke Strands during case analysis;
its concise advisory is displayed separately and never changes the
deterministic guardrail decision. Configure `NEXUS_H_MODEL_ID` and
`AWS_REGION`, and grant the runtime role `bedrock:InvokeModel` for the selected
model. If an enabled model request fails, the API reports the failure rather
than silently presenting an advisory-free response as successful. Because the
demo case-analysis endpoints are public, leave this disabled on public
deployments until application authentication and rate limiting are in place.

## Alexa+ and Ring integrations

NEXUS-H includes an Alexa+ integration using a self-hosted MCP server with
Streamable HTTP transport. Start the dashboard with `python app.py`, then start
the MCP server in a second terminal with `python alexa_mcp_server.py`. It
listens on `127.0.0.1:8001/mcp` locally and exposes read-only tools to list
synthetic cases, retrieve case context, preview deterministic analysis, and view
the human queue. Analysis previews do not create handoffs or audit events.
For remote Alexa+ use, deploy the separate MCP web service over HTTPS; do not
expose port 8001 directly to the internet.

The Ring integration uses the official Ring Partner API endpoints for OAuth
token exchange, access-token refresh, device discovery, and signed webhooks.
There is no official Ring Partner SDK. Register a Partner app in the Ring
Developer Portal and configure its token-exchange URL as
`https://<your-domain>/api/ring/oauth/token` and webhook URL as
`https://<your-domain>/api/ring/webhooks`; set the Account Link URL to
`https://<your-domain>/ring/link`. Create an Amazon Cognito user pool with a
hosted UI domain and an app client that has a client secret, authorization-code
grant, `openid` and `email` scopes, and this exact callback URL:
`https://<your-domain>/auth/callback`. Configure `COGNITO_REGION`,
`COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, `COGNITO_CLIENT_SECRET`, and
`COGNITO_REDIRECT_URI` in the runtime environment. Sign-in accepts only a
verified Cognito email address. Set `NEXUS_H_SESSION_SECRET` to a strong random
value; keep secure cookies enabled when using HTTPS. For localhost-only HTTP
testing, set `NEXUS_H_COOKIE_SECURE=false`; never disable secure cookies on a
public deployment.

Set `RING_PARTNER_CLIENT_ID`, `RING_PARTNER_CLIENT_SECRET`,
`RING_TOKEN_ENCRYPTION_KEY`, and `RING_WEBHOOK_SIGNING_KEY` from secure secrets.
Ring uses the signing key for both the webhook HMAC and account-link nonce.
Generate a Fernet encryption key and session secret with:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Ring access and refresh tokens are encrypted in SQLite and shared across
Gunicorn workers. The implementation exchanges the Ring authorization code,
retrieves the Ring account ID, keeps credentials
unclaimed until the authenticated user signs in, verifies Ring's time-limited
HMAC nonce, then performs the required app-integrations POST and PATCH before
enabling device discovery for that Cognito user. Test the complete flow with an
approved Ring Partner app and real device before treating the Ring track as
submission-ready.

## Demo story

Choose **Suspected fraud**, run analysis, and show NEXUS-H retrieving five
evidence sources before the deterministic guardrail stops, routes to
`fraud_specialist`, creates a human brief, and records the audit event. If
model advisory is enabled, it is displayed separately from that decision. Try
**Standard refund**, **Large refund**, and **Missing context** to demonstrate
the other autonomy states.

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

An earlier public deployment ran on an AWS Lightsail instance in Mumbai
(`ap-south-1`) at `http://65.0.130.235`. That IP-only HTTP deployment is not
recommended for hackathon judging or Ring account linking.

For production use, add HTTPS with a domain and certificate, attach an IAM
role or another secure AWS credential mechanism for Bedrock, and replace the
ephemeral SQLite database with managed persistence.

To run the Alexa+ MCP server on Lightsail, create a second systemd service
using the same virtual environment and `.env` file:

```ini
[Unit]
Description=NEXUS-H Alexa+ MCP server
After=network.target
[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/nexus-h
EnvironmentFile=/home/ec2-user/nexus-h/.env
ExecStart=/home/ec2-user/nexus-h/.venv/bin/python /home/ec2-user/nexus-h/alexa_mcp_server.py
Restart=always
[Install]
WantedBy=multi-user.target
```

Reverse-proxy `/mcp` in Nginx to `http://127.0.0.1:8001/mcp`, disable response
buffering for that location, and set `MCP_ALLOWED_HOSTS` to the exact public
domain and port accepted by the proxy. For an Alexa+ remote connection, use a
public HTTPS domain; the current IP-only HTTP deployment is not sufficient.

The Ring Partner integration requires its own approved Ring Developer Portal
app, registered HTTPS token-exchange and webhook URLs, OAuth account linking,
and secure values in `.env`. Keep that file private and set restrictive file
permissions. The current live deployment does not yet have Ring Partner
credentials or HTTPS configured, so Ring device data will remain unavailable
until those prerequisites are completed.

## Render deployment

This repository includes a Render Blueprint for the dashboard and a separate
Alexa+ MCP web service. Push the project to GitHub, choose **New > Blueprint** in
Render, select the repository, and apply the Blueprint. Render builds the
dashboard on port `8080`, checks `/api/health`, and builds the MCP service on
port `10000`. The public MCP endpoint is
`https://nexus-h-mcp.onrender.com/mcp`; configure the Alexa+ client to use that
Streamable HTTP URL. If the Blueprint already exists, sync/apply the new
`nexus-h-mcp` service from Render after the repository update.

The Render free plan may spin down idle services, so allow for a cold start
during judging. Both services use ephemeral `/tmp` SQLite storage. Ring account
linking additionally requires approved Ring Partner credentials, Cognito
configuration, HTTPS callback registration, and a real device/simulator test.
Set those values as Render secrets; never put them in `render.yaml` or GitHub.

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
