"""Core data shapes shared across the pipeline: parse -> config -> render -> run."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Scope(str, Enum):
    """Where a plugin's config fields may appear."""

    GLOBAL = "global"
    CELL = "cell"
    BOTH = "both"


class Merge(str, Enum):
    """How a config field combines across layers (global -> cell -> overrides)."""

    OVERRIDE = "override"
    DEEP = "deep"
    EXTEND = "extend"


@dataclass
class RawBlock:
    """A parsed chunk of the file: the global header (name=None) or one cell.

    ``sql`` is the directive-stripped body; ``source`` is the untouched slice
    of the file (directives included) spanning lines ``line``..``line_end``.
    """

    name: str | None
    directives: dict[str, Any]
    sql: str
    line: int
    line_end: int = 0
    source: str = ""


@dataclass
class Cell:
    """A named cell with its merged+validated config and raw (unrendered) SQL."""

    name: str
    config: Any
    sql_raw: str
    hash: str
    line: int = 0


@dataclass
class RenderedCell:
    """A cell after Jinja rendering: final SQL, resolved engine/sink, edges."""

    name: str
    config: Any
    sql_raw: str
    sql: str
    hash: str
    engine: str
    sink_type: str
    depends_on: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)
    uses_sources: bool = False
    line: int = 0
    line_end: int = 0
    source: str = ""
    context: str = ""
    context_refs: list[str] = field(default_factory=list)
    external_refs: list[str] = field(default_factory=list)
    reffed_in_context: bool = False


@dataclass
class RunResult:
    """Outcome of running one cell: where it landed, how many rows, or the error."""

    cell: str
    ok: bool
    rows: int | None = None
    target: str | None = None
    elapsed: float = 0.0
    error: str | None = None
    preview: Any | None = None

    def pl(self) -> Any:
        """The Polars preview frame of the landed output (None on failure)."""
        return self.preview


@dataclass
class RunContext:
    """Per-run state handed to executors, sinks, and plugin `run` hooks."""

    conn: Any
    root: Path
    overrides: dict[str, Any] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    config: Any = None
    tmpdir: str | None = None
    ext_cache: set[str] = field(default_factory=set)
    session: Any = None
