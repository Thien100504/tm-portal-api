"""
Seed a fresh development database: run migrations (which also seed roles and
permissions) and create the admin account.

Usage:
    python -m scripts.seed_all
    python -m scripts.seed_all --email admin@example.com --password MyP@ss123
"""
import argparse
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()


def run_migrations() -> None:
    print("\nRunning Alembic migrations...")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("Migration failed:")
        print(result.stderr)
        sys.exit(1)
    for line in result.stderr.splitlines():
        if "Running upgrade" in line:
            print(" ", line.split("] ")[-1])
    print("Migrations done.")


def seed_admin(email: str, password: str) -> None:
    print(f"\nSeeding admin: {email}")
    from passlib.context import CryptContext
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    async_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://taskmanager:taskmanager_dev@127.0.0.1:5432/taskmanager")
    sync_url = async_url.replace("+asyncpg", "+psycopg2")

    engine = create_engine(sync_url, echo=False)
    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

    with Session(engine) as session:
        existing = session.execute(
            text("SELECT id FROM users WHERE email = :email"), {"email": email}
        ).fetchone()

        if existing:
            print(f"  Admin '{email}' already exists, skipping.")
            return

        uid = uuid.uuid4()
        now = datetime.now(timezone.utc)
        session.execute(text("""
            INSERT INTO users (id, email, password_hash, full_name, system_role,
                               is_active, created_at, updated_at)
            VALUES (:id, :email, :pw, 'System Admin', 'admin',
                    true, :now, :now)
        """), {"id": uid, "email": email, "pw": pwd.hash(password), "now": now})
        session.commit()
        print(f"  Admin created (id={uid}).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a fresh development database")
    parser.add_argument("--email", default=os.getenv("ADMIN_EMAIL", "admin@taskmanager.com"))
    parser.add_argument("--password", default=os.getenv("ADMIN_PASSWORD", "Admin@123456"))
    parser.add_argument("--skip-migration", action="store_true")
    parser.add_argument("--skip-admin", action="store_true")
    args = parser.parse_args()

    if not args.skip_migration:
        run_migrations()

    if not args.skip_admin:
        seed_admin(args.email, args.password)

    print(f"\nSeed complete. Log in as {args.email}")


if __name__ == "__main__":
    main()
