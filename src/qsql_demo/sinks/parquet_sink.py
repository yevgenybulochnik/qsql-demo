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

    def write(self, cell: RenderedCell, view: str, conn: Any) -> tuple[int, str]:
        target = self.path(cell.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        (rows,) = conn.execute(
            f"COPY (SELECT * FROM \"{view}\") TO '{target}' (FORMAT PARQUET)"
        ).fetchone()
        return int(rows), str(target)

    def ref_expr(self, cell_name: str) -> str:
        return f"read_parquet('{self.path(cell_name)}')"
