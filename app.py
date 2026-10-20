"""NEXUS-H dashboard API.

The API is intentionally deterministic by default: model-assisted analysis is
opt-in and never substitutes fabricated model output for a missing credential.
"""
import os
import re
from datetime import timedelta

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.flask_client import OAuth
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from nexus_h.agent import StrandsAnalysisError
from nexus_h.service import NexusService
from nexus_h.integrations.ring import (
    RingIntegrationError,
    RingPartnerClient,
    ring_api_configured,
    ring_link_timestamp_valid,
    verify_webhook_signature,
)

app = Flask(__name__)
app.secret_key = os.getenv("NEXUS_H_SESSION_SECRET")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("NEXUS_H_COOKIE_SECURE", "true").lower()
    in {"1", "true", "yes"},
    MAX_CONTENT_LENGTH=int(os.getenv("NEXUS_H_MAX_CONTENT_LENGTH", "65536")),
)
app.permanent_session_lifetime = timedelta(hours=8)
service = NexusService()
ring_client = RingPartnerClient(service.db_path)
oauth = OAuth(app)

COGNITO_REGION = os.getenv("COGNITO_REGION") or os.getenv("AWS_REGION", "")
COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "")
COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID", "")
COGNITO_CLIENT_SECRET = os.getenv("COGNITO_CLIENT_SECRET", "")
COGNITO_REDIRECT_URI = os.getenv("COGNITO_REDIRECT_URI", "")
if all((COGNITO_REGION, COGNITO_USER_POOL_ID, COGNITO_CLIENT_ID, COGNITO_CLIENT_SECRET)):
    oauth.register(
        name="cognito",
        server_metadata_url=(
            f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/"
            f"{COGNITO_USER_POOL_ID}/.well-known/openid-configuration"
        ),
        client_id=COGNITO_CLIENT_ID,
        client_secret=COGNITO_CLIENT_SECRET,
        client_kwargs={"scope": "openid email", "code_challenge_method": "S256"},
    )


def cognito_configured():
    return bool(
        app.secret_key
        and all((
            COGNITO_REGION,
            COGNITO_USER_POOL_ID,
            COGNITO_CLIENT_ID,
            COGNITO_CLIENT_SECRET,
            COGNITO_REDIRECT_URI,
        ))
    )


def current_user():
    user = session.get("nexus_user")
    return user if isinstance(user, dict) else None


def _finish_ring_link():
    pending = session.get("ring_link_pending")
    user = current_user()
    if not pending or not user:
        return None
    try:
        ring_client.complete_account_link(
            pending["time"],
            pending["nonce"],
            user["email"],
            user["sub"],
            os.getenv("RING_WEBHOOK_SIGNING_KEY", ""),
        )
    except RingIntegrationError as error:
        app.logger.warning("Ring account linking failed: %s", error)
        return jsonify({"error": "ring_account_link_failed", "message": str(error)}), 400
    session.pop("ring_link_pending", None)
    return redirect(url_for("index", ring_link="complete"))


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify(service.health())


@app.get("/api/integrations")
def integrations():
    user = current_user()
    return jsonify({
        "alexa_plus": {
            "type": "mcp_streamable_http",
            "endpoint": "/mcp",
            "configured": True,
        },
        "ring": {
            "type": "ring_partner_api",
            "configured": ring_api_configured(),
            "linked": bool(user and ring_client.has_linked_account(user.get("sub"))),
            "account_linking_implemented": True,
            "webhook_signing_configured": bool(os.getenv("RING_WEBHOOK_SIGNING_KEY")),
            "user_authenticated": bool(user),
            "cognito_configured": cognito_configured(),
            "token_exchange_endpoint": "/api/ring/oauth/token",
            "account_link_endpoint": "/ring/link",
            "device_endpoint": "/api/ring/devices",
            "webhook_endpoint": "/api/ring/webhooks",
        },
    })


@app.get("/auth/login")
def auth_login():
    if not cognito_configured():
        return jsonify({
            "error": "cognito_not_configured",
            "message": "Configure the Cognito user pool, app client, redirect URI, and session secret.",
        }), 503
    return oauth.cognito.authorize_redirect(redirect_uri=COGNITO_REDIRECT_URI)


@app.get("/auth/callback")
def auth_callback():
    if not cognito_configured():
        return jsonify({"error": "cognito_not_configured"}), 503
    try:
        token = oauth.cognito.authorize_access_token()
        user = token.get("userinfo") or oauth.cognito.userinfo(token=token)
    except OAuthError as error:
        app.logger.warning("Cognito sign-in failed: %s", error)
        return jsonify({"error": "cognito_sign_in_failed"}), 401
    subject = user.get("sub") if isinstance(user, dict) else None
    email = user.get("email") if isinstance(user, dict) else None
    email_verified = user.get("email_verified") if isinstance(user, dict) else False
    if (
        not isinstance(subject, str)
        or not subject
        or not isinstance(email, str)
        or not email
        or email_verified not in (True, "true")
    ):
        return jsonify({"error": "verified_cognito_identity_required"}), 403
    pending = session.get("ring_link_pending")
    session.clear()
    session["nexus_user"] = {"sub": subject, "email": email}
    session.permanent = True
    if pending:
        session["ring_link_pending"] = pending
        result = _finish_ring_link()
        if result is not None:
            return result
    return redirect("/")


