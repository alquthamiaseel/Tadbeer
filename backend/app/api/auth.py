"""Dashboard login, and optional protection for the API.

``POST /api/auth/login`` checks a username and password against ``users.json``
(see :mod:`app.users`) and returns a signed token (see :mod:`app.security`). The
dashboard keeps it and sends ``Authorization: Bearer <token>`` on every call.

Enforcement is off by default, because the normal way to run this is on a
laptop where the API listens on 127.0.0.1 and nothing else can reach it. Set
``DASHBOARD_AUTH=true`` before putting the dashboard on a domain, at which point
an unauthenticated API would expose every stakeholder conversation the agent has
read. Then every other ``/api`` route requires a valid token for an account that
still exists in ``users.json``.

Logins: ``make create-user``, or set ``DASHBOARD_PASSWORD`` to get an ``admin``.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from app import users
from app.config import settings
from app.security import create_token, verify_token

NOT_AUTHORISED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authorised",
    headers={"WWW-Authenticate": "Bearer"},
)


def _users_file_failure(exc: users.UsersFileError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


async def require_dashboard_auth(authorization: str | None = Header(default=None)) -> None:
    if not settings.dashboard_auth:
        return

    scheme, _, token = (authorization or "").partition(" ")
    claims = verify_token(token) if scheme.lower() == "bearer" else None
    if claims is None:
        raise NOT_AUTHORISED

    # A deleted account's tokens stop working, without waiting out the expiry.
    try:
        user = await asyncio.to_thread(users.find_user, claims["username"])
    except users.UsersFileError as exc:
        raise _users_file_failure(exc) from exc
    if user is None or user.id != claims["user_id"]:
        raise NOT_AUTHORISED


router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    token: str
    username: str


def _check_login(username: str, password: str) -> users.User | None:
    """The account if the password matches. Blocking: run it in a thread."""
    users.dashboard_account()  # creates or re-syncs "admin" from DASHBOARD_PASSWORD
    user = users.find_user(username)
    # Hash even for an unknown username, so timing does not reveal which exist.
    stored = user.password_hash if user is not None else users.dummy_hash()
    if users.verify_password(password, stored) and user is not None:
        return user
    return None


@router.post("/login", response_model=LoginOut)
async def login(body: LoginIn) -> LoginOut:
    try:
        user = await asyncio.to_thread(_check_login, body.username.strip(), body.password)
    except users.UsersFileError as exc:
        raise _users_file_failure(exc) from exc
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong username or password"
        )
    return LoginOut(token=create_token(user.id, user.username), username=user.username)
