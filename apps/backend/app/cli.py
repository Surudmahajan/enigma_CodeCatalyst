"""Operator commands (never exposed over HTTP).

    python -m app.cli create-admin admin@example.com --first-name Ada --last-name Ops
"""

import argparse
import getpass
import sys

from app import models  # noqa: F401
from app.auth.schemas import check_password_strength
from app.auth.service import get_user_by_email, normalize_email
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.users.models import User


def create_admin(email: str, first_name: str, last_name: str) -> None:
    with SessionLocal() as db:
        user = get_user_by_email(db, email)
        if user is None:
            password = getpass.getpass("Password for the new admin: ")
            try:
                check_password_strength(password)
            except ValueError as exc:
                sys.exit(str(exc))
            user = User(email=normalize_email(email), password_hash=hash_password(password), first_name=first_name,
                        last_name=last_name, is_verified=True)
            db.add(user)
        user.is_platform_admin = True
        db.commit()
        print(f"{user.email} is now a platform administrator.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="create or promote a platform administrator")
    admin.add_argument("email")
    admin.add_argument("--first-name", default="Platform")
    admin.add_argument("--last-name", default="Admin")
    args = parser.parse_args()
    if args.command == "create-admin":
        create_admin(args.email, args.first_name, args.last_name)


if __name__ == "__main__":
    main()
