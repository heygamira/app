"""The Alembic migration must build the schema the models describe.

Without this, a passing test suite — which creates tables from metadata — could
coexist with a migration that does not.

That is not hypothetical. ``0009`` shipped with ``created_at`` and ``updated_at``
declared ``NOT NULL`` and no ``server_default``. The ``Timestamps`` mixin gives
those columns a *server* default and no Python one, so SQLAlchemy leaves them
out of the INSERT and reads them back with ``RETURNING`` — which meant every
single insert into that table failed on a real database, while the whole suite
stayed green because it had built the table from the model. It was found by
running the app.

So this file compares the migrated schema to the models **column by column**,
not table by table. The table-name check below is what existed and what was not
enough.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, inspect

from alembic import command
from alembic.config import Config
from app.db.base import Base


@pytest.fixture(scope="module")
def migrated(tmp_path_factory):
    """One database, built by the migrations exactly as production is.

    Module-scoped: running every migration takes real time, and nothing here
    writes to it.
    """
    database_file = tmp_path_factory.mktemp("migrations") / "migrated.db"
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{database_file}"

    from app.core.config import get_settings

    get_settings.cache_clear()
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = Config(os.path.join(project_root, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(project_root, "alembic"))

    engine = None
    try:
        command.upgrade(config, "head")
        engine = create_engine(f"sqlite:///{database_file}")
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


def test_the_migration_creates_every_model_table(migrated):
    tables = set(inspect(migrated).get_table_names())
    expected = set(Base.metadata.tables)
    assert expected <= tables, f"missing tables: {sorted(expected - tables)}"


def test_the_migration_creates_every_model_column(migrated):
    """A column the code writes to has to exist in a migrated database."""
    inspector = inspect(migrated)
    live = {
        name: {column["name"] for column in inspector.get_columns(name)}
        for name in inspector.get_table_names()
    }

    missing: list[str] = []
    for name, table in Base.metadata.tables.items():
        for column in table.columns:
            if column.name not in live.get(name, set()):
                missing.append(f"{name}.{column.name}")
    assert not missing, f"columns the models declare but the migration omits: {missing}"


def test_a_column_the_orm_never_sends_has_a_database_default(migrated):
    """The bug this file exists for, stated as a rule.

    A column that is ``NOT NULL``, carries a ``server_default`` on the model and
    has no Python-side default is one SQLAlchemy deliberately leaves out of the
    INSERT. The database is then the only thing that can fill it, so the DDL
    must carry a DEFAULT. Every ``created_at`` and ``updated_at`` in the schema
    is exactly that shape.

    Checked against the migrated database rather than the model, because the
    model is the thing that is right and the migration is the thing that drifts.
    """
    inspector = inspect(migrated)
    live = {
        name: {column["name"]: column for column in inspector.get_columns(name)}
        for name in inspector.get_table_names()
    }

    undefaulted: list[str] = []
    for name, table in Base.metadata.tables.items():
        for column in table.columns:
            if column.nullable or column.default is not None:
                continue
            if column.server_default is None:
                continue
            found = live.get(name, {}).get(column.name)
            if found is not None and found.get("default") is None:
                undefaulted.append(f"{name}.{column.name}")

    assert not undefaulted, (
        "NOT NULL columns the ORM omits from its INSERT, with no DEFAULT in the "
        f"migration — every insert into these tables will fail: {undefaulted}"
    )


def test_the_migration_creates_every_model_index(migrated):
    """An index the models declare has to survive every migration after it.

    Not theory either. ``0010`` rebuilds ``wellbeing_checks`` — SQLite cannot add
    a DEFAULT to an existing column, so batch mode copies the table — and a
    rebuild keeps only what it was *told* about. The first version of it was
    told about the columns and the foreign keys and nothing else, so all five
    indexes were quietly dropped, including the one the escalation sweep scans
    every minute. Nothing would have failed; it would just have got slower every
    day.
    """
    inspector = inspect(migrated)
    live = {
        name: {index["name"] for index in inspector.get_indexes(name)}
        for name in inspector.get_table_names()
    }

    missing: list[str] = []
    for name, table in Base.metadata.tables.items():
        for index in table.indexes:
            if index.name not in live.get(name, set()):
                missing.append(f"{name}.{index.name}")
        # A column marked `index=True` gets its index from the naming
        # convention rather than an `Index` object, so it is not in
        # `table.indexes` and has to be looked for by name.
        for column in table.columns:
            if not column.index:
                continue
            expected = f"ix_{name}_{column.name}"
            if expected not in live.get(name, set()):
                missing.append(f"{name}.{expected}")

    assert not missing, f"indexes the models declare but a migration dropped: {missing}"
