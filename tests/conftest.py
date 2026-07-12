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
