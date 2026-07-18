"""quicksql language server — analysis layer (no editor transport needed)."""

from __future__ import annotations

import shutil

import pytest

# the lsp extra (sqlglot + pygls) is optional; skip this whole module without it
pytest.importorskip("sqlglot", reason="install the 'lsp' extra to run LSP tests")

from quicksql.compiler import compile_file
from quicksql.lsp.mask import Opaque, Ref, Source, mask_jinja


def test_mask_preserves_length_and_line_structure() -> None:
    sql = "SELECT *\nFROM {{ ref('users') }} u\nWHERE {% if flag %}x{% endif %}"
    masked, spans = mask_jinja(sql)
    assert len(masked) == len(sql)  # offsets map 1:1
    assert masked.count("\n") == sql.count("\n")  # line numbers preserved
    # non-Jinja text is byte-identical
    assert masked.startswith("SELECT *\nFROM ")
    assert " u\nWHERE " in masked


def test_ref_becomes_a_same_length_sql_identifier_mapped_to_the_cell() -> None:
    sql = "FROM {{ ref('users') }} u"
    masked, spans = mask_jinja(sql)
    ref_spans = [s for s in spans if isinstance(s.tag, Ref)]
    assert len(ref_spans) == 1
    span = ref_spans[0]
    assert span.tag == Ref("users")
    # the placeholder sits exactly where the Jinja was and is a bare identifier
    placeholder = masked[span.start : span.end]
    assert span.end - span.start == len("{{ ref('users') }}")
    assert placeholder.isidentifier()
    # ...so sqlglot reads `FROM <placeholder> u` as a table aliased u
    assert masked == f"FROM {placeholder} u"


def test_source_and_opaque_expressions_are_tagged() -> None:
    sql = "SELECT {{ var('x') }} FROM {{ source('seeds/u.csv') }}"
    _, spans = mask_jinja(sql)
    tags = [s.tag for s in spans]
    assert Source("seeds/u.csv") in tags
    assert any(isinstance(t, Opaque) for t in tags)  # var(...) is opaque


def test_control_and_multiline_blocks_blank_to_spaces_keeping_newlines() -> None:
    sql = "SELECT 1\n{% if a\n   and b %}\nWHERE x{% endif %}"
    masked, spans = mask_jinja(sql)
    assert len(masked) == len(sql)
    assert masked.count("\n") == sql.count("\n")
    # a multi-line {% %} becomes spaces (not an identifier) but newlines survive
    block = next(s for s in spans if s.start == sql.index("{% if"))
    assert set(masked[block.start : block.end]) <= {" ", "\n"}


def test_name_to_tag_round_trip_for_scope_lookup() -> None:
    sql = "FROM {{ ref('a') }} x JOIN {{ ref('b') }} y ON x.k = y.k"
    masked, spans = mask_jinja(sql)
    name_to_tag = {s.name: s.tag for s in spans if s.name}
    # every placeholder identifier resolves back to its ref
    assert set(name_to_tag.values()) == {Ref("a"), Ref("b")}
    for name in name_to_tag:
        assert name in masked


# ---------- schema.py: columns per relation ----------


def _write_run(tmp_path, body):
    from quicksql.runner import run_project

    nb = tmp_path / "n.qsql"
    nb.write_text(body)
    project = compile_file(nb)
    run_project(project)  # land the sinks so refs are introspectable
    return compile_file(nb)


def test_ref_columns_come_from_the_landed_cell(tmp_path) -> None:
    from quicksql.lsp.schema import ref_columns

    project = _write_run(
        tmp_path,
        "-- @engine: duckdb\n-- @output: { type: parquet, dir: data/ }\n"
        "-- @cell users\nSELECT 1 AS id, 'ada' AS name, true AS active;\n",
    )
    cols = dict(ref_columns(project, "users"))
    assert set(cols) == {"id", "name", "active"}


def test_source_columns_read_a_csv_header(tmp_path) -> None:
    from quicksql.lsp.schema import source_columns

    (tmp_path / "u.csv").write_text("member_id,plan_code\n1,AB\n")
    project = _write_run(
        tmp_path,
        "-- @engine: duckdb\n-- @cell probe\nSELECT 1 AS x;\n",
    )
    names = [c for c, _ in source_columns(project, "u.csv")]
    assert names == ["member_id", "plan_code"]


