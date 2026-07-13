"""Generate the stress database: 200-column tables at 500 and 1M rows."""

import sys
import time
from pathlib import Path

import duckdb

HERE = Path(__file__).parent
N_COLS = 200  # id + 199 generated

cols = ", ".join(
    f"((range * {k + 3}) % {997 + (k % 13)})::INT AS c{k}" for k in range(1, N_COLS)
)

con = duckdb.connect(str(HERE / "stress.db"))
for name, rows in [("wide_small", 500), ("wide_big", 1_000_000)]:
    t0 = time.perf_counter()
    con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT range AS id, {cols} FROM range({rows})")
    n, width = con.execute(
        f"SELECT count(*), (SELECT count(*) FROM pragma_table_info('{name}')) FROM {name}"
    ).fetchone()
    print(f"{name}: {n} rows x {width} cols in {time.perf_counter() - t0:.1f}s", flush=True)
con.close()
print("db size:", (HERE / "stress.db").stat().st_size // 1_000_000, "MB")
