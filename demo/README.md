# demo

Self-contained subdirectories, each showcasing a slice of quicksql. Every demo
brings its own backends (docker compose) and seed data; nothing here is needed
by the test suite (the repo-root `docker-compose.yml` is the pytest stack).

| directory | what it shows |
|---|---|
| [`kitchen-sink/`](kitchen-sink/) | the works — Postgres claims warehouse (incl. a 250-column table), BigQuery-emulator drug compendia, cross-engine DuckDB joins, vars, DuckDB sink, autorun |

Heads-up: the demo compose stacks reuse the root stack's ports (5432, 9050),
so stop one before starting the other (`docker compose down` at the repo root,
or `docker compose -f demo/<name>/docker-compose.yml down`).
