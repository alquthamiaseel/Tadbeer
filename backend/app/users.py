"""Dashboard logins, kept in ``users.json``.

``users.json`` is the only file the backend persists, and it holds account
records only — id, username, a salted password hash, and a creation time. Never
a plaintext password, never an API token, never pipeline state.

Accounts are added with ``make create-user`` (``scripts/create_user.py``). As a
shortcut, setting ``DASHBOARD_PASSWORD`` creates an ``admin`` account the first
time anyone logs in, and re-hashes it if that variable later changes. Once an
account exists the backend can run with ``DASHBOARD_PASSWORD`` unset.

Writes are atomic (write a temporary file, then rename over the original) and
serialised by a lock, so a crash or two concurrent writers cannot leave a
half-written file. A file that is not valid JSON, or that holds duplicate
accounts, is reported and left untouched rather than overwritten — that would
silently destroy the accounts it holds.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import logging
import os
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings

log = logging.getLogger(__name__)

FILE_VERSION = 1
DASHBOARD_USERNAME = "admin"

#: scrypt cost parameters: ~16 MiB and tens of milliseconds per hash, which is
#: negligible for a dashboard and expensive for anyone guessing offline.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
_SCRYPT_DKLEN = 32

#: Guards every read-modify-write of the file within this process.
_lock = threading.RLock()


class UsersFileError(RuntimeError):
    """users.json exists but cannot be trusted: unreadable, malformed, or ambiguous."""


class DuplicateAccount(ValueError):
    """An account with that username already exists."""


@dataclass(frozen=True)
class User:
    id: str
    username: str
    password_hash: str
    created_at: str


# --- password hashing ------------------------------------------------------


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    """A salted scrypt hash, self-describing so the parameters can change later."""
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time check of ``password`` against a :func:`hash_password` value."""
    try:
        scheme, n, r, p, salt, expected = encoded.split("$")
        if scheme != "scrypt":
            return False
        expected_bytes = base64.b64decode(expected)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected_bytes),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected_bytes)


# --- the file --------------------------------------------------------------


def _path(path: Path | None) -> Path:
    return Path(path) if path is not None else Path(settings.users_file)


def load_users(path: Path | None = None) -> list[User]:
    """Every account in the file. A missing file is an empty one."""
    path = _path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        raise UsersFileError(f"{path} could not be read: {exc}") from exc

    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UsersFileError(
            f"{path} is not valid JSON ({exc}). Fix it, or delete it to have the "
            "dashboard account recreated from DASHBOARD_PASSWORD."
        ) from exc

    records = document.get("users") if isinstance(document, dict) else None
    if not isinstance(records, list):
        raise UsersFileError(f'{path} must be a JSON object with a "users" list')

    users: list[User] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for index, record in enumerate(records):
        try:
            user = User(**{name: record[name] for name in User.__dataclass_fields__})
        except (KeyError, TypeError) as exc:
            raise UsersFileError(f"{path}: account #{index} is missing a field ({exc})") from exc
        if not all(isinstance(value, str) and value for value in asdict(user).values()):
            raise UsersFileError(f"{path}: account #{index} has an empty or non-text field")

        name = user.username.casefold()
        if user.id in seen_ids or name in seen_names:
            # Two records for one account: refusing beats guessing which is real.
            raise UsersFileError(f"{path}: duplicate account {user.username!r}")
        seen_ids.add(user.id)
        seen_names.add(name)
        users.append(user)
    return users


def _serialise(users: list[User]) -> str:
    document = {"version": FILE_VERSION, "users": [asdict(user) for user in users]}
    return json.dumps(document, indent=2) + "\n"


def _write_temp(path: Path, content: str) -> Path:
    """Write ``content`` to a fully synced temporary file beside ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return Path(tmp)


def _write(users: list[User], path: Path) -> None:
    """Replace the file atomically: readers see the old file or the new one."""
    tmp = _write_temp(path, _serialise(users))
    try:
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def ensure_file(path: Path | None = None) -> None:
    """Create an empty users.json if there is none. Never touches an existing one."""
    path = _path(path)
    with _lock:
        if path.exists():
            return
        tmp = _write_temp(path, _serialise([]))
        try:
            # A hard link fails if the target exists, so even another process
            # creating the file at the same moment cannot be overwritten.
            os.link(tmp, path)
            log.info("created %s", path)
        except FileExistsError:
            pass
        except OSError:
            # No hard links on this filesystem; the lock still covers this process.
            if not path.exists():
                os.replace(tmp, path)
                log.info("created %s", path)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp)


def find_user(username: str, path: Path | None = None) -> User | None:
    wanted = username.casefold()
    return next((u for u in load_users(path) if u.username.casefold() == wanted), None)


def create_user(username: str, password: str, path: Path | None = None) -> User:
    """Add an account. Raises :class:`DuplicateAccount` if the username is taken."""
    path = _path(path)
    with _lock:
        users = load_users(path)
        if any(u.username.casefold() == username.casefold() for u in users):
            raise DuplicateAccount(f"an account named {username!r} already exists")
        user = User(
            id=str(uuid.uuid4()),
            username=username,
            password_hash=hash_password(password),
            created_at=datetime.now(UTC).isoformat(),
        )
        _write([*users, user], path)
        return user


def set_password(username: str, password: str, path: Path | None = None) -> User:
    path = _path(path)
    with _lock:
        users = load_users(path)
        for index, user in enumerate(users):
            if user.username.casefold() == username.casefold():
                updated = User(
                    id=user.id,
                    username=user.username,
                    password_hash=hash_password(password),
                    created_at=user.created_at,
                )
                users[index] = updated
                _write(users, path)
                return updated
    raise KeyError(username)


_dummy: str | None = None


def dummy_hash() -> str:
    """A real hash of nothing, to verify against when a username is unknown."""
    global _dummy
    if _dummy is None:
        _dummy = hash_password(os.urandom(16).hex())
    return _dummy


# --- the dashboard account -------------------------------------------------


def password_configured(password: str | None) -> bool:
    """False for an unset password or the shipped placeholder."""
    return bool(password) and password != "changeme"


#: (file, password, stored hash) last confirmed to agree, so the expensive
#: verification runs once per change rather than on every request.
_synced: tuple[Path, str, str] | None = None


def dashboard_account(path: Path | None = None) -> User | None:
    """The account guarding the dashboard, brought in line with DASHBOARD_PASSWORD.

    Returns None when there is no account and no usable password to create one
    from. Raises :class:`UsersFileError` if the file cannot be trusted.
    """
    global _synced
    path = _path(path)
    password = settings.dashboard_password

    with _lock:
        user = find_user(DASHBOARD_USERNAME, path)
        if not password_configured(password):
            return user
        if user is not None and _synced == (path, password, user.password_hash):
            return user

        if user is None:
            user = create_user(DASHBOARD_USERNAME, password, path)
            log.info("created the dashboard account in %s", path)
        elif not verify_password(password, user.password_hash):
            user = set_password(DASHBOARD_USERNAME, password, path)
            log.info("DASHBOARD_PASSWORD changed; re-hashed the dashboard account")
        _synced = (path, password, user.password_hash)
        return user
