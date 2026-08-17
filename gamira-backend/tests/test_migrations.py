"""The Alembic migration must build the schema the models describe.

Without this, a passing test suite (which creates tables from metadata) could
coexist with a migration that no longer applies.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine, inspect

from alembic import command
from alembic.config import Config
from app.db.base import Base


def test_the_migration_creates_every_model_table(tmp_path, monkeypatch):
    database_file = tmp_path / "migrated.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_file}")

    from app.core.config import get_settings

    get_settings.cache_clear()

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = Config(os.path.join(project_root, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(project_root, "alembic"))

    try:
        command.upgrade(config, "head")

        engine = create_engine(f"sqlite:///{database_file}")
        try:
            tables = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()

    expected = set(Base.metadata.tables)
    assert expected <= tables, f"missing tables: {sorted(expected - tables)}"
