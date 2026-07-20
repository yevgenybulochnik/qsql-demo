"""Generate ``seeds/inventory.parquet`` deterministically.

This is a binary seed — edit this generator, not the parquet. Regenerate with:

    uv run python demo/sources/tools/gen_inventory.py

Rerunning must produce a byte-identical file (fixed rows, sorted on COPY, no
randomness), so a regenerated seed shows up as a no-op in ``git diff``.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

# (book_id, warehouse, on_hand) — two warehouses per book_id in books.csv.
# Totals are tuned so a few titles fall under the notebook's restock_threshold.
ROWS = [
    (1, "east", 30), (1, "west", 25),   # 55
    (2, "east", 5),  (2, "west", 8),    # 13  (Dune — sells fast, runs low)
    (3, "east", 40), (3, "west", 35),   # 75
    (4, "east", 12), (4, "west", 10),   # 22  (low)
    (5, "east", 50), (5, "west", 60),   # 110
    (6, "east", 18), (6, "west", 15),   # 33  (low)
    (7, "east", 9),  (7, "west", 6),    # 15  (low)
    (8, "east", 22), (8, "west", 20),   # 42
]


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "seeds" / "inventory.parquet"
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE inventory (book_id INTEGER, warehouse VARCHAR, on_hand INTEGER)"
    )
    con.executemany("INSERT INTO inventory VALUES (?, ?, ?)", ROWS)
    con.execute(
        f"COPY (SELECT * FROM inventory ORDER BY book_id, warehouse) "
        f"TO '{out}' (FORMAT parquet)"
    )
    print(f"wrote {out} ({len(ROWS)} rows)")


if __name__ == "__main__":
    main()
