import pytest

from qsql_demo import registry
from qsql_demo.bootstrap import load_builtins


@pytest.fixture(autouse=True)
def fresh_registries():
    """Snapshot every registry so tests can register scratch plugins freely."""
    load_builtins()
    snaps = [(r, r.snapshot()) for r in registry.ALL_REGISTRIES]
    yield
    for reg, snap in snaps:
        reg.restore(snap)


@pytest.fixture
def project_dir(tmp_path):
    (tmp_path / "seeds").mkdir()
    (tmp_path / "seeds" / "users.csv").write_text(
        "user_id,name,active\n1,ada,true\n2,bob,false\n3,cyd,true\n"
    )
    return tmp_path
