"""qsql language server: per-cell linting + column completion over LSP.

Editor-agnostic analysis (`mask`, `schema`, `analysis`) is unit-testable without
a running editor; `server` is the thin pygls transport, started by ``qsql lsp``.
"""
