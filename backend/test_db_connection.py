"""RELI-RAG A1: verify the PostgreSQL + pgvector database is reachable.

Usage (from the project root):
    python backend/test_db_connection.py

Exits with status 0 on success, 1 on any failure.
"""

import os
import sys
from pathlib import Path
from typing import NoReturn

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

ROOT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def fail(message: str) -> NoReturn:
    print(f"[FAIL] {message}")
    sys.exit(1)


def main() -> None:
    # Existing environment variables take precedence over values in .env.
    load_dotenv(ROOT_ENV_FILE)

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        fail(f"DATABASE_URL is not set (checked environment and {ROOT_ENV_FILE}).")

    try:
        safe_url = make_url(database_url).render_as_string(hide_password=True)
        engine = create_engine(database_url)
    except SQLAlchemyError as exc:
        fail(f"Invalid DATABASE_URL: {exc}")
    except ModuleNotFoundError as exc:
        fail(f"PostgreSQL driver not installed: {exc}")

    print(f"Connecting to {safe_url}")
    try:
        with engine.connect() as conn:
            if conn.execute(text("SELECT 1")).scalar_one() != 1:
                fail("SELECT 1 returned an unexpected value.")
            print("[OK] SELECT 1")

            db_name = conn.execute(text("SELECT current_database()")).scalar_one()
            print(f"[OK] Connected to database: {db_name}")

            vector_version = conn.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            ).scalar_one_or_none()
            if vector_version is None:
                fail(
                    "The 'vector' extension is not installed in this database. "
                    "Run: CREATE EXTENSION IF NOT EXISTS vector;"
                )
            print(f"[OK] pgvector extension installed (version {vector_version})")
    except SQLAlchemyError as exc:
        fail(f"Database error: {exc}")
    finally:
        engine.dispose()

    print("Database connection test passed.")


if __name__ == "__main__":
    main()
