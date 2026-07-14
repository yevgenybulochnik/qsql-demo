# Plan: engine-context groups — same-engine refs stay in-engine

## Context

Today every `ref()` resolves through the producer's sink on the DuckDB conduit, and the
guardrail forces any cell with refs to run on DuckDB. Consequences: two BigQuery cells
cannot reference each other at all — the parent must be extracted to parquet and the
child demoted to a local DuckDB join. For same-warehouse dependencies that is backwards:
the intermediate downloads anyway and the join runs on the laptop instead of next to
the data.

**The change:** cells partition into *contexts* by (engine, connection target). Within a
context, `ref()` resolves to an in-engine temp table in that engine's own dialect and the
dependency executes server-side. Across contexts, the DuckDB conduit keeps its role
unchanged. **Landing stays universal by default**: every cell still materializes through
its sink (parquet by default), so previews, watch semantics, downstream cross-context
refs, and VisiData (`V`) work exactly as today. The temp table and the landed artifact
are two consumers of a single execution:

1. `CREATE TEMP TABLE <cell> AS (<sql>)` — runs once, server-side, in the cell's context
   session.
2. Same-context children reference `<cell>` directly (bare identifier — dialect-neutral).
3. The landing step reads `SELECT * FROM <cell>` from the temp (extract → conduit →
   sink) instead of re-running the query.

This is deliberately the temp-table/session model, *not* dbt-style CTE inlining:
inlining would re-execute the parent per consumer (and once more for landing), and it
dissolves the cell as the unit the plugin run-chain wraps (timing, retries, error
attribution stay per-cell).

## Design

- **Context key** — `Executor.context_key(config) -> str`, e.g. `duckdb:<target-db>`,
  `sqlite:./legacy.db`, `bigquery:my-proj`. Executor-owned: executors already own input
  interpretation. Cells with equal keys form a group.
- **Context sessions** — `RunSession` grows a per-key connection/session cache (the
  quicksql backend-cache pattern). DuckDB's context *is* the existing conduit. SQLite: one
  shared `sqlite3` connection per db path. BigQuery: a session (`session_id` on jobs) so
  temp tables persist across statements.
- **Executor contract split** — `materialize(cell, ctx)` creates the temp table in the
  cell's session; `extract(cell, ctx) -> view` exposes the temp's rows on the conduit for
  landing (today's `execute` ≈ materialize+extract fused). Cells nobody refs
  same-context may keep the cheaper lazy path (DuckDB TEMP VIEW instead of TABLE) — the
  compiler knows each cell's consumers and passes the hint.
- **`ref()` becomes context-aware** — the render capability grows producer context keys
  (alongside producer sinks). Same context → bare temp-table identifier; different
  context → today's sink read-back expression.
- **Guardrail relaxes, not disappears** — *cross-context* refs and `source()` still
  require the consumer to run on DuckDB. Same-context refs are legal on any engine.
- **Selection/watch** — temp tables are session-scoped, and session persistence (watch/
  TUI reuse one `RunSession`) means unchanged upstream temps survive reruns. On a fresh
  session, a selected cell's same-context upstream closure must re-materialize first:
  the session tracks which temps exist and the runner expands the exact-set selection
  through missing same-context upstreams.
- **Observability** — `qsql list`/`explain` show each cell's context key; the run chain
  is unchanged (cells stay the execution unit).

## Phases (each ends green; test-first, conventional commits)

**Phase 0 — plumbing, no behavior change.** `context_key` on executors; compiler
annotates cells with it; producer context keys reach the render capability; `list`/
`explain` display them. All refs still resolve via sinks.

**Phase 1 — DuckDB groups (the mechanism in miniature).** DuckDB cells already share
the conduit: same-context refs resolve to the upstream's temp materialization instead
of round-tripping parquet; reffed cells materialize as TEMP TABLE, unreffed keep TEMP
VIEW. Landing unchanged. Tests: same-conduit ref skips the parquet read-back (assert
rendered SQL), results identical, cross-context ref (duckdb-file input vs :memory:)
still uses the sink path.

**Phase 2 — SQLite contexts.** First real second-connection type: shared connection per
db path in `RunSession`, `CREATE TEMP TABLE` per cell, extraction from the temp. Two
sqlite cells may now ref each other (guardrail update + tests); a duckdb cell reading a
sqlite cell's landed parquet stays as-is. Offline tests throughout.

**Phase 3 — BigQuery sessions.** Session-scoped temp tables; child jobs run with the
session id; extraction reads the temp once for landing. Fake-client tests offline
(session id plumbed, statements sequenced, single execution per cell asserted);
real-credential test gated behind the existing `bigquery` marker. The parent's parquet
lands exactly as today — inspectable in the TUI and VisiData.

**Phase 4 (optional, opt-in) — ephemeral output.** `@output: {type: none}` for parents
whose download isn't wanted (huge intermediates): skips landing, previews via an
in-engine `LIMIT` query, selection always expands through ephemeral upstreams. Deferred
until someone actually needs it; everything above works without it.

## Risks

- Session lifetime is now semantics, not just a perf cache: a dropped BigQuery session
  invalidates temps mid-watch — the runner must detect and re-materialize (session
  tracks its temp set; treat unknown-temp errors as cache misses, replay closure).
- Temp materialization costs storage/compute in the warehouse (BigQuery bills the
  CREATE TEMP TABLE write); document that same-context refs trade a small write for
  avoided downloads and local joins.
- The executor contract split touches all three executors; phase 0/1 keep the fused
  path working so each engine migrates independently.

## Verification

Full suite green per phase; `stress/` rerun for the DuckDB phase (temp-table refs vs
parquet round-trip timings); a two-cell BigQuery notebook against real credentials as
the manual gate for phase 3 — parent visible in VisiData via `V`, child never
downloads the parent.
