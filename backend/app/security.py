"""Signed dashboard login tokens.

A token is ``<user id>.<username>.<expiry>.<HMAC>``. Nothing about a session is
stored server side — the signature is the proof — which keeps users.json the
only local file and means a restart does not need to remember who is logged in.

The signing key is ``SESSION_SECRET``. Without one, a random key is made per
process, so every login ends when the backend restarts — the same lifetime as
the in-memory runs the dashboard shows.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from app.config import settings

TOKEN_LIFETIME_SECONDS = 60 * 60 * 12

_process_secret = secrets.token_bytes(32)


def _key() -> bytes:
    return settings.session_secret.encode() if settings.session_secret else _process_secret


def _sign(payload: str) -> str:
    return hmac.new(_key(), payload.encode(), hashlib.sha256).hexdigest()


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def create_token(user_id: str, username: str, *, now: float | None = None) -> str:
    expiry = int((now if now is not None else time.time()) + TOKEN_LIFETIME_SECONDS)
    payload = f"{user_id}.{_b64(username)}.{expiry}"
    return f"{payload}.{_sign(payload)}"


def verify_token(token: str, *, now: float | None = None) -> dict | None:
    """``{"user_id", "username"}`` for a valid, unexpired token; otherwise None."""
    parts = token.split(".")
    if len(parts) != 4:
        return None
    user_id, username_b64, expiry, signature = parts
    if not hmac.compare_digest(_sign(f"{user_id}.{username_b64}.{expiry}"), signature):
        return None
    try:
        if int(expiry) < (now if now is not None else time.time()):
            return None
        username = base64.urlsafe_b64decode(username_b64 + "==").decode()
    except (ValueError, UnicodeDecodeError):
        return None
    return {"user_id": user_id, "username": username}
