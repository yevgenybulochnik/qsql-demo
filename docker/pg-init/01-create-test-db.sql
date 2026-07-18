-- Runs once, on first boot of an empty volume: pytest gets its own database,
-- isolated from stress/manual data in `quicksql`.
CREATE DATABASE quicksql_test OWNER quicksql;
