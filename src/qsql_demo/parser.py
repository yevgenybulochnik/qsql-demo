"""Parse a .qsql file into a global header + named cell blocks.

A .qsql file is valid SQL whose configuration lives in ``@``-marked comments:

- **Line directives** ``-- @key: value`` — a contiguous run is stripped of the
  ``-- `` prefix (and the leading ``@`` on each top-level key), joined, and parsed
  as one YAML document. Indented ``--`` continuation lines carry nested YAML.
- **Block directives** ``/*@ ... */`` — the body is taken verbatim as a YAML doc.
- **Cell markers** ``-- @cell <name>`` open a new cell. Everything before the first
  marker is the global header.

Directive values are literal (no templating here). Plain ``--`` and ``/* */``
comments (without ``@``) pass through into the SQL body.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import ParseError
from .models import RawBlock
from .util import deep_merge

_CELL_RE = re.compile(r"^cell\b\s*(\S+)?\s*$")


@dataclass
class _Accum:
    """Mutable accumulator for one block while scanning."""

    name: str | None
    fragments: list[str] = field(default_factory=list)  # YAML directive fragments
    body: list[str] = field(default_factory=list)  # raw SQL body lines


def _strip_comment(line: str) -> str | None:
    """Return the text after a leading ``--`` (one following space removed), or None."""
    s = line.lstrip()
    if not s.startswith("--"):
        return None
    rest = s[2:]
    if rest.startswith(" "):
        rest = rest[1:]
    return rest


def _load_fragment(fragment: str) -> dict[str, Any]:
    text = fragment.strip()
    if not text:
        return {}
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:  # pragma: no cover - message varies by input
        raise ParseError(f"invalid directive YAML: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ParseError(f"directive block must be a YAML mapping, got: {text!r}")
    return data


def parse(text: str) -> list[RawBlock]:
    """Parse .qsql source into ``[header, *cells]``; the header is always first."""
    accums: list[_Accum] = [_Accum(name=None)]
    current = accums[0]

    run: list[str] | None = None  # active line-directive run
    in_block = False
    block_buf: list[str] = []

    def flush_run() -> None:
        nonlocal run
        if run is not None:
            current.fragments.append("\n".join(run))
            run = None

    for raw_line in text.splitlines():
        if in_block:
            if "*/" in raw_line:
                block_buf.append(raw_line.split("*/", 1)[0])
                current.fragments.append("\n".join(block_buf))
                in_block = False
                block_buf = []
            else:
                block_buf.append(raw_line)
            continue

        lead = raw_line.lstrip()

        # Block directive: /*@ ... */
        if lead.startswith("/*@"):
            flush_run()
            after = lead[len("/*@") :]
            if "*/" in after:
                current.fragments.append(after.split("*/", 1)[0])
            else:
                in_block = True
                block_buf = [after]
            continue

        content = _strip_comment(raw_line)
        if content is not None:
            if content.startswith("@"):
                directive = content[1:]
                if directive.lstrip().startswith("cell"):
                    m = _CELL_RE.match(directive.strip())
                    if not m or not m.group(1):
                        raise ParseError("@cell requires a name")
                    flush_run()
                    current = _Accum(name=m.group(1))
                    accums.append(current)
                    continue
                # a top-level directive key (starts/continues a run)
                if run is None:
                    run = []
                run.append(directive)
                continue
            # a plain comment line
            if run is not None and content[:1] in (" ", "\t"):
                run.append(content)  # indented YAML continuation
                continue
            flush_run()
            current.body.append(raw_line)  # ordinary comment -> body
            continue

        # non-comment line: blank or SQL
        flush_run()
        current.body.append(raw_line)

    if in_block:
        raise ParseError("unterminated /*@ ... */ block")
    flush_run()

    blocks: list[RawBlock] = []
    seen: set[str] = set()
    for acc in accums:
        directives: dict[str, Any] = {}
        for fragment in acc.fragments:
            directives = deep_merge(directives, _load_fragment(fragment))
        if acc.name is not None:
            if acc.name in seen:
                raise ParseError(f"duplicate cell name: {acc.name}")
            seen.add(acc.name)
        blocks.append(
            RawBlock(name=acc.name, directives=directives, sql="\n".join(acc.body).strip())
        )
    return blocks


def parse_file(path: str | Path) -> list[RawBlock]:
    """Parse a .qsql file from disk."""
    return parse(Path(path).read_text(encoding="utf-8"))
