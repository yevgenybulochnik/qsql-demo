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
    supports_context_refs = True

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

    def _session_state(self, cell: RenderedCell, ctx: RunContext, spec: dict[str, Any]) -> dict:
        """Per-context BigQuery session (temp tables live in it; sessions
        auto-expire server-side, so close() is a no-op)."""
        if ctx.session is None:
            return {"client": self.make_client(spec), "session_id": None}
        key = self.context_key(cell.config)
        if key not in ctx.session.engine_sessions:
            ctx.session.engine_sessions[key] = {
                "client": self.make_client(spec),
                "session_id": None,
            }
        return ctx.session.engine_sessions[key]

    def _job_config(self, state: dict) -> Any:
        """Split out so offline tests avoid the google import."""
        from google.cloud import bigquery

        if state["session_id"] is None:
            return bigquery.QueryJobConfig(create_session=True)
        return bigquery.QueryJobConfig(
            connection_properties=[
                bigquery.ConnectionProperty("session_id", state["session_id"])
            ]
        )

    def _query(self, state: dict, sql: str) -> Any:
        job = state["client"].query(sql, job_config=self._job_config(state))
        # query() only *submits*; sessions allow one active job at a time, so
        # wait for completion before the next statement goes in
        job.result()
        if state["session_id"] is None:
            info = getattr(job, "session_info", None)
            session_id = getattr(info, "session_id", None)
            if session_id:
                state["session_id"] = session_id
        return job

    def execute(self, cell: RenderedCell, ctx: RunContext) -> str:
        spec = (cell.config.input or {}).get("bigquery") or {}
        sql = strip_trailing_semicolon(cell.sql)
        if cell.reffed_in_context:
            # materialize once; the temp serves consumers, the read lands parquet
            state = self._session_state(cell, ctx, spec)
            self._query(state, f"CREATE OR REPLACE TEMP TABLE {cell.name} AS ({sql})")
            table = self._query(state, f"SELECT * FROM {cell.name}").to_arrow()
        elif cell.context_refs:
            # consumes session temps: run in-session, no temp of its own
            state = self._session_state(cell, ctx, spec)
            table = self._query(state, sql).to_arrow()
        else:  # no in-context participation: one plain job, as before
            table = self.make_client(spec).query(sql).to_arrow()
        return register_frame(ctx, result_view(cell.name), table)
