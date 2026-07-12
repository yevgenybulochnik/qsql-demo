"""The starter ``base.sql`` that ``qsql init`` writes."""

from __future__ import annotations

from pathlib import Path

BASE_SQL = """\
-- A qsql pipeline: named SQL cells with config in @-comments.
-- Run it with `qsql run`, explore it with `qsql tui`.

-- @engine: duckdb
-- @output: { type: parquet, dir: data/ }
-- @autorun: true

-- @cell users
SELECT * FROM (VALUES
    (1, 'Ana',  true),
    (2, 'Ben',  false),
    (3, 'Cara', true)
) AS t(id, name, active);

-- @cell active_users
-- @depends_on: [users]
SELECT id, name
FROM {{ ref('users') }}
WHERE active
ORDER BY id;
"""


def write_scaffold(path: str | Path) -> Path:
    """Write the starter file, refusing to overwrite an existing one."""
    target = Path(path)
    if target.exists():
        raise FileExistsError(str(target))
    target.write_text(BASE_SQL, encoding="utf-8")
    return target
