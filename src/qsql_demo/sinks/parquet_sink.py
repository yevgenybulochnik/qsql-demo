"""Default sink: one parquet file per cell in output dir (default data/)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import RenderedCell
from ..registry import sink
from .base import Sink


@sink("parquet")
class ParquetSink(Sink):
    def path(self, cell_name: str) -> Path:
        return self.root / self.cfg.get("dir", "data/") / f"{cell_name}.parquet"

    def _select_list(self, view: str, conn: Any) -> str:
        """duckdb's parquet writer stores HUGEINT as DOUBLE — silent precision
        loss. Cast to DECIMAL(38,0): exact for anything that fits, and a loud
        conversion error (instead of corruption) for 39-digit extremes."""
        columns = conn.execute(f'DESCRIBE SELECT * FROM "{view}"').fetchall()
        if not any(col_type in ("HUGEINT", "UHUGEINT") for _, col_type, *_ in columns):
            return "*"
        parts = []
        for name, col_type, *_ in columns:
            quoted = '"' + name.replace('"', '""') + '"'
            if col_type in ("HUGEINT", "UHUGEINT"):
                parts.append(f"CAST({quoted} AS DECIMAL(38,0)) AS {quoted}")
            else:
                parts.append(quoted)
        return ", ".join(parts)

    def write(self, cell: RenderedCell, view: str, conn: Any) -> tuple[int, str]:
        target = self.path(cell.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        select = self._select_list(view, conn)
        (rows,) = conn.execute(
            f"COPY (SELECT {select} FROM \"{view}\") TO '{target}' (FORMAT PARQUET)"
        ).fetchone()
        return int(rows), str(target)

    def ref_expr(self, cell_name: str) -> str:
        return f"read_parquet('{self.path(cell_name)}')"
