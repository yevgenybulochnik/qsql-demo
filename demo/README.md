# demo

Self-contained subdirectories, each showcasing a slice of quicksql. Every demo
brings its own backends (docker compose) and seed data; nothing here is needed
by the test suite (the repo-root `docker-compose.yml` is the pytest stack).

| directory | what it shows |
|---|---|
| [`kitchen-sink/`](kitchen-sink/) | the works — Postgres claims warehouse (incl. a 250-column table), BigQuery-emulator drug compendia, cross-engine DuckDB joins, vars, DuckDB sink, autorun |

Demo stacks run on offset host ports (kitchen-sink: Postgres 5433, bigquery
emulator 9051) so they coexist with the root pytest stack on 5432/9050 —
no need to stop one to run the other.
