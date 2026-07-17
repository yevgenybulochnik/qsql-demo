# Editor integration

qsql ships a language server (`qsql lsp`, stdio) that gives per-cell **linting**
and **column completion**, engine-aware — reusing the compiler for diagnostics and
the catalog for live/local schema introspection.

## Install

The server lives behind the `lsp` extra (pygls + sqlglot):

```sh
uv tool install 'qsql-demo[lsp]'      # or: pipx install 'qsql-demo[lsp]'
# in this repo, for development:
uv run --extra lsp qsql lsp           # runs the server on stdio
```

## Neovim

`nvim/qsql.lua` is a self-contained client using the built-in `vim.lsp` (no
plugins required). Load it directly:

```vim
:luafile /path/to/qsql-demo/editors/nvim/qsql.lua
```

or drop it on your `runtimepath` as `lua/qsql.lua` and `require("qsql")`.

It registers `*.qsql` / `*.qsql.sql` as the `qsql` filetype (borrowing SQL syntax
highlighting), then starts `qsql lsp` for each buffer, rooted at the nearest
`qsqlrc.py` / `base.qsql`.

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
  once (`qsql run`) so its sink exists.
- Cells containing `{% %}` control flow skip the SQL-syntax lint pass (the
  compiler diagnostics still cover them).
