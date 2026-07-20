# sources

Reading raw local files with `source()` — no database, no docker. A small
bookshop's analytics assembled from four files in four formats, all pulled in
through `{{ source(...) }}` and joined on DuckDB.

## The files

| File | Format | Reader | Read via |
| --- | --- | --- | --- |
| `seeds/books.csv` | CSV | `read_csv_auto` | **named** source `books` |
| `seeds/orders.ndjson` | newline-delimited JSON | `read_json_auto` | **raw path** |
| `seeds/regions.txt` | pipe-delimited text | `read_csv_auto` (with `sep`) | **named** source `regions` + reader options |
| `seeds/inventory.parquet` | Parquet | `read_parquet` | **raw path** |

Two ways to name a source, both shown:

- **Named** — declared in the notebook header's `sources:` map, referenced by
  name. `regions` carries reader options (`type: csv`, `sep: "|"`) so a
  pipe-delimited `.txt` reads as CSV.
- **Raw path** — `source('seeds/orders.ndjson')` with no map entry; the reader
  is inferred from the file extension.

Paths resolve relative to the notebook, so the demo runs from any working
directory. All data is synthetic and deterministic.

## Quickstart

Nothing to stand up — just run it:

```console
$ uv run quicksql run demo/sources/sources.qsql
$ uv run quicksql tui demo/sources/sources.qsql
```

Outputs land next to the notebook: `data/*.parquet` and `warehouse.db` (both
gitignored, regenerated on every run).

## The notebook, cell by cell

| Cell | Shows off |
| --- | --- |
| `books` | a **named** CSV source from the header's `sources:` map |
| `orders` | a **raw-path** NDJSON source — reader inferred from `.ndjson` |
| `regions` | a named source with **reader options** (`type` + `sep`): a pipe-delimited `.txt` read as CSV |
| `inventory` | a **raw-path** Parquet source (`read_parquet`) |
| `order_lines` | `source()` and `ref()` **composing** — JSON orders enriched with CSV catalog fields |
| `sales_by_segment` | rolls revenue up by channel segment, landed in a **DuckDB sink** instead of parquet |
| `restock` | `@autorun: false` on-demand cell; `{{ var('restock_threshold') }}` (try `--set vars.restock_threshold=20`) |

`quicksql run` executes every cell regardless of `autorun` (that flag only
gates watch/TUI cascades); in the TUI, press `r` on `restock` to run it, or use
`quicksql run … --select restock` to run just it plus its upstreams.

## Regenerating the Parquet seed

`seeds/inventory.parquet` is a binary seed — edit the generator, not the file:

```console
$ uv run python demo/sources/tools/gen_inventory.py
```

It's deterministic (fixed rows, sorted on write), so a regenerated seed is a
no-op in `git diff`.