@pytest.mark.postgres
def test_table_columns_introspect_live_postgres(tmp_path) -> None:
    from quicksql.lsp.schema import table_columns

    dsn = "postgresql://quicksql:quicksql@localhost:5432/quicksql_claims"
    nb = tmp_path / "n.qsql"
    nb.write_text(
        "-- @engine: postgres\n"
        f"/*@ input: {{ postgres: {{ dsn: '{dsn}' }} }} */\n"
        "-- @cell probe\nSELECT 1 AS x;\n"
    )
    project = compile_file(nb)
    cell = project.cells["probe"]
    names = [c for c, _ in table_columns(project, cell, "claims.medical_claims")]
    assert "diagnosis_code" in names and "paid_amount" in names


# ---------- analysis.py: diagnostics + completions ----------


def test_diagnostics_flag_unknown_ref_at_the_cell_line(tmp_path) -> None:
    from quicksql.lsp.analysis import Analyzer

    text = "-- @engine: duckdb\n-- @cell a\nSELECT * FROM {{ ref('nope') }};\n"
    diags = Analyzer().diagnostics(text, tmp_path)
    assert any("nope" in d.message for d in diags)
    assert any(d.line == 1 for d in diags)  # the `-- @cell a` line (0-indexed)


def test_diagnostics_flag_cross_context_source_on_non_duckdb(tmp_path) -> None:
    from quicksql.lsp.analysis import Analyzer

    text = "-- @engine: sqlite\n-- @cell a\nSELECT * FROM {{ source('u.csv') }};\n"
    diags = Analyzer().diagnostics(text, tmp_path)
    assert any("duckdb" in d.message for d in diags)


def test_diagnostics_surface_sqlglot_syntax_errors(tmp_path) -> None:
    from quicksql.lsp.analysis import Analyzer

    text = "-- @engine: duckdb\n-- @cell a\nSELECT * FROM WHERE 1;\n"
    diags = Analyzer().diagnostics(text, tmp_path)
    assert any(d.source == "sqlglot" for d in diags)


# ---------- analysis.py: googlesql-backed bigquery diagnostics ----------

# body line 1 = file line 3; `|> SET` is valid BigQuery that sqlglot rejects
_PIPE_TEXT = "-- @engine: bigquery\n-- @cell a\nFROM t\n|> SET x = 2\n"


def _fake_execute_query(tmp_path, stdout: str = "", exit_code: int = 0):
    """A stand-in `execute_query`: swallow stdin, print a canned parse result."""
    payload = tmp_path / "payload.txt"
    payload.write_text(stdout)
    script = tmp_path / "fake_execute_query"
    script.write_text(f"#!/bin/sh\ncat >/dev/null\ncat {payload}\nexit {exit_code}\n")
    script.chmod(0o755)
    return script


def test_googlesql_errors_map_to_cell_relative_positions(tmp_path, monkeypatch) -> None:
    from quicksql.lsp.analysis import Analyzer

    fake = _fake_execute_query(
        tmp_path, "ERROR: Syntax error: boom [at 3:5]\n|> SET x = 2\n    ^\n"
    )
    monkeypatch.setenv("QSQL_EXECUTE_QUERY", str(fake))
    diags = Analyzer().diagnostics(_PIPE_TEXT, tmp_path)
    # cell.source line 1 is the `-- @cell a` line itself, so input line 3 =
    # file line 4 = row 3 (0-indexed); col 5 -> character 4
    assert [(d.line, d.character, d.source) for d in diags] == [(3, 4, "googlesql")]
    assert "boom" in diags[0].message


def test_googlesql_clean_parse_accepts_pipe_operators_sqlglot_rejects(
    tmp_path, monkeypatch
) -> None:
    from quicksql.lsp.analysis import Analyzer

    fake = _fake_execute_query(tmp_path, "QueryStatement [0-19]\n")
    monkeypatch.setenv("QSQL_EXECUTE_QUERY", str(fake))
    assert Analyzer().diagnostics(_PIPE_TEXT, tmp_path) == []


