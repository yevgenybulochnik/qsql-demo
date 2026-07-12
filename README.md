# qsql

A notebook-like CLI for SQL. A single `.qsql` file is valid SQL split into **named
cell blocks**, with configuration expressed entirely in `--`/`/* */` comments. Each
cell runs on an engine and lands its result via a sink; cells form a dependency DAG
and can be watched or explored in a VisiData-style TUI.

The config vocabulary is **extensible via plugins** (decorators) and the config
models are assembled at runtime with `pydantic.create_model`.

## Quickstart

```bash
uv sync
uv run qsql            # scaffold a starter base.sql
uv run qsql run        # compile + run, landing data/<cell>.parquet
uv run qsql list       # cells, engine→sink, autorun, deps, topo order
uv run qsql watch      # re-run changed cells (and downstream) on save
uv run qsql tui        # interactive master-detail explorer
```

## The file format

```sql
-- @engine: duckdb
-- @output: { type: parquet, dir: data/ }     # global default sink
-- @autorun: true

/*@
sources:
  regions: { path: ./seeds/regions.csv }      # type inferred from extension
  sales:   { type: excel, path: ./sales.xlsx, sheet: Q1 }
*/

-- @cell users                                # a cell: config in @-comments, then SQL
SELECT * FROM read_csv_auto('users.csv');

-- @cell active_users
-- @depends_on: [users]
SELECT * FROM {{ ref('users') }} WHERE active;
```

- **Directives** are `@`-marked comments — line `-- @key: value` or block `/*@ … */`
  — parsed as YAML into each block's config. Values are literal; only SQL bodies are
  templated (Jinja).
- `-- @cell <name>` opens a cell; everything before the first cell is the global
  header. Plain `--` / `/* */` comments pass through into the SQL body.
- Jinja globals in SQL: `ref('cell')`, `source('name'|path, **opts)`, `var('k')`,
  `env('K')`.

## input → engine → output

Every cell has three pluggable layers:

- **sources** read input files — `csv`, `excel` (DuckDB `excel` ext), `parquet`,
  `json`. Or write a raw reader in a *loader cell* and `ref()` it.
- **engines** run the compute — `duckdb` (primary/conduit), `sqlite` (zero-dep),
  `bigquery` (extra). Choose per cell via `@engine` or infer it from a sole `@input`
  key.
- **sinks** land the result — `parquet` (default), `duckdb` (table in a `.db`),
  `postgres` (via DuckDB's `postgres` ext).

Parquet is the cross-cell interchange: `ref('x')` reads `x` back through its sink, so
a DuckDB cell can join a duckdb-, a bigquery-, and an excel-origin upstream and write
the result to Postgres. Cells that read local outputs must run on DuckDB.

Environment/per-run values come from the override layer: `--set output.dir=out` or
`QSQL_output__dir=out`.

## Extending it

Four decorators register plugins; directives are assembled into the pydantic config
models at runtime:

```python
from qsql_demo.registry import directive, source_reader, executor, sink
from qsql_demo.models import Directive, Scope, Merge

@directive
class Retries(Directive):
    key = "retries"; scope = Scope.BOTH; annotation = int; default = 0
```

See `plugins/builtin.py`, `sources.py`, `executors/`, and `sinks/` for the builtins.

## Development

Built test-first (red-green-refactor). Run the suite:

```bash
uv run pytest                                        # fast, offline
uv run pytest -m "network or postgres or bigquery"   # opt-in gated tests
```
