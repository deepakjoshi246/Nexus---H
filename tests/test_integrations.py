import asyncio
import hashlib
import hmac
import json
import sqlite3
import time
from urllib.request import Request

import pytest
from cryptography.fernet import Fernet

from nexus_h.integrations.ring import (
    RingIntegrationError,
    RingPartnerClient,
    compute_ring_nonce,
    verify_webhook_signature,
)


class MockResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def test_ring_webhook_requires_valid_hmac():
    body = b'{"type":"motion_detected"}'
    key = "test-signing-key"
    signature = hmac.new(key.encode(), body, hashlib.sha256).hexdigest()

    assert verify_webhook_signature(key, body, f"sha256={signature}")
    assert not verify_webhook_signature(key, body, "sha256=invalid")
    assert not verify_webhook_signature(key, body, signature)
    assert not verify_webhook_signature("", body, signature)


def test_ring_link_encrypts_tokens_and_completes_verified_flow(tmp_path, monkeypatch):
    encryption_key = Fernet.generate_key().decode("ascii")
    signing_key = "test-signing-key"
    now_seconds = 1_700_000_000
    now_ms = str(now_seconds * 1000)
    clock_state = {"now": now_seconds}
    monkeypatch.setenv("RING_PARTNER_CLIENT_ID", "partner-id")
    monkeypatch.setenv("RING_PARTNER_CLIENT_SECRET", "partner-secret")
    monkeypatch.setenv("RING_TOKEN_ENCRYPTION_KEY", encryption_key)
    calls = []

    def opener(request, timeout):
        assert timeout == 15
        calls.append(request)
        if request.full_url == "https://oauth.ring.com/oauth/token":
            body = {"access_token": "short-lived", "refresh_token": "rotated"}
        elif request.full_url == "https://api.amazonvision.com/v1/users/me":
            assert request.get_header("Authorization") == "Bearer short-lived"
            body = {"data": {"id": "ring-account-1"}}
        elif request.full_url == "https://api.amazonvision.com/v1/accounts/me/app-integrations":
            assert request.get_header("Authorization") == "Bearer short-lived"
            if request.get_method() == "POST":
                assert json.loads(request.data) == {
                    "account_identifier": "user@example.com",
                    "nonce": compute_ring_nonce(now_ms, "ring-account-1", signing_key),
                }
            else:
                assert request.get_method() == "PATCH"
                assert json.loads(request.data) == {"status": "completed"}
            body = {}
        else:
            assert request.full_url.startswith("https://api.amazonvision.com/v1/devices?")
            assert request.get_header("Authorization") == "Bearer short-lived"
            body = {"data": [{"id": "ring-device-1"}]}
        return MockResponse(json.dumps(body).encode())

    db_path = tmp_path / "ring.db"
    client = RingPartnerClient(
        db_path,
        opener=opener,
        wall_clock=lambda: clock_state["now"],
    )
    assert client.exchange_authorization_code("single-use-code") == {
        "credentials_received": True,
        "linked": False,
    }
    nonce = compute_ring_nonce(now_ms, "ring-account-1", signing_key)
    assert client.complete_account_link(
        now_ms, nonce, "user@example.com", "cognito-user-1", signing_key
    ) == {"linked": True}
    assert client.list_devices("cognito-user-1")["data"][0]["id"] == "ring-device-1"
    assert len(calls) == 5

    clock_state["now"] += 14400
    assert client._get_access_token("ring-account-1") == "short-lived"
    calls_after_refresh = len(calls)
    second_worker = RingPartnerClient(
        db_path,
        opener=opener,
        wall_clock=lambda: clock_state["now"],
    )
    assert second_worker._get_access_token("ring-account-1") == "short-lived"
    assert len(calls) == calls_after_refresh

    with sqlite3.connect(db_path) as db:
        encrypted_refresh, encrypted_access = db.execute(
            "SELECT refresh_token,access_token FROM ring_tokens "
            "WHERE account_id='ring-account-1'"
        ).fetchone()
    assert b"rotated" not in encrypted_refresh
    assert b"short-lived" not in encrypted_access
    assert Fernet(encryption_key.encode()).decrypt(encrypted_refresh) == b"rotated"
    assert Fernet(encryption_key.encode()).decrypt(encrypted_access) == b"short-lived"
    assert isinstance(calls[0], Request)
    assert client.has_linked_account("cognito-user-1")