def test_missing_binary_falls_back_to_sqlglot_and_downgrades_pipe_errors(
    tmp_path, monkeypatch
) -> None:
    from quicksql.lsp.analysis import Analyzer

    monkeypatch.delenv("QSQL_EXECUTE_QUERY", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))  # no execute_query discoverable
    diags = Analyzer().diagnostics(_PIPE_TEXT, tmp_path)
    assert [(d.severity, d.source) for d in diags] == [("warning", "sqlglot")]
    assert "pipe" in diags[0].message.lower()


def test_broken_binary_falls_back_to_sqlglot(tmp_path, monkeypatch) -> None:
    from quicksql.lsp.analysis import Analyzer

    fake = _fake_execute_query(tmp_path, "panic", exit_code=1)
    monkeypatch.setenv("QSQL_EXECUTE_QUERY", str(fake))
    diags = Analyzer().diagnostics(_PIPE_TEXT, tmp_path)
    assert [(d.severity, d.source) for d in diags] == [("warning", "sqlglot")]


@pytest.mark.skipif(
    shutil.which("execute_query") is None,
    reason="googlesql execute_query not on PATH",
)
def test_googlesql_real_binary_parses_pipe_syntax(tmp_path, monkeypatch) -> None:
    from quicksql.lsp.analysis import Analyzer

    monkeypatch.delenv("QSQL_EXECUTE_QUERY", raising=False)
    text = "-- @engine: bigquery\n-- @cell a\nFROM t\n|> SET x = 2\n|> DROP y\n"
    assert Analyzer().diagnostics(text, tmp_path) == []


def _land_users(tmp_path, text):
    from quicksql.runner import run_project

    nb = tmp_path / "n.qsql"
    nb.write_text(text)
    run_project(compile_file(nb), select=["users"])  # land users.parquet only


def test_completion_offers_ref_columns_and_alias_scopes_them(tmp_path) -> None:
    from quicksql.lsp.analysis import Analyzer

    text = (
        "-- @engine: duckdb\n-- @output: { type: parquet, dir: data/ }\n"
        "-- @cell users\nSELECT 1 AS id, 'ada' AS name, true AS active;\n"
        "-- @cell down\nSELECT u.id FROM {{ ref('users') }} u\n"
    )
    _land_users(tmp_path, text)
    a = Analyzer()
    down_line = 5  # `SELECT u.id FROM ...` (0-indexed)

    # bare position after SELECT -> union of the cell's columns + keywords
    flat = {c.label for c in a.completions(text, tmp_path, down_line, len("SELECT "))}
    assert {"id", "name", "active"} <= flat
    assert "FROM" in flat  # keywords too

    # after `u.` -> scoped to users' columns
    scoped = a.completions(text, tmp_path, down_line, len("SELECT u."))
    labels = {c.label for c in scoped if c.kind == "field"}
    assert {"id", "name", "active"} <= labels


def test_completion_in_ref_call_offers_cell_names(tmp_path) -> None:
    from quicksql.lsp.analysis import Analyzer

    text = (
        "-- @engine: duckdb\n-- @output: { type: parquet, dir: data/ }\n"
        "-- @cell users\nSELECT 1 AS id;\n"
        "-- @cell down\nSELECT * FROM {{ ref('users') }}\n"
    )
    _land_users(tmp_path, text)
    down_line = 5
    prefix = "SELECT * FROM {{ ref('"  # cursor right after ref('
    items = Analyzer().completions(text, tmp_path, down_line, len(prefix))
    names = {c.label for c in items if c.kind == "reference"}
    assert "users" in names


@pytest.mark.postgres
def test_completion_alias_scopes_to_a_live_postgres_table(tmp_path) -> None:
    from quicksql.lsp.analysis import Analyzer

    dsn = "postgresql://quicksql:quicksql@localhost:5432/quicksql_claims"
    text = (
        "-- @engine: postgres\n"
        f"/*@ input: {{ postgres: {{ dsn: '{dsn}' }} }} */\n"
        "-- @cell probe\nSELECT m.paid_amount FROM claims.medical_claims m\n"
    )
    (tmp_path / "n.qsql").write_text(text)
    probe_line = 3  # the SELECT line (0-indexed)
    scoped = Analyzer().completions(text, tmp_path, probe_line, len("SELECT m."))
    labels = {c.label for c in scoped if c.kind == "field"}
    assert "paid_amount" in labels and "diagnosis_code" in labels


