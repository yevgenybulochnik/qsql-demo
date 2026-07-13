# qsql-demo

A CLI "notebook for SQL": one `.qsql`/`.sql` file of valid SQL, split into named cells by
`-- @cell <name>` markers. All configuration lives in `@`-marked comment directives parsed as
YAML — line form `-- @key: value` and block form `/*@ ... */`. Everything before the first
`@cell` is a global header that every cell inherits and may override.

## Core concepts

- **Cell shape: input → engine → output.** Each cell runs on an engine (`duckdb` default,
  `sqlite`, `bigquery`) and lands its result through a sink (default: parquet at
  `data/<cell>.parquet`). Cells form a DAG from implicit `{{ ref('name') }}` edges plus explicit
  `@depends_on`; runs walk it in topo order, cycles are compile errors.
- **Sinks are the cross-cell interchange.** A sink both writes a cell's output and exposes
  `ref_expr(name, config)` — the DuckDB expression a downstream cell uses to read it back
  (`read_parquet(...)`, an ATTACHed table, …). This is what lets cells on different engines and
  destinations compose.
- **DuckDB is the universal conduit.** Any cell that uses `ref()`/`source()`/`@depends_on` must
  run on DuckDB (compile-time guardrail). Non-DuckDB engines extract to Polars; DuckDB writes
  that into whatever sink the cell chose.
- **Everything is a plugin.** `@plugin`, `@executor`, `@source_reader`, and `@sink` decorators
  (`registry.py`) self-register at import time. A `Plugin` (`plugins/base.py`) bundles a pydantic
  `Config` — its fields become config directives, with real validators — plus an optional `run`
  hook that wraps cell execution in a priority-ordered decorator chain (lower = outermore).
  `config.build_models()` composes the registered Configs into `GlobalConfig`/`CellConfig` via
  multiple-inheritance `create_model()`. Executors/sinks/source readers stay selected strategies,
  not decorators; compile-time behavior (render globals, edges, engine/sink resolution) stays
  core. See `docs/plugin-authoring.md`.
- **Config resolution** merges global → cell → run overrides (`--set k.v=x`, `QSQL_*` env), with
  a per-directive merge strategy (override / deep-dict / list-extend). Directive values are
  literal YAML; Jinja applies to SQL bodies only.
- **Watch and TUI are reflect-only.** You edit the file in your own editor; a watchfiles loop
  recompiles on save and re-runs changed cells + downstream (autorun cells only). Change
  detection hashes the raw SQL body only — editing a cell's *directives* does not trigger a
  rebuild (known limitation). Watches are placed on the file's parent directory, never the file
  itself: editors that save via rename would kill an inode-level watch.

## Commands

- `uv run pytest` — full suite. `network`/`bigquery`/`postgres` marked tests are deselected by
  default via `addopts`; opt in with `-m network` etc.
- `uv run qsql init|run|watch|tui|list|show|compile [file]` — default file is `base.sql`.
- `uv run qsql run --select 'cell'` (`+cell` = with upstream, `cell+` = with downstream);
  `--set key.path=value` for run-time config overrides.

## Architecture (src/qsql_demo/)

Pipeline: `parser` → `config` → `render` → `graph` → `compiler` (produces `Project`) → `runner`.

- `parser.py` — text → `[RawBlock]`: header + cells, directives as one YAML dict, body hash
- `registry.py` / `plugins/base.py` / `plugins/builtin.py` — registries + Plugin base + builtins
- `config.py` — plugin-Config composition, merge/override resolution, engine + sink resolution
- `render.py` — Jinja over SQL bodies; `ref()`/`source()`/`var()`/`env()` globals
- `graph.py` — topo sort, cycle detection, `downstream()` (the watch rebuild set)
- `runner.py` — topo execution over one conduit DuckDB connection; wraps each cell in the plugin
  decorator chain, ATTACHes upstream sinks
- `executors/`, `sinks/`, `sources.py` — engine, output, and file-reader plugins
- `watcher.py` — pure rebuild planning (`changed_cells`/`plan_rebuild`) + the watchfiles loop
- `tui.py` — Textual master-detail app; `sheet.py` — pure VisiData-style ops over a Polars frame
- `cli.py` — typer entry points

## Development: red-green-refactor

Build strictly test-first, one behavior at a time:

1. **Red** — write the pytest test for the next behavior; run it and watch it fail *for the
   expected reason*.
2. **Green** — write the minimal code to pass; confirm the whole suite is green.
3. **Refactor** — clean up with the tests as the safety net; stay green.
4. **Commit at each green** (see below). Never commit red.

`tests/` mirrors `src/qsql_demo/` (`test_parser.py`, `test_config.py`, …); shared fixtures live
in `tests/conftest.py` (notably `project_dir`). Keep pure logic (rebuild planning, sheet ops)
unit-tested directly; drive the TUI through Textual's `run_test()` pilot.

## Commits: Conventional Commits

`type(scope): summary` — scope is the module touched: `parser`, `config`, `render`, `graph`,
`registry`, `runner`, `sink`, `executor`, `sources`, `watcher`, `tui`, `cli`, `models`.
Types in use: `feat`, `fix`, `test`, `refactor`, `build` (deps/pyproject), `docs`, `chore`.
Commits are small and behavior-sized — ideally a `test(scope): …` red commit followed by the
`feat`/`fix(scope): …` commit that turns it green.
