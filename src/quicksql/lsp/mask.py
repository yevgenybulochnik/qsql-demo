"""Length-preserving Jinja mask: rewrite SQL-with-Jinja into plain SQL sqlglot
can parse, without moving a single character.

Each Jinja run is replaced in place by text of the *same length* so every
offset (and line/column) outside it is unchanged — sqlglot error positions and
the editor cursor map 1:1 back to the buffer. Single-line ``{{ ref/source }}``
expressions become a bare identifier that reads as a table in FROM/JOIN scope
(recorded so a completion request can map the alias back to real columns).
Other single-line ``{{ }}`` expressions also become an identifier — never
spaces, which would leave a dangling operator in ``x > {{ var('d') }}`` —
except that a bare ``{{ var('key') }}`` whose value is known and fits is
replaced by the value itself (space-padded), the same text the runtime render
produces. ``{% %}`` control tags, comments, and any multi-line run blank to
spaces (with newlines kept, so line numbers hold).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


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
    """One masked region. ``name`` is the placeholder identifier standing in
    for a ``{{ }}`` expression (None for space-blanked runs and substituted
    var values, whose masked text is not a placeholder)."""

    start: int
    end: int
    name: str | None
    tag: Tag


_JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)
_REF = re.compile(r"\bref\(\s*['\"]([^'\"]+)['\"]")
_SOURCE = re.compile(r"\bsource\(\s*['\"]([^'\"]+)['\"]")
# a bare var('key') / var('key', default) call and nothing else
_BARE_VAR = re.compile(r"^\s*var\(\s*['\"]([^'\"]+)['\"]\s*(?:,[^)]*)?\)\s*$")


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


def _var_value(inner: str, length: int, values: Mapping[str, Any]) -> str | None:
    """The runtime rendering of a bare ``var('key')`` body, space-padded to
    ``length`` — or None when the key is unknown or the value doesn't fit."""
    m = _BARE_VAR.match(inner)
    if m is None or m.group(1) not in values:
        return None
    text = str(values[m.group(1)])
    if "\n" in text or len(text) > length:
        return None
    return text + " " * (length - len(text))


def mask_jinja(
    sql: str, var_values: Mapping[str, Any] | None = None
) -> tuple[str, list[MaskSpan]]:
    """Return (masked_sql, spans). ``len(masked_sql) == len(sql)`` and newlines
    are preserved; ``spans`` records what each masked region stood for.
    ``var_values`` (the cell's merged ``vars:``) enables in-place substitution
    of bare ``{{ var('key') }}`` expressions."""
    out: list[str] = []
    spans: list[MaskSpan] = []
    pos = 0
    for i, m in enumerate(_JINJA.finditer(sql)):
        out.append(sql[pos : m.start()])
        run = m.group(0)
        is_expr = run.startswith("{{") and "\n" not in run
        if not is_expr:
            out.append(_blank(run))
            spans.append(MaskSpan(m.start(), m.end(), None, Opaque()))
            pos = m.end()
            continue
        inner = run[2:-2]
        tag, table_like = _tag_for(inner)
        value = None if table_like else _var_value(inner, len(run), var_values or {})
        if value is not None:
            out.append(value)
            spans.append(MaskSpan(m.start(), m.end(), None, tag))
        else:
            name = _placeholder(i, len(run))
            out.append(name)
            spans.append(MaskSpan(m.start(), m.end(), name, tag))
        pos = m.end()
    out.append(sql[pos:])
    return "".join(out), spans
