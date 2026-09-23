"""Local operator tool: bootstrap an owner without a public first-user claim."""

import argparse
import getpass
import sys

from sqlalchemy import delete, select, update

from app.auth import Credentials, hash_password
from app.models import AuthSession, Project, SessionLocal, User


def main():
    parser = argparse.ArgumentParser(description="Create/reset a local account and assign unowned legacy projects")
    parser.add_argument("username")
    parser.add_argument("--password-stdin", action="store_true", help="Read one password line from stdin; never pass it in arguments")
    parser.add_argument("--claim-legacy", action="store_true", help="Assign only projects whose owner_id is NULL")
    parser.add_argument("--reset-password", action="store_true", help="Explicitly replace an existing user's password")
    args = parser.parse_args()
    password = sys.stdin.readline().rstrip("\r\n") if args.password_stdin else getpass.getpass("New password: ")
    try:
        credentials = Credentials(username=args.username, password=password)
    except ValueError:
        parser.error("账号需为 3–32 位字母、数字、下划线或短横线；密码长度为 8–128 位")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == credentials.username).with_for_update())
        if user and not args.reset_password:
            parser.error("Account exists; use --reset-password only if an intentional password reset is needed")
        if user:
            user.password_hash = hash_password(credentials.password)
            db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
        else:
            user = User(username=credentials.username, password_hash=hash_password(credentials.password))
            db.add(user)
            db.flush()
        claimed = 0
        if args.claim_legacy:
            claimed = db.execute(update(Project).where(Project.owner_id.is_(None)).values(owner_id=user.id)).rowcount
        db.commit()
        print(f"Account {user.username} ready; assigned {claimed} legacy projects.")


if __name__ == "__main__":
    main()
