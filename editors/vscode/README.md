# quicksql for VS Code

Language support for quicksql SQL notebooks (`.qsql` / `.qsql.sql`): syntax
highlighting for cells, directives and Jinja on top of SQL, plus diagnostics,
column completion, go-to-definition on `ref()` and a cell outline — all served
by the quicksql language server (see `../README.md` for what it does and needs).

## Install

The extension is a thin client; the server ships separately:

```sh
uv tool install 'quicksql[lsp]'      # server on PATH (or: pipx install 'quicksql[lsp]')
```

Build and install the extension:

```sh
cd editors/vscode
npm install
npm run package                       # -> quicksql-<version>.vsix
code --install-extension quicksql-*.vsix
```

If `quicksql` is not on VS Code's PATH, set `quicksql.serverPath` in settings.

**Remote-SSH**: install the extension into the *remote* ("Install in SSH: …") —
LSP extensions run on the remote side, which is where `quicksql` and your
notebooks live.

## Development

```sh
npm install
npm run compile        # typecheck + bundle to out/extension.js
npm test               # grammar scope tests (tests/*.qsql)
code --extensionDevelopmentPath="$PWD" ../../examples/pipeline.qsql
```

The grammar test harness (`vscode-tmgrammar-test`) prints
`grammar not found for "source.sql"` — expected: the SQL body delegates to VS
Code's built-in SQL grammar, which only exists inside VS Code.
