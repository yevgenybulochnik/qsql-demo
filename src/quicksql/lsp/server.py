"""pygls transport: bind the editor-agnostic `Analyzer` to LSP methods.

Thin by design — every handler pulls the document text, hands it to the
`Analyzer`, and maps the plain result back to lsprotocol types. Started by
``quicksql lsp`` (see `cli.py`), spoken over stdio.
"""

from __future__ import annotations

from pathlib import Path

from lsprotocol import types
from pygls.lsp.server import LanguageServer

from .analysis import Analyzer, Diagnostic

_KIND = {
    "field": types.CompletionItemKind.Field,
    "reference": types.CompletionItemKind.Reference,
    "keyword": types.CompletionItemKind.Keyword,
}
_SEVERITY = {
    "error": types.DiagnosticSeverity.Error,
    "warning": types.DiagnosticSeverity.Warning,
}


def _to_lsp_diagnostic(d: Diagnostic) -> types.Diagnostic:
    return types.Diagnostic(
        range=types.Range(
            start=types.Position(line=d.line, character=d.character),
            end=types.Position(line=d.end_line, character=d.end_character),
        ),
        message=d.message,
        severity=_SEVERITY.get(d.severity, types.DiagnosticSeverity.Error),
        source=d.source,
    )


def _root(doc) -> Path:
    return Path(doc.path).parent if doc.path else Path(".")


def create_server() -> LanguageServer:
    server = LanguageServer("qsql-lsp", "0.1")
    analyzer = Analyzer()

    def publish(ls: LanguageServer, uri: str) -> None:
        doc = ls.workspace.get_text_document(uri)
        diags = [_to_lsp_diagnostic(d) for d in analyzer.diagnostics(doc.source, _root(doc))]
        ls.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(uri=uri, diagnostics=diags)
        )

    @server.feature(types.TEXT_DOCUMENT_DID_OPEN)
    def did_open(ls: LanguageServer, params: types.DidOpenTextDocumentParams) -> None:
        publish(ls, params.text_document.uri)

    @server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
    def did_change(ls: LanguageServer, params: types.DidChangeTextDocumentParams) -> None:
        publish(ls, params.text_document.uri)

    @server.feature(
        types.TEXT_DOCUMENT_COMPLETION,
        types.CompletionOptions(trigger_characters=[".", " ", "("]),
    )
    def completion(
        ls: LanguageServer, params: types.CompletionParams
    ) -> types.CompletionList:
        doc = ls.workspace.get_text_document(params.text_document.uri)
        items = analyzer.completions(
            doc.source, _root(doc), params.position.line, params.position.character
        )
        return types.CompletionList(
            is_incomplete=False,
            items=[
                types.CompletionItem(
                    label=c.label, kind=_KIND.get(c.kind), detail=c.detail or None
                )
                for c in items
            ],
        )

    @server.feature(types.TEXT_DOCUMENT_DEFINITION)
    def definition(
        ls: LanguageServer, params: types.DefinitionParams
    ) -> types.Location | None:
        doc = ls.workspace.get_text_document(params.text_document.uri)
        loc = analyzer.definition(
            doc.source, _root(doc), params.position.line, params.position.character
        )
        if loc is None:
            return None
        pos = types.Position(line=loc[0], character=loc[1])
        return types.Location(
            uri=params.text_document.uri, range=types.Range(start=pos, end=pos)
        )

    @server.feature(types.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
    def document_symbol(
        ls: LanguageServer, params: types.DocumentSymbolParams
    ) -> list[types.DocumentSymbol]:
        doc = ls.workspace.get_text_document(params.text_document.uri)
        out: list[types.DocumentSymbol] = []
        for name, start, end, engine in analyzer.document_symbols(doc.source, _root(doc)):
            rng = types.Range(
                start=types.Position(line=start, character=0),
                end=types.Position(line=end, character=0),
            )
            out.append(
                types.DocumentSymbol(
                    name=name,
                    detail=engine,
                    kind=types.SymbolKind.Class,
                    range=rng,
                    selection_range=rng,
                )
            )
        return out

    return server


def start_io() -> None:
    """Run the language server over stdio (blocks until the client exits)."""
    create_server().start_io()
