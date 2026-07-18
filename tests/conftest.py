import os

import pytest

from quicksql import registry
from quicksql.bootstrap import load_builtins


@pytest.fixture(autouse=True)
def fresh_registries():
    """Snapshot every registry so tests can register scratch plugins freely."""
    load_builtins()
    snaps = [(r, r.snapshot()) for r in registry.ALL_REGISTRIES]
    yield
    for reg, snap in snaps:
        reg.restore(snap)


@pytest.fixture
def pg_dsn():
    """DSN of the compose Postgres's test database (docker compose up -d --wait);
    postgres-marked tests skip when psycopg or the server is unavailable."""
    dsn = os.environ.get(
        "QUICKSQL_TEST_PG_DSN", "postgresql://quicksql:quicksql@localhost:5432/quicksql_test"
    )
    psycopg = pytest.importorskip(
        "psycopg", reason="postgres tests need the 'postgres' extra"
    )
    try:
        psycopg.connect(dsn, connect_timeout=2).close()
    except psycopg.OperationalError as exc:
        pytest.skip(f"no postgres server at {dsn}: {exc}")
    return dsn


@pytest.fixture
def project_dir(tmp_path):
    (tmp_path / "seeds").mkdir()
    (tmp_path / "seeds" / "users.csv").write_text(
        "user_id,name,active\n1,ada,true\n2,bob,false\n3,cyd,true\n"
    )
    return tmp_path
