"""Importing this package self-registers the builtin sinks."""

from __future__ import annotations

from . import duckdb_sink  # noqa: F401
from . import parquet_sink  # noqa: F401