def test_ring_link_rejects_expired_or_mismatched_nonce(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "RING_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )
    now_seconds = 1_700_000_000
    key = "test-signing-key"
    client = RingPartnerClient(
        tmp_path / "ring.db",
        opener=lambda *_args, **_kwargs: pytest.fail("No API request expected"),
        wall_clock=lambda: now_seconds,
    )
    client._save_token("ring-account-1", "refresh")
    fresh_time = str(now_seconds * 1000)
    nonce = compute_ring_nonce(fresh_time, "ring-account-1", key)

    with pytest.raises(RingIntegrationError, match="expired"):
        client.complete_account_link(
            str((now_seconds - 601) * 1000), nonce, "user@example.com", "user-1", key
        )
    with pytest.raises(RingIntegrationError, match="No matching"):
        client.complete_account_link(
            fresh_time, "B" + nonce[1:], "user@example.com", "user-1", key
        )


def test_ring_link_retry_must_match_original_nonce(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "RING_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii")
    )
    now_seconds = 1_700_000_000
    key = "test-signing-key"
    timestamp = str(now_seconds * 1000)
    nonce = compute_ring_nonce(timestamp, "ring-account-1", key)
    calls = []

    def opener(request, timeout):
        calls.append(request)
        assert request.get_method() == "PATCH"
        assert json.loads(request.data) == {"status": "completed"}
        return MockResponse(b"{}")

    client = RingPartnerClient(
        tmp_path / "ring.db",
        opener=opener,
        wall_clock=lambda: now_seconds,
    )
    client._save_token(
        "ring-account-1",
        "refresh",
        status="AWAITING",
        user_sub="user-1",
        token_response={"access_token": "access", "expires_in": 14400},
    )
    with sqlite3.connect(client.db_path) as db:
        db.execute(
            "UPDATE ring_tokens SET link_time=?,link_nonce=? WHERE account_id=?",
            (timestamp, nonce, "ring-account-1"),
        )

    with pytest.raises(RingIntegrationError, match="No matching"):
        client.complete_account_link(
            timestamp, "B" + nonce[1:], "user@example.com", "user-1", key
        )
    assert not calls
    assert client.complete_account_link(
        timestamp, nonce, "user@example.com", "user-1", key
    ) == {"linked": True}
    assert len(calls) == 1


