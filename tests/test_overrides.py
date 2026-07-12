"""Tests for the CLI/env override layer."""

from __future__ import annotations

import pytest

from qsql_demo.errors import ConfigError
from qsql_demo.overrides import collect, from_cli, from_env


def test_from_cli_nesting_and_typing() -> None:
    assert from_cli(["a.b=1"]) == {"a": {"b": 1}}
    assert from_cli(["autorun=false"]) == {"autorun": False}
    assert from_cli(["output.type=duckdb"]) == {"output": {"type": "duckdb"}}


def test_from_cli_requires_equals() -> None:
    with pytest.raises(ConfigError):
        from_cli(["novalue"])


def test_from_env_prefix_and_double_underscore() -> None:
    env = {"QSQL_input__duckdb": "./x.db", "PATH": "/usr/bin", "QSQL_autorun": "true"}
    assert from_env(env) == {"input": {"duckdb": "./x.db"}, "autorun": True}


def test_collect_cli_beats_env() -> None:
    env = {"QSQL_autorun": "true"}
    assert collect(["autorun=false"], env) == {"autorun": False}
