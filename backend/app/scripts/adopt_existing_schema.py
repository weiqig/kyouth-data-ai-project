from __future__ import annotations

import sys
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app import models  # noqa: F401 - populate SQLAlchemy metadata
from app.db import Base, engine

BASELINE_REVISION = "0001_initial_phase1_schema"


def main() -> int:
    """Stamp legacy prototype databases that already contain the Phase 1 schema.

    This is intentionally not a schema migration. It only bridges databases that were
    created before Alembic became the schema authority. New empty databases are left
    alone so `alembic upgrade head` can create the schema normally.
    """
    try:
        with engine.begin() as connection:
            inspector = inspect(connection)
            existing_tables = set(inspector.get_table_names())

            if "alembic_version" in existing_tables:
                return 0

            managed_tables = set(Base.metadata.tables.keys())
            present_managed_tables = managed_tables & existing_tables

            if not present_managed_tables:
                return 0

            missing_tables = managed_tables - existing_tables
            if missing_tables:
                missing = ", ".join(sorted(missing_tables))
                present = ", ".join(sorted(present_managed_tables))
                print(
                    "Existing database contains part of the application schema. "
                    "Leaving it unstamped so Alembic can create any missing objects. "
                    f"Present tables: {present}. Missing tables: {missing}."
                )
                return 0

            connection.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                {"revision": BASELINE_REVISION},
            )
            print(f"Stamped existing Phase 1 schema as Alembic revision {BASELINE_REVISION}.")
            return 0
    except SQLAlchemyError as exc:
        print(f"Failed to inspect or stamp existing schema: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
