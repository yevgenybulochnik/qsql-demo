"""Builtin file-source readers and source() resolution.

A ``source(name_or_path, **opts)`` reference resolves to a DuckDB reader
expression. Readers are a pluggable registry (``@source_reader``); the type is
taken from a declared source's ``type`` or inferred from the file extension.
Each reader may declare DuckDB ``requires`` extensions (e.g. ``excel``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from .errors import ConfigError
from .registry import SOURCE_READERS, SourceReaderRegistry, source_reader


@dataclass
class SourceSpec:
    """A resolved file source handed to a reader function."""

    name: str | None
    type: str
    path: str
    options: dict[str, Any] = field(default_factory=dict)


def _lit(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _fmt_opts(options: dict[str, Any]) -> str:
    if not options:
        return ""
    return ", " + ", ".join(f"{key} = {_lit(val)}" for key, val in options.items())


@source_reader("csv", extensions=(".csv", ".tsv"))
def _csv(spec: SourceSpec) -> str:
    return f"read_csv_auto('{spec.path}'{_fmt_opts(spec.options)})"


@source_reader("parquet", extensions=(".parquet", ".pq"))
def _parquet(spec: SourceSpec) -> str:
    return f"read_parquet('{spec.path}'{_fmt_opts(spec.options)})"


@source_reader("json", extensions=(".json", ".ndjson"))
def _json(spec: SourceSpec) -> str:
    return f"read_json_auto('{spec.path}'{_fmt_opts(spec.options)})"


@source_reader("excel", extensions=(".xlsx", ".xls"), requires=("excel",))
def _excel(spec: SourceSpec) -> str:
    return f"read_xlsx('{spec.path}'{_fmt_opts(spec.options)})"


def _select_reader(type_: str | None, path: str, registry: SourceReaderRegistry):
    if type_ is not None:
        reader = registry.get(type_)
        if reader is None:
            raise ConfigError(f"unknown source type: {type_!r}")
        return reader
    ext = os.path.splitext(str(path))[1].lower()
    reader = registry.for_extension(ext)
    if reader is None:
        raise ConfigError(f"cannot infer source type for {path!r}; add a `type`")
    return reader


def resolve_source(
    arg: str,
    sources_cfg: dict[str, Any] | None = None,
    extra_opts: dict[str, Any] | None = None,
    registry: SourceReaderRegistry = SOURCE_READERS,
) -> tuple[str, list[str]]:
    """Resolve ``source(arg, **opts)`` to ``(duckdb_reader_expr, required_extensions)``."""
    sources_cfg = sources_cfg or {}
    extra_opts = dict(extra_opts or {})

    if arg in sources_cfg:
        declared = dict(sources_cfg[arg])
        if "path" not in declared:
            raise ConfigError(f"source {arg!r} has no `path`")
        path = declared.pop("path")
        type_ = declared.pop("type", None)
        options = {**declared, **extra_opts}
        name: str | None = arg
    else:
        path = arg
        type_ = extra_opts.pop("type", None)
        options = extra_opts
        name = None

    reader = _select_reader(type_, path, registry)
    spec = SourceSpec(name=name, type=reader.name, path=path, options=options)
    return reader.func(spec), list(reader.requires)
