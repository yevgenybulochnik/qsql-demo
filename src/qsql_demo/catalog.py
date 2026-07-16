"""Drillable schema catalog: nodes that load a Polars frame and resolve children.

Pure data + blocking loaders; the TUI runs ``load()`` in a thread worker and
pushes the frame as a Sheet whose Enter drills via ``child``. Field-path frames
mirror BigQuery's ``information_schema.column_field_paths``: one row per path
level, intermediate STRUCTs included; a LIST wrapper adds no path segment.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import polars as pl

FIELD_PATH_SCHEMA = {"column": pl.Utf8, "field_path": pl.Utf8, "type": pl.Utf8, "mode": pl.Utf8}


def _field_path_frame(rows: list[tuple[str, str, str, str]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=FIELD_PATH_SCHEMA, orient="row")


def bq_field_paths(fields: Iterable[Any]) -> pl.DataFrame:
    """Flatten BigQuery SchemaFields (.name/.field_type/.mode/.fields) depth-first."""
    rows: list[tuple[str, str, str, str]] = []

    def walk(field: Any, column: str, prefix: str) -> None:
        path = f"{prefix}.{field.name}" if prefix else field.name
        rows.append((column, path, field.field_type, field.mode or ""))
        for sub in field.fields or ():
            walk(sub, column, path)

    for field in fields:
        walk(field, field.name, "")
    return _field_path_frame(rows)


def duckdb_field_paths(columns: Sequence[str], types: Sequence[Any]) -> pl.DataFrame:
    """Flatten DuckDBPyTypes (.id/.children) depth-first.

    ``.children`` raises on scalars, so recursion gates on ``.id``; fixed-size
    arrays carry a non-type child (the size), filtered by the ``.id`` check.
    """
    rows: list[tuple[str, str, str, str]] = []

    def walk(name: str, type_: Any, column: str, prefix: str) -> None:
        path = f"{prefix}.{name}" if prefix else name
        mode = "REPEATED" if type_.id in ("list", "array", "map") else ""
        rows.append((column, path, str(type_), mode))
        descend(type_, column, path)

    def descend(type_: Any, column: str, path: str) -> None:
        if type_.id == "struct":
            for sub_name, sub_type in type_.children:
                walk(sub_name, sub_type, column, path)
        elif type_.id in ("list", "array", "map"):
            # the collection wrapper adds no path segment: recurse into the
            # element type(s) under the collection's own path
            for _, sub_type in type_.children:
                if hasattr(sub_type, "id"):
                    descend(sub_type, column, path)

    for name, type_ in zip(columns, types):
        walk(name, type_, name, "")
    return _field_path_frame(rows)
