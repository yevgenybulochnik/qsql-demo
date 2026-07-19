"""Per-dialect completion vocabulary: keyword and function-name word lists.

Derived once per dialect from sqlglot's tables — already a dependency, so the
lists track sqlglot upgrades for free — topped up with names sqlglot doesn't
carry (notably BigQuery's range family of table-valued functions, which
BigQuery registers on top of ZetaSQL and most grammars omit). duckdb is the
exception: its functions come from its own embedded catalog (``duckdb_functions()``),
authoritative and offline, because sqlglot's parser registry is one pool shared
across dialects and can't attribute a function to a single engine (it would
offer a duckdb cell BigQuery-only names like SAFE_DIVIDE). This is vocabulary
only: completion clients prefix-filter, and everything positional (alias scopes,
FROM/JOIN relation paths) stays in analysis.py.
"""

from __future__ import annotations

import re
from functools import lru_cache

# dialect-independent core, and the whole list when a cell has no sqlglot
# dialect: the clause skeleton every engine shares
CORE_KEYWORDS = [
    "SELECT", "FROM", "WHERE", "GROUP BY", "ORDER BY", "HAVING", "LIMIT", "OFFSET",
    "JOIN", "LEFT JOIN", "RIGHT JOIN", "INNER JOIN", "FULL JOIN", "ON", "USING",
    "AS", "AND", "OR", "NOT", "IN", "IS NULL", "IS NOT NULL", "CASE", "WHEN", "THEN",
    "ELSE", "END", "DISTINCT", "UNION", "UNION ALL", "WITH", "OVER", "PARTITION BY",
]

# valid dialect names sqlglot's tables don't (yet) carry
_EXTRA_FUNCTIONS: dict[str, tuple[str, ...]] = {
    "bigquery": (
        "GAP_FILL",
        "GENERATE_RANGE_ARRAY",
        "RANGE",
        "RANGE_CONTAINS",
        "RANGE_END",
        "RANGE_INTERSECT",
        "RANGE_OVERLAPS",
        "RANGE_SESSIONIZE",
        "RANGE_START",
    ),
}

# plain (possibly spaced) uppercase words — drops sqlglot's operator and
# comment-marker tokenizer entries like "&&", ":=", "/*+" (and duckdb's
# operator rows like "->>"), leaving callable names
_WORDS = re.compile(r"^[A-Z][A-Z_]+(?: [A-Z][A-Z_]+)*$")

# sqlglot's shared registry keys some abstract ``exp.Func`` base classes by a
# name auto-derived from the class (SafeFunc -> SAFE_FUNC); these are machinery,
# never callable SQL, and must not reach any dialect's completions
_INTERNAL_SUFFIX = "_FUNC"


def _dialect_class(dialect: str | None):
    if dialect is None:
        return None
    from sqlglot.dialects.dialect import Dialect

    return Dialect.get(dialect)


@lru_cache(maxsize=None)
def keywords(dialect: str | None) -> tuple[str, ...]:
    """Keyword labels for a sqlglot dialect name (CORE_KEYWORDS when the
    dialect is unknown), alphabetical."""
    d = _dialect_class(dialect)
    if d is None:
        return tuple(CORE_KEYWORDS)
    pool = {k for k in d.tokenizer_class.KEYWORDS if _WORDS.match(k)}
    pool.update(CORE_KEYWORDS)
    return tuple(sorted(pool))


@lru_cache(maxsize=1)
def _duckdb_catalog_functions() -> frozenset[str]:
    """duckdb's own function names from its embedded catalog. Empty (→ sqlglot
    fallback) if the catalog can't be read, so completions never break."""
    try:
        import duckdb

        con = duckdb.connect()
        try:
            rows = con.execute(
                "SELECT DISTINCT upper(function_name) FROM duckdb_functions()"
            ).fetchall()
        finally:
            con.close()
    except Exception:
        return frozenset()
    return frozenset(r[0] for r in rows if _WORDS.match(r[0]))


def _base_functions(dialect: str | None) -> set[str] | None:
    """Raw function pool for a dialect (None when the dialect is unknown):
    duckdb's own catalog, else sqlglot's registry minus its internal wrappers."""
    d = _dialect_class(dialect)
    if d is None:
        return None
    if dialect == "duckdb":
        catalog = _duckdb_catalog_functions()
        if catalog:
            return set(catalog)  # else fall through to sqlglot
    return {
        f
        for f in d.parser_class.FUNCTIONS
        if _WORDS.match(f) and not f.endswith(_INTERNAL_SUFFIX)
    }


@lru_cache(maxsize=None)
def functions(dialect: str | None) -> tuple[str, ...]:
    """Function-name labels for a sqlglot dialect name, alphabetical; names
    already offered as keywords are dropped. Empty when the dialect is
    unknown — there is no engine-independent function list worth offering."""
    pool = _base_functions(dialect)
    if pool is None:
        return ()
    pool.update(_EXTRA_FUNCTIONS.get(dialect, ()))
    return tuple(sorted(pool - set(keywords(dialect))))