@app.get("/auth/logout")
def auth_logout():
    session.clear()
    return redirect("/")


@app.get("/ring/link")
def ring_account_link():
    time_param = request.args.get("time", "")
    nonce = request.args.get("nonce", "")
    if not re.fullmatch(r"[0-9]{13}", time_param) or not re.fullmatch(
        r"[A-Za-z0-9_-]{43}", nonce
    ):
        return jsonify({"error": "invalid_ring_link_parameters"}), 400
    if not ring_link_timestamp_valid(time_param):
        return jsonify({"error": "ring_link_request_expired"}), 400
    if not ring_api_configured() or not os.getenv("RING_WEBHOOK_SIGNING_KEY"):
        return jsonify({
            "error": "ring_not_configured",
            "message": "Configure the Ring Partner credentials, encryption key, and signing key.",
        }), 503
    if not current_user():
        if not cognito_configured():
            return jsonify({"error": "cognito_not_configured"}), 503
        session["ring_link_pending"] = {"time": time_param, "nonce": nonce}
        return redirect(url_for("auth_login"))
    session["ring_link_pending"] = {"time": time_param, "nonce": nonce}
    result = _finish_ring_link()
    if result is not None:
        return result
    return jsonify({"error": "ring_link_failed"}), 400


@app.post("/api/ring/oauth/token")
def ring_token_exchange():
    if not ring_api_configured():
        return jsonify({"error": "ring_not_configured"}), 503
    payload = request.get_json(silent=True) if request.is_json else request.form
    code = payload.get("code") if isinstance(payload, dict) else None
    if not isinstance(code, str) or not code or len(code) > 4096:
        return jsonify({"error": "ring_authorization_code_required"}), 400
    try:
        result = ring_client.exchange_authorization_code(code)
    except RingIntegrationError as error:
        app.logger.warning("Ring OAuth token exchange failed: %s", error)
        return jsonify({"error": "ring_oauth_failed", "message": str(error)}), 502
    return jsonify(result), 200


@app.get("/api/ring/devices")
def ring_devices():
    if not ring_api_configured():
        return jsonify({
            "error": "ring_not_configured",
            "message": (
                "Register a Ring Partner app and configure its client credentials "
                "and token encryption key."
            ),
        }), 503
    user = current_user()
    if not user:
        return jsonify({"error": "authentication_required"}), 401
    if not ring_client.has_linked_account(user.get("sub")):
        return jsonify({
            "error": "ring_account_not_linked",
            "message": "Link a Ring account to your signed-in profile first.",
        }), 409
    try:
        return jsonify(ring_client.list_devices(user.get("sub")))
    except RingIntegrationError as error:
        app.logger.warning("Ring device lookup failed: %s", error)
        return jsonify({"error": "ring_api_unavailable", "message": str(error)}), 502


@app.post("/api/ring/webhooks")
def ring_webhook():
    signing_key = os.getenv("RING_WEBHOOK_SIGNING_KEY")
    signature = request.headers.get("X-Signature", "")
    if not verify_webhook_signature(signing_key, request.get_data(), signature):
        return jsonify({"error": "invalid_webhook_signature"}), 401
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid_webhook_payload"}), 400
    event_type = payload.get("type") or payload.get("event_type")
    if not isinstance(event_type, str) or not re.fullmatch(
        r"[a-z][a-z0-9_]{0,63}", event_type
    ):
        return jsonify({"error": "webhook_event_type_required"}), 400
    app.logger.info("Accepted Ring Partner API webhook event: %s", event_type)
    return jsonify({"received": True, "event_type": event_type}), 200


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
    try:
        result = service.analyze_case(case_id, payload)
    except StrandsAnalysisError as error:
        app.logger.error("%s", error)
        return jsonify({"error": "model_advisory_failed", "message": str(error)}), 502
    if result is None:
        return jsonify({"error": "case_not_found"}), 404
    return jsonify(result)


@app.post("/api/analyze-case")
def analyze_case():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "json_object_required"}), 400
    case_id = payload.get("case_id")
    if not case_id:
        return jsonify({"error": "case_id_required"}), 400
    try:
        result = service.analyze_case(case_id, payload)
    except StrandsAnalysisError as error:
        app.logger.error("%s", error)
        return jsonify({"error": "model_advisory_failed", "message": str(error)}), 502
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
