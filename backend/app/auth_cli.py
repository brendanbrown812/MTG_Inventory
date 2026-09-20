from __future__ import annotations

import argparse
import getpass

from app.auth_service import create_user, set_password
from app.database import Base, SessionLocal, engine, run_migrations
from app.models import User


def _password_twice() -> str:
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm password: "):
        raise ValueError("Passwords do not match.")
    return password


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Spellbinder accounts")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user")
    create.add_argument("username")
    create.add_argument("--admin", action="store_true", help="Create an administrator")
    reset = commands.add_parser("reset-password")
    reset.add_argument("username")
    commands.add_parser("list-users")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    with SessionLocal() as db:
        if args.command == "list-users":
            users = db.query(User).order_by(User.username).all()
            print("\n".join(f"{user.username}\t{user.role}\t{'active' if user.is_active else 'disabled'}" for user in users) or "No users.")
            return
        if args.command == "create-user":
            if not args.admin:
                parser.error("Only admin accounts are supported right now; pass --admin.")
            try:
                user = create_user(db, args.username, _password_twice(), role="admin")
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            db.commit()
            print(f"Created administrator {user.username}.")
            return
        user = db.query(User).filter(User.username == args.username.strip().lower()).first()
        if user is None:
            raise SystemExit("User not found.")
        try:
            set_password(db, user, _password_twice())
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        db.commit()
        print(f"Password reset for {user.username}; existing sessions were revoked.")


if __name__ == "__main__":
    main()
