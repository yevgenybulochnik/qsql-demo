"""Importing this package self-registers the builtin executors."""

from __future__ import annotations

from . import duckdb_exec  # noqa: F401
from . import sqlite_exec  # noqa: F401
