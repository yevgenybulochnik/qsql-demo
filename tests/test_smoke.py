"""Smoke test: prove the package imports and the pytest harness runs."""

from __future__ import annotations


def test_package_imports() -> None:
    import qsql_demo

    assert qsql_demo is not None


def test_project_dir_fixture(project_dir) -> None:
    assert project_dir.is_dir()
