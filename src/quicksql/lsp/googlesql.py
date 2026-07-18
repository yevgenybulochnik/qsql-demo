"""Optional GoogleSQL (ex-ZetaSQL) bridge: reference-grade BigQuery syntax checks.

sqlglot hard-rejects six valid pipe-syntax operators (SET/DROP/RENAME/CALL/
WINDOW/ASSERT). The googlesql `execute_query` binary implements the actual
BigQuery grammar; when it is discoverable, bigquery cells' syntax diagnostics
route through it (parse mode only — no catalog, so no table resolution), and
the sqlglot path stands otherwise.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

# not QUICKSQL_*: overrides.parse_env sweeps that prefix into config overrides
ENV_VAR = "QSQL_EXECUTE_QUERY"

# the leading status token (INVALID_ARGUMENT etc.) is noise for an editor
_ERROR = re.compile(r"^ERROR: (?:[A-Z_]+: )?(.*) \[at (\d+):(\d+)\]", re.MULTILINE)


def find_execute_query() -> str | None:
    """Explicit path from ``QSQL_EXECUTE_QUERY``, else ``execute_query`` on PATH."""
    return os.environ.get(ENV_VAR) or shutil.which("execute_query")


def parse_errors(
    binary: str, sql: str, timeout: float = 5.0
) -> list[tuple[int, int, str]] | None:
    """Syntax errors from ``--mode=parse`` as (line, col, message), 1-indexed
    within ``sql``; ``[]`` on a clean parse; ``None`` when the tool itself
    failed (missing, crashed, timed out) so the caller can fall back.

    The tool exits 0 even on syntax errors — they arrive on stdout as
    ``ERROR: <message> [at <line>:<col>]``, line numbers global across a
    multi-statement input."""
    try:
        proc = subprocess.run(
            [binary, "--mode=parse", "-"],
            input=sql,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return [
        (int(m.group(2)), int(m.group(3)), m.group(1)) for m in _ERROR.finditer(proc.stdout)
    ]
