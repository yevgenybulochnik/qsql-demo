"""qsql — a notebook-like CLI for SQL with comment-driven, pluggable config."""

from __future__ import annotations

from .compiler import Project
from .parser import parse, parse_file

__all__ = ["Project", "parse", "parse_file"]
