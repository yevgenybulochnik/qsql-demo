"""The BigQuery executor (optional extra).

Runs a cell's SQL on BigQuery and materializes the result as a Polars frame, so
its output lands as local parquet like any other engine. ``google-cloud-bigquery``
is imported lazily (inside ``_client``) so this module imports without the extra;
real runs need credentials and are covered by a marker-gated test.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from ..models import Executor, RenderedCell
from ..registry import executor
from ..runtime import ExecResult, RunContext


@executor("bigquery")
class BigQueryExecutor(Executor):
    reads_parquet = False

    def _client(self, config: Any, ctx: RunContext | None) -> Any:  # pragma: no cover - needs creds
        from google.cloud import bigquery

        project = (getattr(config, "input", {}) or {}).get("bigquery", {}).get("project")
        factory = lambda: bigquery.Client(project=project)
        return ctx.get_conn(("bigquery", project), factory) if ctx else factory()

    def run(self, cell: RenderedCell, ctx: RunContext | None) -> ExecResult:
        client = self._client(cell.config, ctx)
        job = client.query(cell.sql)
        rows = [dict(row) for row in job.result()]
        return ExecResult(frame=pl.DataFrame(rows))
