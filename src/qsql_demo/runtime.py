"""Shared runtime types used by executors, sinks, and the runner.

``ExecResult`` is what an executor hands to a sink; ``RunContext`` is the shared
state for a single run: the conduit DuckDB connection plus caches for backend
connections, ATTACHed databases, and loaded extensions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass
class ExecResult:
    """An executor's output: exactly one of ``sql`` (a DuckDB SELECT) or ``frame``."""

    sql: str | None = None
    frame: Any = None  # a polars.DataFrame


def as_subquery(sql: str) -> str:
    """Normalize rendered SQL for embedding inside ``COPY (...)`` / ``CREATE ... AS (...)``."""
    return sql.strip().rstrip(";").strip()


class RunContext:
    """Per-run state shared across executors and sinks."""

    def __init__(self, duck: Any, project_dir: str | Path) -> None:
        self.duck = duck  # the conduit DuckDB connection (universal reader/writer)
        self.project_dir = Path(project_dir)
        self._conns: dict[Any, Any] = {}
        self._attached: set[str] = set()
        self._loaded: set[str] = set()

    def get_conn(self, key: Any, factory: Callable[[], Any]) -> Any:
        """Return a cached backend connection, creating it via ``factory`` on first use."""
        if key not in self._conns:
            self._conns[key] = factory()
        return self._conns[key]

    def load_extension(self, name: str) -> None:
        if name in self._loaded:
            return
        self.duck.execute(f"INSTALL {name}")
        self.duck.execute(f"LOAD {name}")
        self._loaded.add(name)

    def ensure_attached(self, alias: str, attach_sql: str) -> None:
        if alias in self._attached:
            return
        self.duck.execute(attach_sql)
        self._attached.add(alias)

    def close(self) -> None:
        for conn in self._conns.values():
            try:
                conn.close()
            except Exception:
                pass
        try:
            self.duck.close()
        except Exception:
            pass
