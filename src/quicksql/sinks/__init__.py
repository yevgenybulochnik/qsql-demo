from .base import Sink, make_sink
from . import parquet_sink, duckdb_sink, postgres_sink  # noqa: F401  (self-register)

__all__ = ["Sink", "make_sink"]
