# kitchen sink

Every major quicksql feature in one notebook: Postgres cells, a BigQuery cell,
DuckDB cross-engine joins, vars, a non-default sink, and an ultra-wide table
for the TUI catalog to chew on.

## Topology

| Backend | Holds | Seeded by |
| --- | --- | --- |
| Postgres (`quicksql_claims`) | transactional claims — `claims.eligibility`, `claims.medical_claims`, `claims.pharmacy_claims`, and the **250-column** `claims.claims_837_wide` flattened 837-style extract | `pg-init/*.sql` via `/docker-entrypoint-initdb.d` on first boot of an empty volume |
| BigQuery emulator (project `quicksql-test`) | drug compendia reference data — `compendia.ndc_directory`, `compendia.therapeutic_classes`, `compendia.drug_pricing` | `bq-seed/compendia.yaml` via goccy's `--data-from-yaml` on every start (state is in-memory) |

The compendia NDCs match the pharmacy-claims seed exactly, so the cross-engine
join in `class_spend` hits on every row. All data is synthetic and
deterministic (`generate_series`, no `random()`); nothing is PHI.

## Quickstart

The stack uses the **same ports (5432, 9050) as the repo-root compose** — stop
that one first (`docker compose down` at the repo root).

```console
$ docker compose -f demo/kitchen-sink/docker-compose.yml up -d --wait
$ uv run --extra postgres --extra bigquery quicksql run demo/kitchen-sink/kitchen-sink.qsql
$ uv run --extra postgres --extra bigquery quicksql tui demo/kitchen-sink/kitchen-sink.qsql
```

Outputs land next to the notebook: `data/*.parquet` and `warehouse.db` (both
gitignored, regenerated on every run).

## The notebook, cell by cell

| Cell | Engine | Shows off |
| --- | --- | --- |
| `enrolled_members` | postgres | plain cell inheriting the global `input` |
| `wide_claim_profile` | postgres | querying the 250-column wide table (browse it with `S` in the TUI — every column has a COMMENT-sourced description) |
| `rx_fills` | postgres | pharmacy spend by NDC |
| `drug_reference` | bigquery | per-cell `input` override pointing at the emulator; latest-price-per-NDC join |
| `class_spend` | duckdb | cross-engine `ref()` join (Postgres × BigQuery) landed in a DuckDB sink (`warehouse.db`) instead of parquet |
| `pmpm` | duckdb | reading a DuckDB sink back via `ref()`; `{{ var('months') }}` (try `--set vars.months=12`) |
| `scratch_notes` | duckdb | `@autorun: false` — skipped by watch/TUI cascades, run on demand |

## Regenerating the wide table

`pg-init/20-claims-wide.sql` is generated — edit
[`tools/gen_wide_claims.py`](tools/gen_wide_claims.py), not the SQL:

```console
$ uv run python demo/kitchen-sink/tools/gen_wide_claims.py > demo/kitchen-sink/pg-init/20-claims-wide.sql
```

The generator is deterministic; rerunning it must produce a byte-identical
file. To apply a changed seed, recreate the Postgres volume:
`docker compose -f demo/kitchen-sink/docker-compose.yml down -v && ... up -d --wait`.

The core seed (`pg-init/10-claims-core.sql`) doubles as the manual seed for the
root stack's `quicksql_claims` database (used by the postgres-marked tests):

```console
$ docker compose exec -T postgres psql -U quicksql -d quicksql_claims -q < demo/kitchen-sink/pg-init/10-claims-core.sql
```
