"""Parse .qsql/.sql text into RawBlocks: a global header plus named cells.

Two directive forms, both marked with ``@`` and parsed as YAML into one dict:

* line  — ``-- @key: value`` (contiguous lines stripped of ``-- @`` and joined)
* block — ``/*@ ... */`` (body taken verbatim as a YAML document)

``-- @cell <name>`` opens a cell; text before the first ``@cell`` is the global
header. Everything that isn't a directive is SQL body; plain ``--`` and
``/* */`` comments pass through untouched.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

from .errors import ParseError
from .models import RawBlock

LINE_DIRECTIVE = re.compile(r"^\s*--\s*@(.*)$")
BLOCK_OPEN = re.compile(r"^\s*/\*@")
CELL_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def body_hash(sql: str) -> str:
    """Content hash of a cell body, insensitive to surrounding whitespace."""
    return hashlib.sha256(sql.strip().encode()).hexdigest()[:16]


def _parse_yaml(text: str, line: int) -> dict[str, Any]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ParseError(f"invalid directive YAML at line {line}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ParseError(f"directive at line {line} must be a YAML mapping, got: {data!r}")
    return data


class _Block:
    def __init__(self, name: str | None, line: int) -> None:
        self.name = name
        self.line = line
        self.directives: dict[str, Any] = {}
        self.sql_lines: list[str] = []

    def finish(self) -> RawBlock:
        return RawBlock(
            name=self.name,
            directives=self.directives,
            sql="\n".join(self.sql_lines).strip("\n"),
            line=self.line,
        )


def parse_text(text: str) -> list[RawBlock]:
    """Split text into the global header block (first, name=None) and cells."""
    lines = text.splitlines()
    blocks: list[_Block] = [_Block(None, 1)]
    seen: set[str] = set()
    group: list[str] = []  # pending contiguous line-directive content
    group_line = 0

    def flush_group() -> None:
        nonlocal group
        if group:
            blocks[-1].directives.update(_parse_yaml("\n".join(group), group_line))
            group = []

    i = 0
    while i < len(lines):
        line = lines[i]
        m = LINE_DIRECTIVE.match(line)
        if m:
            content = m.group(1).strip()
            cell = re.match(r"^cell\b(.*)$", content)
            if cell:
                flush_group()
                name = cell.group(1).strip()
                if not name:
                    raise ParseError(f"@cell without a name at line {i + 1}")
                if not CELL_NAME.match(name):
                    raise ParseError(f"invalid cell name {name!r} at line {i + 1}")
                if name in seen:
                    raise ParseError(f"duplicate cell name {name!r} at line {i + 1}")
                seen.add(name)
                blocks.append(_Block(name, i + 1))
            else:
                if not group:
                    group_line = i + 1
                group.append(content)
            i += 1
            continue
        flush_group()
        if BLOCK_OPEN.match(line):
            start = i
            body = [BLOCK_OPEN.sub("", line, count=1)]
            while "*/" not in body[-1]:
                i += 1
                if i >= len(lines):
                    raise ParseError(f"unterminated /*@ block at line {start + 1}")
                body.append(lines[i])
            body[-1] = body[-1][: body[-1].index("*/")]
            blocks[-1].directives.update(_parse_yaml("\n".join(body), start + 1))
            i += 1
            continue
        blocks[-1].sql_lines.append(line)
        i += 1
    flush_group()
    return [b.finish() for b in blocks]


def parse_file(path: str | Path) -> list[RawBlock]:
    return parse_text(Path(path).read_text())
