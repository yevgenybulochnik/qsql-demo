"""Tests for core enums, dataclasses, and plugin base classes."""

from __future__ import annotations

import pytest

from qsql_demo.models import (
    Executor,
    Merge,
    RawBlock,
    RunResult,
    Scope,
    Sink,
    body_hash,
)


def test_scope_members() -> None:
    assert {s.name for s in Scope} == {"GLOBAL", "CELL", "BOTH"}


def test_merge_members() -> None:
    assert {m.name for m in Merge} == {"OVERRIDE", "DEEP", "EXTEND"}


def test_body_hash_is_deterministic_and_content_sensitive() -> None:
    assert body_hash("SELECT 1") == body_hash("SELECT 1")
    assert body_hash("SELECT 1") != body_hash("SELECT 2")


def test_rawblock_header_vs_cell() -> None:
    header = RawBlock(name=None, directives={"engine": "duckdb"}, sql="")
    cell = RawBlock(name="users", directives={}, sql="SELECT 1")
    assert header.is_header
    assert not cell.is_header
    # hash is auto-computed from the body when not supplied
    assert cell.hash == body_hash("SELECT 1")


def test_runresult_ok_and_preview() -> None:
    ok = RunResult(name="x", target="data/x.parquet", rows=3, preview="frame")
    assert ok.ok
    assert ok.pl() == "frame"

    bad = RunResult(name="x", target="", error="boom")
    assert not bad.ok


def test_executor_and_sink_are_abstract() -> None:
    with pytest.raises(TypeError):
        Executor()  # type: ignore[abstract]
    with pytest.raises(TypeError):
        Sink()  # type: ignore[abstract]
