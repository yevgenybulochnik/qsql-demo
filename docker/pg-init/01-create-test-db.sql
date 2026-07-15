-- Runs once, on first boot of an empty volume: pytest gets its own database,
-- isolated from stress/manual data in `qsql`.
CREATE DATABASE qsql_test OWNER qsql;
