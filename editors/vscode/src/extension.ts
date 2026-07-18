// quicksql language server client — the counterpart of editors/nvim/qsql.lua.
// Spawns `<quicksql.serverPath> lsp` (stdio) and hands qsql documents to it.

import * as vscode from "vscode";
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
} from "vscode-languageclient/node";

let client: LanguageClient | undefined;

export async function activate(_context: vscode.ExtensionContext): Promise<void> {
  const command = vscode.workspace
    .getConfiguration("quicksql")
    .get<string>("serverPath", "quicksql");

  const serverOptions: ServerOptions = { command, args: ["lsp"] };
  const clientOptions: LanguageClientOptions = {
    documentSelector: [{ language: "qsql" }],
  };

  client = new LanguageClient("quicksql", "quicksql", serverOptions, clientOptions);
  try {
    await client.start();
  } catch {
    client = undefined;
    void vscode.window.showErrorMessage(
      `quicksql: could not start "${command} lsp". Install the server with: ` +
        "uv tool install 'quicksql[lsp]' — or point quicksql.serverPath at it."
    );
  }
}

export function deactivate(): Thenable<void> | undefined {
  return client?.stop();
}
