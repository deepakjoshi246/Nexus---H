"""Server-side client for the Ring Partner API."""
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet, InvalidToken


API_BASE_URL = "https://api.amazonvision.com"
TOKEN_URL = "https://oauth.ring.com/oauth/token"
NONCE_VALIDITY_SECONDS = 600


class RingIntegrationError(RuntimeError):
    """Raised when the Ring Partner API cannot fulfill a request."""


def ring_api_configured():
    return all(os.getenv(key) for key in (
        "RING_PARTNER_CLIENT_ID",
        "RING_PARTNER_CLIENT_SECRET",
        "RING_TOKEN_ENCRYPTION_KEY",
    ))


def verify_webhook_signature(signing_key, raw_body, received_signature):
    if (
        not signing_key
        or not isinstance(received_signature, str)
        or not received_signature.startswith("sha256=")
    ):
        return False
    expected = hmac.new(
        signing_key.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()
    received = received_signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)


def compute_ring_nonce(time_param, account_id, signing_key):
    message = f"{time_param}:{account_id}".encode("utf-8")
    digest = hmac.new(signing_key.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def ring_link_timestamp_valid(time_param, now=None):
    if not isinstance(time_param, str) or len(time_param) != 13 or not time_param.isdigit():
        return False
    age_seconds = (time.time() if now is None else now) - int(time_param) / 1000
    return 0 <= age_seconds <= NONCE_VALIDITY_SECONDS


class RingPartnerClient:
    def __init__(
        self,
        db_path,
        opener=urlopen,
        wall_clock=time.time,
    ):
        self.db_path = str(db_path)
        self._opener = opener
        self._wall_clock = wall_clock
        self._cipher = None
        encryption_key = os.getenv("RING_TOKEN_ENCRYPTION_KEY")
        if encryption_key:
            try:
                self._cipher = Fernet(encryption_key.encode("ascii"))
            except (ValueError, TypeError) as error:
                raise RingIntegrationError(
                    "RING_TOKEN_ENCRYPTION_KEY must be a valid Fernet key."
                ) from error
        self._init_store()

    def _init_store(self):
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS ring_tokens ("
                "account_id TEXT PRIMARY KEY, refresh_token BLOB NOT NULL, "
                "status TEXT NOT NULL, user_sub TEXT, created_at REAL NOT NULL, "
                "access_token BLOB, access_expires_at REAL, link_time TEXT, "
                "link_nonce TEXT)"
            )
            columns = {
                row[1] for row in db.execute("PRAGMA table_info(ring_tokens)")
            }
            if "access_token" not in columns:
                db.execute("ALTER TABLE ring_tokens ADD COLUMN access_token BLOB")
            if "access_expires_at" not in columns:
                db.execute("ALTER TABLE ring_tokens ADD COLUMN access_expires_at REAL")
            if "link_time" not in columns:
                db.execute("ALTER TABLE ring_tokens ADD COLUMN link_time TEXT")
            if "link_nonce" not in columns:
                db.execute("ALTER TABLE ring_tokens ADD COLUMN link_nonce TEXT")

    def _encrypt_token(self, token):
        if not self._cipher:
            raise RingIntegrationError(
                "Ring token encryption is unavailable; configure RING_TOKEN_ENCRYPTION_KEY."
            )
        return self._cipher.encrypt(token.encode("utf-8"))

    def _decrypt_token(self, encrypted):
        if not self._cipher:
            raise RingIntegrationError(
                "Ring token encryption is unavailable; configure RING_TOKEN_ENCRYPTION_KEY."
            )
        try:
            return self._cipher.decrypt(encrypted).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as error:
            raise RingIntegrationError(
                "Stored Ring credentials cannot be decrypted; check the encryption key."
            ) from error

    def _token_expiry(self, token_response):
        try:
            lifetime = max(0, int(token_response.get("expires_in", 14400)) - 60)
        except (TypeError, ValueError):
            lifetime = 14340
        return self._wall_clock() + lifetime

    def _save_token(
        self,
        account_id,
        refresh_token,
        status="UNCLAIMED",
        user_sub=None,
        token_response=None,
    ):
        encrypted = self._encrypt_token(refresh_token)
        access_token = None
        access_expires_at = None
        if token_response is not None:
            raw_access_token = token_response.get("access_token")
            if not isinstance(raw_access_token, str) or not raw_access_token:
                raise RingIntegrationError(
                    "Ring OAuth response did not include an access token."
                )
            access_token = self._encrypt_token(raw_access_token)
            access_expires_at = self._token_expiry(token_response)
        with sqlite3.connect(self.db_path, timeout=20) as db:
            db.execute(
                "INSERT INTO ring_tokens "
                "(account_id,refresh_token,status,user_sub,created_at,access_token,"
                "access_expires_at) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(account_id) DO UPDATE SET "
                "refresh_token=excluded.refresh_token,"
                "status=CASE WHEN ring_tokens.status IN ('AWAITING','LINKED') "
                "THEN ring_tokens.status ELSE excluded.status END,"
                "user_sub=CASE WHEN ring_tokens.status IN ('AWAITING','LINKED') "
                "THEN ring_tokens.user_sub ELSE excluded.user_sub END,"
                "created_at=excluded.created_at,"
                "access_token=excluded.access_token,"
                "access_expires_at=excluded.access_expires_at",
                (
                    account_id,
                    encrypted,
                    status,
                    user_sub,
                    self._wall_clock(),
                    access_token,
                    access_expires_at,
                ),
            )

    def has_linked_account(self, user_sub):
        with sqlite3.connect(self.db_path) as db:
            row = db.execute(
                "SELECT 1 FROM ring_tokens WHERE user_sub=? AND status='LINKED' LIMIT 1",
                (user_sub,),
            ).fetchone()
        return row is not None

    def _token_request(self, form):
        client_id = os.getenv("RING_PARTNER_CLIENT_ID")
        client_secret = os.getenv("RING_PARTNER_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise RingIntegrationError("Ring Partner OAuth credentials are not configured.")
        body = {
            **form,
            "client_id": client_id,
            "client_secret": client_secret,
        }
        request = Request(
            TOKEN_URL,
            data=urlencode(body).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=15) as response:
                result = json.loads(response.read())
        except HTTPError as error:
            raise RingIntegrationError(
                f"Ring OAuth token request failed with HTTP {error.code}."
            ) from error
        except (URLError, TimeoutError) as error:
            raise RingIntegrationError("Ring OAuth service is currently unreachable.") from error
        except (TypeError, json.JSONDecodeError) as error:
            raise RingIntegrationError("Ring OAuth service returned invalid JSON.") from error
        if not isinstance(result, dict) or not result.get("access_token"):
            raise RingIntegrationError("Ring OAuth response did not include an access token.")
        return result

    def _api_request(self, method, path, access_token, payload=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.api+json, application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{API_BASE_URL}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with self._opener(request, timeout=15) as response:
                raw = response.read()
        except HTTPError as error:
            if error.code == 401:
                raise RingIntegrationError(
                    "Ring access token is expired or unauthorized."
                ) from error
            if error.code == 429:
                raise RingIntegrationError(
                    "Ring Partner API rate limit reached; retry later."
                ) from error
            raise RingIntegrationError(
                f"Ring Partner API returned HTTP {error.code}."
            ) from error
        except (URLError, TimeoutError) as error:
            raise RingIntegrationError("Ring Partner API is currently unreachable.") from error
        if not raw:
            return {}
        try:
            result = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as error:
            raise RingIntegrationError("Ring Partner API returned invalid JSON.") from error
        if not isinstance(result, dict):
            raise RingIntegrationError("Ring Partner API returned an unexpected response.")
        return result

    def exchange_authorization_code(self, code):
        if not isinstance(code, str) or not code or len(code) > 4096:
            raise RingIntegrationError("A valid Ring authorization code is required.")
        result = self._token_request({
            "grant_type": "authorization_code",
            "code": code,
        })
        refresh_token = result.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise RingIntegrationError("Ring OAuth response did not include a refresh token.")
        access_token = result["access_token"]
        profile = self._api_request("GET", "/v1/users/me", access_token)
        profile_data = profile.get("data")
        account_id = profile_data.get("id") if isinstance(profile_data, dict) else None
        if not isinstance(account_id, str) or not account_id:
            raise RingIntegrationError("Ring user profile did not include an account ID.")
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "DELETE FROM ring_tokens WHERE status='UNCLAIMED' AND created_at < ?",
                (self._wall_clock() - 900,),
            )
        self._save_token(account_id, refresh_token, token_response=result)
        return {"credentials_received": True, "linked": False}

    def _get_access_token(self, account_id):
        with sqlite3.connect(self.db_path, timeout=20) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT refresh_token,access_token,access_expires_at,status,user_sub "
                "FROM ring_tokens WHERE account_id=?",
                (account_id,),
            ).fetchone()
            if row is None:
                raise RingIntegrationError(
                    "No Ring credentials are available for this account."
                )
            now = self._wall_clock()
            if row["access_token"] and row["access_expires_at"] and row["access_expires_at"] > now:
                return self._decrypt_token(row["access_token"])
            refresh_token = self._decrypt_token(row["refresh_token"])
            result = self._token_request({
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            })
            access_token = result.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise RingIntegrationError(
                    "Ring OAuth response did not include an access token."
                )
            rotated_refresh_token = result.get("refresh_token")
            db.execute(
                "UPDATE ring_tokens SET refresh_token=?,access_token=?,"
                "access_expires_at=? WHERE account_id=?",
                (
                    self._encrypt_token(rotated_refresh_token)
                    if isinstance(rotated_refresh_token, str) and rotated_refresh_token
                    else row["refresh_token"],
                    self._encrypt_token(access_token),
                    self._token_expiry(result),
                    account_id,
                ),
            )
            return access_token

    def complete_account_link(
        self, time_param, received_nonce, account_identifier, user_sub, signing_key
    ):
        if not all((time_param, received_nonce, account_identifier, user_sub, signing_key)):
            raise RingIntegrationError("Ring account-link details are incomplete.")
        if (
            not isinstance(time_param, str)
            or not isinstance(received_nonce, str)
            or not isinstance(account_identifier, str)
            or not isinstance(user_sub, str)
            or not isinstance(signing_key, str)
            or len(received_nonce) != 43
        ):
            raise RingIntegrationError("Ring account-link nonce or timestamp is invalid.")
        if not ring_link_timestamp_valid(time_param, self._wall_clock()):
            raise RingIntegrationError("Ring account-link request has expired.")

        with sqlite3.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            db.execute(
                "DELETE FROM ring_tokens WHERE status='UNCLAIMED' AND created_at < ?",
                (self._wall_clock() - 900,),
            )
            awaiting = db.execute(
                "SELECT account_id,link_time,link_nonce FROM ring_tokens "
                "WHERE user_sub=? AND status='AWAITING'",
                (user_sub,),
            ).fetchall()
            candidates = db.execute(
                "SELECT account_id FROM ring_tokens WHERE status='UNCLAIMED' "
                "AND created_at >= ?",
                (self._wall_clock() - 900,),
            ).fetchall()

        account_id = next((
            row["account_id"] for row in awaiting
            if row["link_time"] == time_param
            and row["link_nonce"]
            and hmac.compare_digest(row["link_nonce"], received_nonce)
        ), None)
        if account_id is None:
            account_id = next((
                row["account_id"] for row in candidates
                if hmac.compare_digest(
                    compute_ring_nonce(time_param, row["account_id"], signing_key),
                    received_nonce,
                )
            ), None)
            if account_id is None:
                raise RingIntegrationError("No matching unclaimed Ring account was found.")
            self._api_request(
                "POST",
                "/v1/accounts/me/app-integrations",
                self._get_access_token(account_id),
                {"account_identifier": account_identifier, "nonce": received_nonce},
            )
            with sqlite3.connect(self.db_path) as db:
                updated = db.execute(
                    "UPDATE ring_tokens SET status='AWAITING',user_sub=?,"
                    "link_time=?,link_nonce=? "
                    "WHERE account_id=? AND status='UNCLAIMED'",
                    (user_sub, time_param, received_nonce, account_id),
                )
                if updated.rowcount != 1:
                    raise RingIntegrationError(
                        "Ring account-link credentials were already claimed."
                    )

        self._api_request(
            "PATCH",
            "/v1/accounts/me/app-integrations",
            self._get_access_token(account_id),
            {"status": "completed"},
        )
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "UPDATE ring_tokens SET status='LINKED' WHERE account_id=? AND user_sub=?",
                (account_id, user_sub),
            )
        return {"linked": True}

    def list_devices(self, user_sub):
        with sqlite3.connect(self.db_path) as db:
            row = db.execute(
                "SELECT account_id FROM ring_tokens WHERE user_sub=? AND status='LINKED' "
                "LIMIT 1",
                (user_sub,),
            ).fetchone()
        if row is None:
            raise RingIntegrationError("No Ring account is linked to this user.")
        return self._api_request(
            "GET",
            "/v1/devices?include=status,capabilities,location",
            self._get_access_token(row[0]),
        )