def test_definition_jumps_from_ref_to_the_defining_cell(tmp_path) -> None:
    from quicksql.lsp.analysis import Analyzer

    text = (
        "-- @engine: duckdb\n-- @output: { type: parquet, dir: data/ }\n"
        "-- @cell users\nSELECT 1 AS id;\n"
        "-- @cell down\nSELECT * FROM {{ ref('users') }}\n"
    )
    _land_users(tmp_path, text)
    # cursor inside ref('users') on the `down` cell (line 5)
    target = Analyzer().definition(text, tmp_path, 5, len("SELECT * FROM {{ ref('us"))
    assert target == (2, 0)  # the `-- @cell users` line, 0-indexed


def test_document_symbols_outline_every_cell(tmp_path) -> None:
    from quicksql.lsp.analysis import Analyzer

    text = (
        "-- @engine: duckdb\n-- @cell a\nSELECT 1;\n-- @cell b\nSELECT 2;\n"
    )
    syms = Analyzer().document_symbols(text, tmp_path)
    names = [s[0] for s in syms]
    assert names == ["a", "b"]
    assert all(s[3] == "duckdb" for s in syms)


# ---------- server.py: pygls wiring ----------


def test_server_registers_the_lsp_features_and_maps_diagnostics() -> None:
    pytest.importorskip("pygls", reason="install the 'lsp' extra")
    from lsprotocol import types

    from quicksql.lsp.analysis import Diagnostic
    from quicksql.lsp.server import _to_lsp_diagnostic, create_server

    server = create_server()
    registered = set(server.protocol.fm.features)
    assert {
        types.TEXT_DOCUMENT_DID_OPEN,
        types.TEXT_DOCUMENT_DID_CHANGE,
        types.TEXT_DOCUMENT_COMPLETION,
        types.TEXT_DOCUMENT_DEFINITION,
        types.TEXT_DOCUMENT_DOCUMENT_SYMBOL,
    } <= registered

    lsp_diag = _to_lsp_diagnostic(Diagnostic(2, 0, 2, 9, "boom", "error", "sqlglot"))
    assert lsp_diag.range.start.line == 2
    assert lsp_diag.severity == types.DiagnosticSeverity.Error
    assert lsp_diag.source == "sqlglot" and lsp_diag.message == "boom"


def test_completion_scopes_each_join_alias_to_its_own_ref(tmp_path) -> None:
    from quicksql.lsp.analysis import Analyzer

    text = (
        "-- @engine: duckdb\n-- @output: { type: parquet, dir: data/ }\n"
        "-- @cell users\nSELECT 1 AS user_id, 'ada' AS name;\n"
        "-- @cell events\nSELECT 1 AS user_id, 'click' AS event;\n"
        "-- @cell down\n"
        "SELECT e. FROM {{ ref('users') }} u JOIN {{ ref('events') }} e USING (user_id)\n"
    )
    from quicksql.runner import run_project

    nb = tmp_path / "n.qsql"
    nb.write_text(text)
    run_project(compile_file(nb), select=["users", "events"])
    scoped = Analyzer().completions(text, tmp_path, 7, len("SELECT e."))
    labels = {c.label for c in scoped if c.kind == "field"}
    assert labels == {"user_id", "event"}  # events only — not users' columns


def test_completion_derives_cte_alias_columns_from_its_projection(tmp_path) -> None:
    from quicksql.lsp.analysis import Analyzer

    text = (
        "-- @engine: duckdb\n-- @output: { type: parquet, dir: data/ }\n"
        "-- @cell users\nSELECT 1 AS user_id, 'ada' AS name;\n"
        "-- @cell cte_cell\n"
        "WITH w AS (SELECT user_id, name AS member_name FROM {{ ref('users') }})\n"
        "SELECT w. FROM w\n"
    )
    from quicksql.runner import run_project

    nb = tmp_path / "n.qsql"
    nb.write_text(text)
    run_project(compile_file(nb), select=["users"])
    scoped = Analyzer().completions(text, tmp_path, 6, len("SELECT w."))
    labels = {c.label for c in scoped if c.kind == "field"}
    # the CTE's own projected columns, output alias included
    assert labels == {"user_id", "member_name"}
