"""Core data structures and plugin base classes shared across qsql.

Kept dependency-light on purpose: these types are imported everywhere, so they
avoid pulling in duckdb/polars/pydantic. The typed config objects attached to
``Cell.config`` are pydantic models built dynamically in ``config.py``.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Scope(Enum):
    """Where a directive may appear."""

    GLOBAL = "global"  # header only
    CELL = "cell"  # cell only
    BOTH = "both"  # header default, cell override


class Merge(Enum):
    """How a cell value combines with the inherited global value."""

    OVERRIDE = "override"  # cell replaces global (scalars)
    DEEP = "deep"  # recursive dict merge (e.g. vars/input/output)
    EXTEND = "extend"  # list concatenation (e.g. depends_on/extensions)


def body_hash(sql: str) -> str:
    """Stable content hash of a cell's SQL body (drives watch's change detection)."""
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


@dataclass
class RawBlock:
    """A block straight out of the parser: the global header or a named cell.

    ``name is None`` marks the global header. ``hash`` is auto-derived from the
    SQL body when not supplied.
    """

    name: str | None
    directives: dict[str, Any]
    sql: str
    hash: str = ""

    def __post_init__(self) -> None:
        if not self.hash:
            self.hash = body_hash(self.sql)

    @property
    def is_header(self) -> bool:
        return self.name is None


@dataclass
class Cell:
    """A named cell with its raw SQL body and resolved (typed) config."""

    name: str
    sql_raw: str
    config: Any  # a dynamically-built CellConfig pydantic instance
    hash: str = ""

    def __post_init__(self) -> None:
        if not self.hash:
            self.hash = body_hash(self.sql_raw)


@dataclass
class RenderedCell:
    """A cell after Jinja rendering, with its resolved engine/sink and edges."""

    name: str
    config: Any
    sql: str  # rendered SQL that actually runs
    sql_raw: str  # source SQL as written (for the TUI raw/rendered toggle)
    engine: str
    sink: Any
    refs: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    hash: str = ""


@dataclass
class RunResult:
    """Outcome of running one cell."""

    name: str
    target: str  # parquet path or table identifier the result landed in
    rows: int | None = None
    elapsed: float | None = None
    error: str | None = None
    preview: Any = None  # a polars DataFrame for the TUI (optional)

    @property
    def ok(self) -> bool:
        return self.error is None

    def pl(self) -> Any:
        """The Polars preview frame, if one was captured."""
        return self.preview


class Directive:
    """Base for a config directive plugin.

    Subclasses declare the config key via class attributes; the registry reads
    ``key``/``annotation``/``default`` to assemble the pydantic config models and
    uses ``scope``/``merge`` during resolution. Behavior hooks (if any) are added
    by subclasses.
    """

    key: str
    scope: Scope = Scope.CELL
    annotation: Any = str
    default: Any = None
    merge: Merge = Merge.OVERRIDE


class Executor(ABC):
    """Base for an engine plugin: runs a cell's SQL on a backend."""

    name: str = ""
    reads_parquet: bool = False

    @abstractmethod
    def connect(self, cfg: Any) -> Any:
        """Open (or return a cached) connection for the given resolved config."""

    @abstractmethod
    def run(self, cell: RenderedCell, conn: Any) -> Any:
        """Execute the cell and return a result relation DuckDB can consume."""


class Sink(ABC):
    """Base for an output plugin: lands a cell's result and exposes how to read it back."""

    name: str = ""
    requires: list[str] = []  # duckdb extensions to LOAD (e.g. "postgres")

    @abstractmethod
    def prepare(self, cfg: Any, duck: Any) -> None:
        """Set up the conduit DuckDB connection (ATTACH targets, LOAD extensions)."""

    @abstractmethod
    def write(self, cell: RenderedCell, relation: Any, duck: Any) -> RunResult:
        """Materialize the cell's result at the destination."""

    @abstractmethod
    def ref_expr(self, cell: RenderedCell) -> str:
        """A DuckDB-readable expression a downstream cell uses to read this output."""
