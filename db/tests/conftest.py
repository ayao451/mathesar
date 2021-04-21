"""
This file should provide utilities for setting up test DBs and the like.  It's
intended to be the containment zone for anything specific about the testing
environment (e.g., the login info for the Postgres instance for testing)
"""
import pytest
from sqlalchemy import create_engine, text
from config.settings import DATABASES

TEST_DB = "mathesar_db_test_database"


@pytest.fixture(scope="session")
def test_db():
    superuser_engine = _get_superuser_engine()
    with superuser_engine.connect() as conn:
        # We need to use raw SQL here, since the goal is to end the transaction
        # block started by `superuser_engine.connect()`, but `conn.commit()`
        # doesn't seem to end empty transaction blocks.
        # TODO Figure out why that is.
        conn.execute(text("COMMIT"))
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB}"))
    yield TEST_DB
    with superuser_engine.connect() as conn:
        conn.execute(text("COMMIT"))
        conn.execute(text(f"DROP DATABASE {TEST_DB} WITH (FORCE)"))


@pytest.fixture
def engine(test_db):
    return create_engine(
        _get_connection_string(
            DATABASES["default"]["USER"],
            DATABASES["default"]["PASSWORD"],
            DATABASES["default"]["HOST"],
            test_db,
        ),
        future=True,
    )


def _get_superuser_engine():
    return create_engine(
        _get_connection_string(
            username=DATABASES["default"]["USER"],
            password=DATABASES["default"]["PASSWORD"],
            hostname=DATABASES["default"]["HOST"],
            database=DATABASES["default"]["NAME"],
        ),
        future=True,
    )


def _get_connection_string(username, password, hostname, database):
    return f"postgresql://{username}:{password}@{hostname}/{database}"