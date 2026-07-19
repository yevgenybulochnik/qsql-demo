-- Runs once, on first boot of an empty volume: synthetic healthcare claims
-- for smoke-testing against Postgres. Seed it with
-- demo/kitchen-sink/pg-init/10-claims-core.sql (see that file's header for
-- the command).
CREATE DATABASE quicksql_claims OWNER quicksql;
