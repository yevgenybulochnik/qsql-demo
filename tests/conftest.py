"""Shared pytest fixtures for the qsql test suite.

Fixtures grow as the build proceeds (sample .qsql text, seed CSV, xlsx fixture,
in-memory DuckDB connection, a fresh plugin registry, ...). For now it only holds
what the smoke test needs.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """An isolated working directory for a qsql project under test."""
    return tmp_path


@pytest.fixture
def registries():
    """Snapshot the global plugin registries so a test's registrations don't leak.

    Ensures builtins are loaded, yields the plugin registry, and restores all
    four registries to their pre-test state afterwards.
    """
    import qsql_demo.executors  # noqa: F401  (import triggers executor registration)
    import qsql_demo.plugins  # noqa: F401  (import triggers plugin registration)
    import qsql_demo.sinks  # noqa: F401  (import triggers sink registration)
    import qsql_demo.sources  # noqa: F401  (import triggers source-reader registration)
    from qsql_demo.registry import EXECUTORS, PLUGINS, SINKS, SOURCE_READERS

    registries = (PLUGINS, EXECUTORS, SINKS, SOURCE_READERS)
    snaps = [(r, r.snapshot()) for r in registries]
    try:
        yield PLUGINS
    finally:
        for reg, snap in snaps:
            reg.restore(snap)
