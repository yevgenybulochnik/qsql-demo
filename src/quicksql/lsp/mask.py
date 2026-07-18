"""Length-preserving Jinja mask: rewrite SQL-with-Jinja into plain SQL sqlglot
can parse, without moving a single character.

Each Jinja run is replaced in place by text of the *same length* so every
offset (and line/column) outside it is unchanged — sqlglot error positions and
the editor cursor map 1:1 back to the buffer. Single-line ``{{ ref/source }}``
expressions become a bare identifier that reads as a table in FROM/JOIN scope
(recorded so a completion request can map the alias back to real columns);
``{% %}`` control tags, comments, and any multi-line run blank to spaces (with
newlines kept, so line numbers hold).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Ref:
    """A ``{{ ref('cell') }}`` — stands in for that cell's landed output."""

    cell: str


@dataclass(frozen=True)
class Source:
    """A ``{{ source('spec') }}`` — the string spec, or None for the dict form."""

    spec: str | None


@dataclass(frozen=True)
class Opaque:
    """Any other Jinja run (var/env/config expr, control tag, comment)."""


Tag = Ref | Source | Opaque


@dataclass(frozen=True)
class MaskSpan:
    """One masked region. ``name`` is the placeholder identifier for a
    table-like ``{{ }}`` expression (else None, for space-blanked runs)."""

    start: int
    end: int
    name: str | None
    tag: Tag


_JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)
_REF = re.compile(r"\bref\(\s*['\"]([^'\"]+)['\"]")
_SOURCE = re.compile(r"\bsource\(\s*['\"]([^'\"]+)['\"]")


def _placeholder(index: int, length: int) -> str:
    """A unique, all-lowercase SQL identifier of exactly ``length`` chars. The
    ``q<index>`` prefix keeps it unique; ``q`` padding fills the rest."""
    base = f"q{index}"[:length]
    return (base + "q" * (length - len(base)))[:length]


def _blank(text: str) -> str:
    """Same-length blanking that preserves newlines (so line numbers hold)."""
    return "".join("\n" if c == "\n" else " " for c in text)


def _tag_for(inner: str) -> tuple[Tag, bool]:
    """Classify a ``{{ ... }}`` body; the bool is whether it's table-like (gets
    an identifier placeholder rather than being blanked)."""
    m = _REF.search(inner)
    if m:
        return Ref(m.group(1)), True
    m = _SOURCE.search(inner)
    if m:
        return Source(m.group(1)), True
    return Opaque(), False


def mask_jinja(sql: str) -> tuple[str, list[MaskSpan]]:
    """Return (masked_sql, spans). ``len(masked_sql) == len(sql)`` and newlines
    are preserved; ``spans`` records what each masked region stood for."""
    out: list[str] = []
    spans: list[MaskSpan] = []
    pos = 0
    for i, m in enumerate(_JINJA.finditer(sql)):
        out.append(sql[pos : m.start()])
        run = m.group(0)
        is_expr = run.startswith("{{") and "\n" not in run
        tag: Tag = Opaque()
        table_like = False
        if is_expr:
            tag, table_like = _tag_for(run[2:-2])
        if table_like:
            name = _placeholder(i, len(run))
            out.append(name)
            spans.append(MaskSpan(m.start(), m.end(), name, tag))
        else:
            out.append(_blank(run))
            spans.append(MaskSpan(m.start(), m.end(), None, tag))
        pos = m.end()
    out.append(sql[pos:])
    return "".join(out), spans
