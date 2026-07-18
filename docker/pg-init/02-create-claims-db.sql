-- Runs once, on first boot of an empty volume: synthetic healthcare claims
-- for smoke-testing against Postgres. Seed it with examples/claims_seed.sql
-- (see that file's header for the commands, including the create-if-missing
-- path for volumes that predate this script).
CREATE DATABASE quicksql_claims OWNER quicksql;
