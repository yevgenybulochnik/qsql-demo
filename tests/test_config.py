"""Tests for dynamic config models, merge/override resolution, and engine/sink resolution."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from qsql_demo.config import (
    build_models,
    resolve_cell,
    resolve_engine,
    resolve_sink,
)
from qsql_demo.errors import ConfigError
from qsql_demo.models import Scope
from qsql_demo.plugins.base import Plugin, qfield
from qsql_demo.registry import PluginRegistry


def test_cellconfig_defaults() -> None:
    _, Cell = build_models()
    c = Cell()
    assert c.autorun is True
    assert c.output == {"type": "parquet", "dir": "data/"}
    assert c.vars == {}
    assert c.depends_on == []


def test_globalconfig_excludes_cell_only_directives() -> None:
    Global, Cell = build_models()
    assert "depends_on" not in Global.model_fields
    assert "depends_on" in Cell.model_fields


def test_mutable_defaults_are_not_shared() -> None:
    _, Cell = build_models()
    a, b = Cell(), Cell()
    a.vars["x"] = 1
    assert b.vars == {}


def test_deep_merge_vars_and_scalar_override() -> None:
    cfg = resolve_cell(
        header={"engine": "duckdb", "vars": {"a": 1}},
        cell={"vars": {"b": 2}, "autorun": False},
        overrides={},
    )
    assert cfg.engine == "duckdb"
    assert cfg.vars == {"a": 1, "b": 2}
    assert cfg.autorun is False


def test_override_layer_beats_cell() -> None:
    cfg = resolve_cell(header={}, cell={"autorun": False}, overrides={"autorun": True})
    assert cfg.autorun is True


def test_depends_on_extends_across_sources() -> None:
    cfg = resolve_cell(header={}, cell={"depends_on": ["a"]}, overrides={"depends_on": ["b"]})
    assert cfg.depends_on == ["a", "b"]


def test_engine_resolution_explicit_inferred_and_default() -> None:
    assert resolve_engine(resolve_cell({}, {"engine": "bigquery"}, {})) == "bigquery"
    assert resolve_engine(resolve_cell({}, {"input": {"bigquery": {"project": "p"}}}, {})) == "bigquery"
    assert resolve_engine(resolve_cell({}, {}, {})) == "duckdb"


def test_engine_ambiguous_multiple_inputs_raises() -> None:
    cfg = resolve_cell({}, {"input": {"duckdb": "x", "bigquery": {}}}, {})
    with pytest.raises(ConfigError):
        resolve_engine(cfg)


def test_sink_resolution_default_and_override() -> None:
    assert resolve_sink(resolve_cell({}, {}, {})) == "parquet"
    cfg = resolve_cell({}, {"output": {"type": "duckdb", "path": "w.db"}}, {})
    assert resolve_sink(cfg) == "duckdb"


def test_unknown_directive_raises() -> None:
    with pytest.raises(ConfigError):
        resolve_cell({}, {"bogus": 1}, {})


def test_cell_only_directive_in_header_raises() -> None:
    with pytest.raises(ConfigError):
        resolve_cell({"depends_on": ["a"]}, {}, {})


def test_unknown_sink_type_rejected_at_resolution() -> None:
    with pytest.raises(ConfigError, match="unknown sink type"):
        resolve_cell({}, {"output": {"type": "bogus"}}, {})


def test_build_models_composes_plugin_configs_with_validators() -> None:
    reg = PluginRegistry()

    class Retries(Plugin):
        name = "retries"
        scope = Scope.BOTH

        class Config(BaseModel):
            retries: int = qfield(0, ge=0)

    reg.register(Retries)
    _, Cell = build_models(reg)
    assert Cell(retries=2).retries == 2
    with pytest.raises(ValidationError):
        Cell(retries=-1)
    with pytest.raises(ValidationError):
        Cell(bogus=1)  # extra="forbid" still applies
