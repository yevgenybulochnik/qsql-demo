"""CLI smoke tests via Typer's CliRunner."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from qsql_demo.cli import app

runner = CliRunner()


def test_init_creates_and_refuses(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    first = runner.invoke(app, ["init"])
    assert first.exit_code == 0
    assert (tmp_path / "base.sql").exists()

    second = runner.invoke(app, ["init"])
    assert second.exit_code != 0  # refuses to overwrite


def test_bare_invocation_scaffolds(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, [])
    assert (tmp_path / "base.sql").exists()


def test_run_writes_parquet(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "data" / "active_users.parquet").exists()


def test_run_with_set_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["run", "--set", "output.dir=out"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "out" / "users.parquet").exists()


def test_list_shows_cells_and_order(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "users" in result.output
    assert "active_users" in result.output


def test_compile_prints_rendered_sql(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["compile"])
    assert result.exit_code == 0
    assert "read_parquet" in result.output


def test_run_reports_failure_nonzero(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "bad.sql").write_text("-- @cell boom\nSELECT * FROM nonexistent_table_xyz;\n")
    result = runner.invoke(app, ["run", "bad.sql"])
    assert result.exit_code != 0
