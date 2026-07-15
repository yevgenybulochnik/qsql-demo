from .base import Executor
from . import duckdb_exec, sqlite_exec, bigquery_exec, postgres_exec  # noqa: F401  (self-register)

__all__ = ["Executor"]
