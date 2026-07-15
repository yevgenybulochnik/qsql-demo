# qsql-demo

qsql is a CLI "notebook for SQL": one `.qsql`/`.sql` file of valid SQL, split into named
cells by `-- @cell <name>`. Config lives in `@`-comment YAML directives — line form
`-- @key: value`, block form `/*@ ... */` — with a global header (everything before the
first `@cell`) inherited by every cell.

## Core concepts

- **Cell shape = input → engine → output.** Cells form a DAG from `{{ ref('cell') }}` +
  `@depends_on`, topo-sorted with cycle detection (`graph.py`).
- **Sinks are the cross-cell interchange.** Each cell lands via its sink (default
  `data/<cell>.parquet`); `Sink.ref_expr()` tells downstream cells how to read it back
  (read_parquet, ATTACHed duckdb/postgres table, ...).
- **Engine contexts.** Cells partition by (engine, connection target) via
  `Executor.context_key`. Same-context `ref()` resolves to a bare temp-table name in
  the engine's own dialect (session-scoped: duckdb conduit / shared sqlite connection /
  BigQuery session), executing the dependency next to the data; the cell still lands
  via its sink from that temp — one execution, two consumers.
- **DuckDB is the cross-context conduit.** Cells using *cross-context*
  `ref()`/`source()`/`@extensions` must run on duckdb (compile-time guardrail); other
  engines extract to Polars/Arrow and DuckDB lands it in any sink.
- **Everything is a plugin.** `@plugin` / `@executor` / `@source_reader` / `@sink`
  decorators register into registries (`registry.py`). A `Plugin` bundles a pydantic
  `Config` (its fields become directives; validators run on merged config; merge
  strategy rides on fields via `qfield`) with behavior hooks (lower `priority` =
  outermore): `run(cell, ctx, inner)` wraps execution (or the simpler
  `before_execute`/`after_execute`); `render_context(rctx)` *contributes* Jinja
  globals under a collision guard (the builtin ref/source/var/env globals are plugin
  contributions; `rctx` is the RenderContext capability: add_edge/producer_expr/
  require_extensions); `after_render(rctx, sql)` transforms SQL; first-result
  decision hooks `resolve_engine`/`resolve_sink`/`should_rerun` and aggregation hooks
  `collect_edges`/`sink_config` let directives own their behavior (core defaults:
  duckdb/parquet/rerun); `after_compile` may raise to reject a compile;
  `before_run`/`after_run` are contained notifications.
  `qsql explain` prints the effective chain/hook order. `config.build_models`
  composes all plugin Configs into GlobalConfig/CellConfig via `create_model`.
- **Config resolution:** global → cell → run overrides (`--set k.v=x`, `QSQL_K__V=x`),
  per-field merge strategy (OVERRIDE / DEEP / EXTEND). Config values are literal; Jinja
  applies to SQL bodies only.
- **Watch/TUI are reflect-only.** The file is edited elsewhere; change detection hashes
  SQL bodies only, so config-only edits don't trigger reruns (known limitation).
  Third-party plugins load via `--plugins mod.or.path.py` or a `qsqlrc.py` next to the file.

## Commands

- `uv run pytest` — markers `network` / `bigquery` / `postgres` are deselected by default.
  `docker compose up -d --wait` stands up Postgres (databases: `qsql` for stress/manual
  data, `qsql_test` for pytest), then `uv run --extra postgres pytest -m postgres` runs
  the integration tests; they skip when the server is down. Override the DSN with
  `QSQL_TEST_PG_DSN`. Everything except the cloud-gated tests:
  `uv run --extra postgres pytest -m "not (network or bigquery)"` — an explicit `-m`
  overrides the default deselection.
- `uv run qsql` (bare = init) | `init` | `run` | `watch` | `tui` | `list` | `show <cell>` |
  `compile` — default file `base.qsql`; `--set key.path=value` repeatable. `qsql tui`
  with a missing file opens a notebook picker: existing .qsql/.qsql.sql files plus
  starter templates (builtin `base` + user templates from `~/.qsql/templates/*.qsql`);
  `o` in the TUI switches notebooks.

## Architecture map (`src/qsql_demo/`)

- `parser.py` — text → RawBlocks (directive YAML + SQL body + body hash)
- `registry.py` — registries + decorators; field→plugin map with collision guard
- `plugins/` — `base.py` (Plugin, qfield), `builtin.py` (the directive vocabulary),
  `emit_sql.py` (behavior-plugin demonstrator)
- `config.py` — model composition, scope checks, layer merging, engine/sink resolution
- `overrides.py` — `--set` / `QSQL_*` parsing
- `render.py` — Jinja on SQL bodies; ref/source/var/env; records edges + extensions
- `sources.py` — file reader registry (csv/parquet/json/excel)
- `graph.py` — topo sort, cycle detection, downstream sets
- `compiler.py` — parse → config → render → graph ⇒ `Project`
- `runner.py` — topo run; per-cell executor+sink; plugin run-chain; RunSession holds
  the conduit connection + extension cache across watch/TUI reruns
- `executors/`, `sinks/` — strategy leaves (duckdb/sqlite/postgres/bigquery;
  parquet/duckdb/postgres)
- `scaffold.py`, `cli.py`, `watcher.py`, `sheet.py` + `tui.py` — CLI, watch loop, TUI

## Development methodology — red-green-refactor

Write the failing pytest first and watch it fail **for the expected reason**; write the
minimal code to green; refactor while green. Tests mirror `src/` layout
(`tests/test_<module>.py`); shared fixtures in `tests/conftest.py` (registry
snapshot/restore is autouse — tests may register scratch plugins freely).

## Conventional Commits

`type(scope): summary` — scope = module (`parser`, `config`, `render`, `graph`, `sink`,
`executor`, `runner`, `cli`, `tui`, `watcher`); types in history: `feat`, `fix`, `test`,
`refactor`, `build`, `docs`, `chore`. Behavior-sized commits; `test(...)` red commit then
`feat/fix(...)` green commit when practical.
