"""The starter file `qsql init` writes: runs offline, demonstrates the basics."""

from __future__ import annotations

from pathlib import Path

BASE_SQL = """\
-- qsql starter — one SQL file, cells split by `-- @cell`, config in @-comments.
-- Run it:      qsql run
-- Inspect it:  qsql list / qsql show <cell> / qsql tui
-- Watch it:    qsql watch   (re-runs changed cells + their dependents on save)

-- @engine: duckdb
-- @output: { type: parquet, dir: data/ }
-- @autorun: true

/*@
vars: { active_only: true }
*/

-- @cell users
SELECT * FROM (VALUES
    (1, 'ada', true),
    (2, 'bob', false),
    (3, 'cyd', true)
) AS t(user_id, name, active);

-- @cell events
SELECT (range % 3 + 1)::INT AS user_id,
       'event_' || range::VARCHAR AS event
FROM range(10);

-- @cell active_user_events
-- @depends_on: [users]
SELECT u.name, e.event
FROM {{ ref('users') }} u
JOIN {{ ref('events') }} e USING (user_id)
{% if var('active_only') %}WHERE u.active{% endif %};

-- Things to try:
--   * point a cell at another engine:   /*@ input: { sqlite: legacy.db } */
--   * land a cell somewhere else:       -- @output: { type: duckdb, path: warehouse.db }
--   * read files:                       SELECT * FROM {{ source('seeds/users.csv') }}
--   * override at run time:             qsql run --set output.type=duckdb
"""


def write_scaffold(path: Path | str) -> Path:
    """Write the starter file; refuses to overwrite an existing one."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(BASE_SQL)
    return path
