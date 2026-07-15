# qsql — a notebook for SQL, in one file

A single `.sql` file is the notebook: valid SQL split into named **cells** by comment
directives. Config is YAML inside `@`-comments; SQL bodies are Jinja-templated. Cells
form a dependency DAG, run on pluggable **engines** (DuckDB, SQLite, Postgres, BigQuery), and land
through pluggable **sinks** (parquet files, DuckDB tables, Postgres tables) that also
define how downstream cells read them back.

![qsql TUI: Postgres cells, a cross-engine DuckDB cell, an nvim edit triggering an autorun rerun, and the VisiData deep-dive](demo/qsql-demo.gif)

*Two cells run in Postgres, next to the data; the DuckDB cell joins their results. Editing
the SQL in nvim reruns just the changed cell and its downstream — `top_customers` is
untouched while `shipped_by_tier` and `tier_share` go 3 rows → 2. `V` opens the landed
parquet in VisiData. Recorded by [`demo/demo.tape`](demo/README.md).*

```sql
-- @engine: duckdb
-- @output: { type: parquet, dir: data/ }

-- @cell users
SELECT * FROM {{ source('seeds/users.csv') }};

-- @cell legacy_orders
/*@ input: { sqlite: legacy.db } */
SELECT * FROM orders;

-- @cell report
-- @output: { type: duckdb, path: warehouse.db }
SELECT u.name, count(*) AS orders
FROM {{ ref('users') }} u JOIN {{ ref('legacy_orders') }} o USING (user_id)
GROUP BY 1;
```

## Quick start

```console
$ uv sync
$ uv run qsql            # scaffolds base.qsql
$ uv run qsql run        # runs every cell, lands data/<cell>.parquet
$ uv run qsql list       # cells, topo order, engine -> sink, autorun
$ uv run qsql show report        # rendered SQL for one cell
$ uv run qsql watch      # rerun changed cells + dependents on save
$ uv run qsql tui        # VisiData-style TUI (j/k, Enter dive, F freq, V real vd)
$ uv run qsql run --set output.type=duckdb --set vars.active_only=false
```

## How it works

- **Cells + DAG** — `{{ ref('cell') }}` renders to *how the producer's sink is read
  back* and records a dependency edge. Topo order runs upstreams first.
- **DuckDB is the conduit** — cells that `ref()`/`source()` run on DuckDB; other
  engines extract their result and DuckDB writes it to the chosen sink.
- **Everything is a plugin** — directives, engines, file readers, and sinks are all
  registered via decorators. A plugin bundles config fields (with pydantic validation)
  and can decorate cell execution (retries, caching, SQL emission...). See
  [docs/plugin-authoring.md](docs/plugin-authoring.md).
- **Run-time overrides** — `--set key.path=value` and `QSQL_KEY__PATH=value` layer on
  top of global → cell config.

Optional extras: `uv sync --extra bigquery` (BigQuery engine),
`--extra postgres` (Postgres engine, via psycopg), `--extra visidata` (the TUI's `V`
deep-dive). The Postgres *sink* needs no Python driver — DuckDB's `postgres` extension
handles it (`output: { type: postgres, dsn: "$PG_DSN", table: analytics.report }`);
the Postgres *engine* runs cells next to the data (`input: { postgres: { dsn: "$PG_DSN" } }`),
with same-DSN cells sharing a session so `ref()` stays in-engine.

## Development

Built test-first (red-green-refactor) with pytest; commits follow Conventional Commits.

```console
$ uv run pytest          # network/bigquery/postgres-gated tests are skipped by default
$ docker compose up -d --wait                 # local Postgres (qsql + qsql_test databases)
$ uv run --extra postgres pytest -m postgres  # postgres tests only
$ uv run --extra postgres pytest -m "not (network or bigquery)"   # everything but the cloud
```

An explicit `-m` overrides the default deselection in `pyproject.toml`. Postgres tests
skip (never fail) when the server is down, so the last line is safe without Docker.
