"""Sink: where a cell's result lands, and how downstream cells read it back.

Sinks are the cross-cell interchange: ``write`` materializes the result at the
destination; ``ref_expr`` is the DuckDB-readable expression a downstream cell's
``ref()`` renders to. Instantiated per cell from the merged output config.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar

from ..models import RenderedCell


class Sink(ABC):
    name: ClassVar[str] = ""
    requires: ClassVar[list[str]] = []  # duckdb extensions, e.g. "postgres"

    def __init__(self, cfg: dict[str, Any], root: Path) -> None:
        self.cfg = cfg
        self.root = root

    def prepare(self, conn: Any) -> None:
        """Make the destination reachable on the conduit (ATTACH, mkdir, ...)."""

    @abstractmethod
    def write(self, cell: RenderedCell, view: str, conn: Any) -> tuple[int, str]:
        """Land the result view at the destination; return (rows, target)."""

    @abstractmethod
    def ref_expr(self, cell_name: str) -> str:
        """DuckDB expression for reading this cell's landed output back."""


def path_alias(prefix: str, key: str) -> str:
    """Deterministic ATTACH alias so separately-built sink instances agree."""
    return f"{prefix}_{hashlib.sha1(key.encode()).hexdigest()[:8]}"


def make_sink(config: Any, root: Path) -> Sink:
    """Build the sink for a cell's merged config (output + schema fallback)."""
    from ..config import resolve_sink_type
    from ..registry import SINKS

    cfg = dict(config.output or {})
    if "schema" not in cfg and getattr(config, "schema_", None):
        cfg["schema"] = config.schema_
    return SINKS.get(resolve_sink_type(config))(cfg, root)
