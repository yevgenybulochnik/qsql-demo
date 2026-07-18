import pytest
from pydantic import BaseModel, field_validator

from quicksql.config import (
    build_models,
    resolve_cell,
    resolve_engine,
    resolve_global,
    resolve_sink_type,
)
from quicksql.errors import ConfigError
from quicksql.models import Merge, Scope
from quicksql.plugins.base import Plugin, qfield
from quicksql.registry import plugin


def test_build_models_fields_and_defaults() -> None:
    GlobalConfig, CellConfig = build_models()
    g = GlobalConfig()
    assert g.engine is None
    assert g.output == {"type": "parquet", "dir": "data/"}
    assert g.autorun is True
    assert g.vars == {}
    c = CellConfig()
    assert c.depends_on == []
    assert "depends_on" not in GlobalConfig.model_fields


def test_mutable_defaults_are_isolated() -> None:
    _, CellConfig = build_models()
    a, b = CellConfig(), CellConfig()
    a.vars["x"] = 1
    assert b.vars == {}


def test_unknown_directive_raises() -> None:
    with pytest.raises(ConfigError, match="unknown directive: @bogus"):
        resolve_global({"bogus": 1})


def test_scope_violation_raises() -> None:
    with pytest.raises(ConfigError, match="@depends_on is not allowed in global scope"):
        resolve_global({"depends_on": ["a"]})


def test_merge_precedence_global_cell_override() -> None:
    cfg = resolve_cell(
        {"engine": "duckdb", "vars": {"a": 1, "b": 2}},
        {"engine": "sqlite", "vars": {"b": 3}},
        overrides={"vars": {"c": 4}},
    )
    assert cfg.engine == "sqlite"                     # OVERRIDE: cell beats global
    assert cfg.vars == {"a": 1, "b": 3, "c": 4}       # DEEP merge across layers


def test_deep_merge_output_keeps_unset_keys() -> None:
    cfg = resolve_cell({"output": {"dir": "out/"}}, {}, overrides={"output": {"type": "duckdb"}})
    assert cfg.output["dir"] == "out/"
    assert cfg.output["type"] == "duckdb"


def test_extend_merge_concatenates_lists() -> None:
    cfg = resolve_cell({"extensions": ["excel"]}, {"extensions": ["postgres"]})
    assert cfg.extensions == ["excel", "postgres"]


def test_validator_rejects_unknown_sink_type() -> None:
    with pytest.raises(ConfigError, match="output.type"):
        resolve_cell({}, {"output": {"type": "carrier_pigeon"}})


def test_validator_rejects_unknown_engine() -> None:
    with pytest.raises(ConfigError, match="engine"):
        resolve_cell({}, {"engine": "abacus"})


def test_validator_rejects_non_string_extensions() -> None:
    with pytest.raises(ConfigError):
        resolve_cell({}, {"extensions": [1, 2]})


def test_resolve_engine_explicit_inferred_default() -> None:
    assert resolve_engine(resolve_cell({}, {"engine": "sqlite"})) == "sqlite"
    assert resolve_engine(resolve_cell({}, {"input": {"sqlite": "db.db"}})) == "sqlite"
    assert resolve_engine(resolve_cell({}, {})) == "duckdb"


def test_resolve_engine_ambiguous_input_raises() -> None:
    cfg = resolve_cell({}, {"input": {"sqlite": "a", "duckdb": "b"}})
    with pytest.raises(ConfigError, match="infer"):
        resolve_engine(cfg)


def test_resolve_sink_type_default_and_override() -> None:
    assert resolve_sink_type(resolve_cell({}, {})) == "parquet"
    assert resolve_sink_type(resolve_cell({}, {"output": {"type": "duckdb"}})) == "duckdb"


def test_schema_alias_field() -> None:
    cfg = resolve_cell({}, {"schema": "analytics"})
    assert cfg.schema_ == "analytics"


def test_third_party_config_plugin_extends_models() -> None:
    @plugin
    class RowLimit(Plugin):
        scope = Scope.CELL

        class Config(BaseModel):
            row_limit: int | None = qfield(None)

            @field_validator("row_limit")
            @classmethod
            def positive(cls, v: int | None) -> int | None:
                if v is not None and v <= 0:
                    raise ValueError("row_limit must be positive")
                return v

    cfg = resolve_cell({}, {"row_limit": 10})
    assert cfg.row_limit == 10
    with pytest.raises(ConfigError, match="positive"):
        resolve_cell({}, {"row_limit": -1})
    with pytest.raises(ConfigError, match="not allowed in global scope"):
        resolve_global({"row_limit": 5})


def test_duplicate_validator_names_across_plugins_are_rejected() -> None:
    # pydantic composes plugin Configs by inheritance, so a validator whose
    # attribute name repeats an existing one (e.g. Sources' _shape) silently
    # shadows it in the MRO — the guard must fail loudly instead
    @plugin
    class Shadowing(Plugin):
        class Config(BaseModel):
            widgets: list[str] = qfield([])

            @field_validator("widgets")
            @classmethod
            def _shape(cls, v: list[str]) -> list[str]:  # clashes with Sources
                return v

    with pytest.raises(ConfigError, match="_shape"):
        build_models()


def test_override_keys_scoped_to_target_model() -> None:
    # global-only override keys are dropped when resolving cells, not errors
    @plugin
    class Auditish(Plugin):
        scope = Scope.GLOBAL

        class Config(BaseModel):
            audit_dir: str | None = qfield(None)

    g = resolve_global({}, overrides={"audit_dir": "build/"})
    assert g.audit_dir == "build/"
    c = resolve_cell({}, {}, overrides={"audit_dir": "build/"})
    assert not hasattr(c, "audit_dir")


def test_unknown_override_key_raises() -> None:
    with pytest.raises(ConfigError, match="unknown directive: @zap"):
        resolve_cell({}, {}, overrides={"zap": 1})