def test_ring_store_adds_shared_access_token_columns(tmp_path, monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("RING_TOKEN_ENCRYPTION_KEY", key)
    db_path = tmp_path / "older-ring.db"
    with sqlite3.connect(db_path) as db:
        db.execute(
            "CREATE TABLE ring_tokens (account_id TEXT PRIMARY KEY, "
            "refresh_token BLOB NOT NULL, status TEXT NOT NULL, "
            "user_sub TEXT, created_at REAL NOT NULL)"
        )
    client = RingPartnerClient(db_path, wall_clock=lambda: 1000)
    with sqlite3.connect(db_path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(ring_tokens)")}
    assert {"access_token", "access_expires_at", "link_time", "link_nonce"} <= columns
    assert client._token_expiry({"expires_in": 30}) == 1000


def test_alexa_mcp_registers_streamable_support_tools():
    from alexa_mcp_server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}
    assert {
        "list_support_cases",
        "get_case_context",
        "analyze_support_case",
        "get_human_queue",
    } <= names
    assert mcp.settings.streamable_http_path == "/mcp"
    assert mcp.settings.stateless_http


def test_ring_webhook_acknowledges_valid_event_with_http_200(monkeypatch):
    from app import app

    body = b'{"type":"motion_detected"}'
    key = "test-signing-key"
    signature = hmac.new(key.encode(), body, hashlib.sha256).hexdigest()
    monkeypatch.setenv("RING_WEBHOOK_SIGNING_KEY", key)

    response = app.test_client().post(
        "/api/ring/webhooks",
        data=body,
        content_type="application/json",
        headers={"X-Signature": f"sha256={signature}"},
    )
    assert response.status_code == 200
    assert response.json["received"] is True


def test_ring_token_exchange_rejects_non_string_codes(monkeypatch):
    from app import app
    monkeypatch.setenv("RING_PARTNER_CLIENT_ID", "partner-id")
    monkeypatch.setenv("RING_PARTNER_CLIENT_SECRET", "partner-secret")
    monkeypatch.setenv("RING_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))

    response = app.test_client().post("/api/ring/oauth/token", json={"code": 123})
    assert response.status_code == 400
    assert response.json["error"] == "ring_authorization_code_required"


def test_ring_webhook_rejects_invalid_event_name(monkeypatch):
    from app import app
    key = "test-signing-key"
    body = b'{"type":"motion_detected\\nforged-log"}'
    signature = hmac.new(key.encode(), body, hashlib.sha256).hexdigest()
    monkeypatch.setenv("RING_WEBHOOK_SIGNING_KEY", key)

    response = app.test_client().post(
        "/api/ring/webhooks",
        data=body,
        content_type="application/json",
        headers={"X-Signature": f"sha256={signature}"},
    )
    assert response.status_code == 400


def test_ring_device_discovery_requires_authenticated_link(monkeypatch):
    from app import app

    monkeypatch.setenv("RING_PARTNER_CLIENT_ID", "partner-id")
    monkeypatch.setenv("RING_PARTNER_CLIENT_SECRET", "partner-secret")
    monkeypatch.setenv("RING_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))

    response = app.test_client().get("/api/ring/devices")
    assert response.status_code == 401
    assert response.json["error"] == "authentication_required"


def test_cognito_login_fails_closed_when_not_configured(monkeypatch):
    from app import app
    monkeypatch.setattr("app.cognito_configured", lambda: False)
    response = app.test_client().get("/auth/login")
    assert response.status_code == 503
    assert response.json["error"] == "cognito_not_configured"


def test_model_advisory_failure_is_returned_as_gateway_error(monkeypatch):
    import app as app_module

    from nexus_h.agent import StrandsAnalysisError
    monkeypatch.setattr(
        app_module.service,
        "analyze_case",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            StrandsAnalysisError("model advisory unavailable")
        ),
    )
    response = app_module.app.test_client().post("/api/cases/case-100/analyze")
    assert response.status_code == 502
    assert response.json["error"] == "model_advisory_failed"


def test_ring_account_link_preserves_nonce_through_sign_in(monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module.app, "secret_key", "test-session-secret")
    monkeypatch.setattr(app_module, "cognito_configured", lambda: True)
    monkeypatch.setenv("RING_PARTNER_CLIENT_ID", "partner-id")
    monkeypatch.setenv("RING_PARTNER_CLIENT_SECRET", "partner-secret")
    monkeypatch.setenv("RING_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("RING_WEBHOOK_SIGNING_KEY", "ring-signing-key")
    timestamp = str(int(time.time() * 1000))
    nonce = "A" * 43
    client = app_module.app.test_client()

    response = client.get(f"/ring/link?time={timestamp}&nonce={nonce}")
    assert response.status_code == 302
    assert response.location.endswith("/auth/login")
    with client.session_transaction() as browser_session:
        assert browser_session["ring_link_pending"] == {
            "time": timestamp,
            "nonce": nonce,
        }


def test_cognito_callback_accepts_only_verified_identity(monkeypatch):
    import app as app_module

    linked = []

    class FakeCognito:
        def __init__(self, email_verified):
            self.email_verified = email_verified

        def authorize_access_token(self):
            return {
                "userinfo": {
                    "sub": "cognito-user-1",
                    "email": "user@example.com",
                    "email_verified": self.email_verified,
                }
            }

    monkeypatch.setattr(app_module.app, "secret_key", "test-session-secret")
    monkeypatch.setattr(app_module, "cognito_configured", lambda: True)
    monkeypatch.setattr(
        app_module.oauth, "cognito", FakeCognito(True), raising=False
    )
    monkeypatch.setenv("RING_WEBHOOK_SIGNING_KEY", "ring-signing-key")
    monkeypatch.setattr(
        app_module.ring_client,
        "complete_account_link",
        lambda *args: linked.append(args) or {"linked": True},
    )
    client = app_module.app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["ring_link_pending"] = {
            "time": "1700000000000",
            "nonce": "A" * 43,
        }
    response = client.get("/auth/callback")
    assert response.status_code == 302
    assert response.location.endswith("/?ring_link=complete")
    assert linked == [(
        "1700000000000",
        "A" * 43,
        "user@example.com",
        "cognito-user-1",
        "ring-signing-key",
    )]
    assert client.get("/api/integrations").json["ring"]["user_authenticated"] is True
    monkeypatch.setattr(
        app_module.oauth, "cognito", FakeCognito(False), raising=False
    )
    assert app_module.app.test_client().get("/auth/callback").status_code == 403
