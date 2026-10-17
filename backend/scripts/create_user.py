"""Create a dashboard login in users.json, or reset an existing one's password.

Usage:
    python -m scripts.create_user --username sara
    python -m scripts.create_user --username sara --password 'at least 8 chars'

Without ``--password`` it is asked for at the prompt, which keeps it out of
your shell history.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from app import users
from app.config import settings

MIN_PASSWORD_LENGTH = 8


def create_or_update(username: str, password: str) -> int:
    username = username.strip()
    if not username:
        print("Username must not be empty.")
        return 1
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
        return 1
    try:
        users.ensure_file()
        if users.find_user(username) is None:
            users.create_user(username, password)
            print(f"Created {username!r} in {settings.users_file}.")
        else:
            users.set_password(username, password)
            print(f"Updated the password for {username!r}.")
    except users.UsersFileError as exc:
        print(exc)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", help="omit to be prompted")
    args = parser.parse_args()
    password = args.password if args.password is not None else getpass.getpass("Password: ")
    return create_or_update(args.username, password)


if __name__ == "__main__":
    sys.exit(main())
