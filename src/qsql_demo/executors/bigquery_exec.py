"""BigQuery executor: extracts to Arrow, which DuckDB registers and lands anywhere.

Needs the ``bigquery`` extra (google-cloud-bigquery, pyarrow, db-dtypes).
"""

from __future__ import annotations

from typing import Any

from ..errors import ExecutorError
from ..models import RenderedCell, RunContext
from ..registry import executor
from .base import Executor, register_frame, result_view, strip_trailing_semicolon


@executor("bigquery")
class BigQueryExecutor(Executor):
    def context_key(self, config: Any) -> str:
        spec = (config.input or {}).get("bigquery") or {}
        return f"bigquery:{spec.get('project')}"

    def make_client(self, spec: dict[str, Any]) -> Any:
        """Split out so tests can substitute a fake client."""
        try:
            from google.cloud import bigquery
        except ImportError as exc:
            raise ExecutorError(
                "bigquery engine needs the 'bigquery' extra: uv sync --extra bigquery"
            ) from exc
        return bigquery.Client(project=spec.get("project"))

    def execute(self, cell: RenderedCell, ctx: RunContext) -> str:
        spec = (cell.config.input or {}).get("bigquery") or {}
        client = self.make_client(spec)
        table = client.query(strip_trailing_semicolon(cell.sql)).to_arrow()
        return register_frame(ctx, result_view(cell.name), table)
