import pytest

from quicksql.errors import ConfigError
from quicksql.overrides import gather_overrides, parse_env, parse_set


def test_parse_set_nested_and_yaml_scalars() -> None:
    got = parse_set(["output.type=duckdb", "vars.n=3", "autorun=false", "engine=sqlite"])
    assert got == {
        "output": {"type": "duckdb"},
        "vars": {"n": 3},
        "autorun": False,
        "engine": "sqlite",
    }


def test_parse_set_without_equals_raises() -> None:
    with pytest.raises(ConfigError, match="--set"):
        parse_set(["outputtype"])


def test_parse_env_prefix_and_nesting() -> None:
    got = parse_env({"QUICKSQL_OUTPUT__TYPE": "duckdb", "QUICKSQL_AUTORUN": "false", "PATH": "/bin"})
    assert got == {"output": {"type": "duckdb"}, "autorun": False}


def test_cli_set_wins_over_env() -> None:
    got = gather_overrides(["output.type=parquet"], {"QUICKSQL_OUTPUT__TYPE": "duckdb"})
    assert got["output"]["type"] == "parquet"
