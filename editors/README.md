# Editor integration

quicksql ships a language server (`quicksql lsp`, stdio) that gives per-cell **linting**
and **column completion**, engine-aware — reusing the compiler for diagnostics and
the catalog for live/local schema introspection.

## Install

The server lives behind the `lsp` extra (pygls + sqlglot):

```sh
uv tool install 'quicksql[lsp]'      # or: pipx install 'quicksql[lsp]'
# in this repo, for development:
uv run --extra lsp quicksql lsp           # runs the server on stdio
```

## VS Code

`vscode/` is a thin client extension: it declares the `qsql` language (with a
TextMate grammar layering cell/directive/Jinja scopes over the built-in SQL
grammar) and spawns `quicksql lsp` for qsql documents. Build with
`npm install && npm run package`, install the resulting `.vsix` — see
`vscode/README.md` for details, including the Remote-SSH note.

## Neovim

`nvim/qsql.lua` is a self-contained client using the built-in `vim.lsp` (no
plugins required). Load it directly:

```vim
:luafile /path/to/quicksql/editors/nvim/qsql.lua
```

or drop it on your `runtimepath` as `lua/qsql.lua` and `require("qsql")`.

It registers `*.qsql` / `*.qsql.sql` as the `qsql` filetype (borrowing SQL syntax
highlighting), then starts `quicksql lsp` for each buffer, rooted at the nearest
`quicksqlrc.py` / `base.qsql`.

- **Diagnostics** publish on open and on change: unknown `ref()`, unknown
  `depends_on`, cross-context `ref()`/`source()` that must run on duckdb, bad
  directive YAML, cycles, and per-dialect SQL syntax errors.
- **Completion** (omnifunc `<C-x><C-o>`, or any LSP completion plugin): columns of
  the tables/`ref()`/`source()` in the cell — alias-scoped (`m.` → that table's
  columns) via sqlglot; plus `ref('…')` cell names and SQL keywords.
- **Go-to-definition** on a `ref('cell')` jumps to that cell; **document symbols**
  outline the cells.

### Notes

- Completion for postgres/bigquery tables opens a live connection using the cell's
  own DSN/config (cached), so it needs the relevant extra and credentials.
- `ref()` columns come from the upstream cell's **landed** output — run the cell
  once (`quicksql run`) so its sink exists.
- Cells containing `{% %}` control flow skip the SQL-syntax lint pass (the
  compiler diagnostics still cover them).

### BigQuery pipe-syntax validation (optional)

sqlglot (the default linter) can't parse six valid BigQuery pipe operators
(`|> SET / DROP / RENAME / CALL / WINDOW / ASSERT`); such cells get a *warning*
("cell not fully validated") instead of a false error. For reference-grade
validation, install the GoogleSQL (ex-ZetaSQL) `execute_query` binary — it
implements the actual BigQuery grammar:

1. Download `execute_query_linux` or `execute_query_macos` from
   <https://github.com/google/googlesql/releases> (Linux/macOS only) and
   `chmod +x` it.
2. Put it on PATH as `execute_query`, or point the LSP at it explicitly with
   `QSQL_EXECUTE_QUERY=/path/to/execute_query`.

When discoverable, all `@engine: bigquery` cells' syntax diagnostics come from
googlesql (source `googlesql` in the editor) with sqlglot as the fallback.
Parse-only: table names aren't resolved, and completions still use sqlglot, so
a cell using one of the six operators above loses alias-scoped column
completion.
