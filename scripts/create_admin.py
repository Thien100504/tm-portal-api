"""
Script that creates the default Admin account (GAP-05 fix).

Uses synchronous SQLAlchemy to keep the CLI script simple.
Reads ADMIN_EMAIL and ADMIN_PASSWORD from environment variables or command-line arguments.

Usage:
    python scripts/create_admin.py
    python scripts/create_admin.py --email admin@example.com --password MyP@ss123
"""

import argparse
import sys
import uuid
from datetime import UTC, datetime

from dotenv import load_dotenv
from passlib.context import CryptContext
from sqlalchemy import Boolean, Column, DateTime, String, create_engine, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Session

load_dotenv()

# ── Password hashing ─────────────────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_sync_database_url() -> str:
    """Get the synchronous database URL from environment variables."""
    import os

    async_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://taskmanager:secret@localhost:5432/taskmanager_db",
    )
    # Switch from the async driver to the sync driver
    return async_url.replace("+asyncpg", "+psycopg2").replace(
        "postgresql://", "postgresql+psycopg2://"
    )


class Base(DeclarativeBase):
    """Base for the script - standalone, does not depend on app models."""

    pass


class User(Base):
    """Minimal User model for creating the admin — matches the schema in spec Section 7."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False, default="System Admin")
    system_role = Column(String(50), nullable=False, default="admin")
    avatar_url = Column(String(500), nullable=True)
    telegram_chat_id = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


def create_admin(email: str, password: str) -> None:
    """
    Create the admin account in the database.

    Args:
        email: Admin login email
        password: Plaintext password (will be hashed with bcrypt)
    """
    db_url = get_sync_database_url()
    engine = create_engine(db_url, echo=False)

    # Create tables if they do not exist (safe for the first run)
    Base.metadata.create_all(bind=engine, checkfirst=True)

    with Session(engine) as session:
        # Check whether the admin already exists
        existing = session.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": email},
        ).fetchone()

        if existing:
            print(f"Warning: Admin with email '{email}' already exists. Skipping.")
            return

        # Create a new admin
        admin = User(
            email=email,
            password_hash=pwd_context.hash(password),
            full_name="System Admin",
            system_role="admin",
            is_active=True,
        )
        session.add(admin)
        session.commit()

        print("✅ Admin account created successfully!")
        print(f"   Email: {email}")
        print(f"   ID:    {admin.id}")


def main() -> None:
    """Entry point for the CLI script."""
    parser = argparse.ArgumentParser(
        description="Create the default admin account for Task Manager"
    )
    parser.add_argument(
        "--email",
        type=str,
        default=None,
        help="Admin email (default: read from the ADMIN_EMAIL env var)",
    )
    parser.add_argument(
        "--password",
        type=str,
        default=None,
        help="Admin password (default: read from the ADMIN_PASSWORD env var)",
    )
    args = parser.parse_args()

    # Prefer CLI arguments, fall back to environment variables
    import os

    email = args.email or os.getenv("ADMIN_EMAIL", "admin@taskmanager.com")
    password = args.password or os.getenv("ADMIN_PASSWORD", "Admin@123456")

    if not email or not password:
        print(
            "Error: provide the email and password as arguments or environment variables."
        )
        sys.exit(1)

    print(f"Creating admin with email: {email}")
    create_admin(email, password)


if __name__ == "__main__":
    main()
