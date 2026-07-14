import pytest

from qsql_demo.errors import ParseError
from qsql_demo.parser import body_hash, parse_text

SAMPLE = """\
-- @engine: duckdb
-- @output: { type: parquet, dir: data/ }

/*@
vars: { data_dir: ./seeds }
autorun: true
*/

-- plain comment stays in the header, not a directive

-- @cell users
SELECT * FROM read_csv('{{ var("data_dir") }}/users.csv');

-- @cell events
/*@ input: { bigquery: { project: my-proj } } */
-- @depends_on: [users]
SELECT 1 AS x; -- trailing comment kept in body
"""


def test_global_header_collects_line_and_block_directives() -> None:
    blocks = parse_text(SAMPLE)
    header = blocks[0]
    assert header.name is None
    assert header.directives["engine"] == "duckdb"
    assert header.directives["output"] == {"type": "parquet", "dir": "data/"}
    assert header.directives["vars"] == {"data_dir": "./seeds"}
    assert header.directives["autorun"] is True


def test_cells_split_on_cell_directive() -> None:
    blocks = parse_text(SAMPLE)
    assert [b.name for b in blocks] == [None, "users", "events"]
    users = blocks[1]
    assert "read_csv" in users.sql
    assert users.directives == {}


def test_cell_directives_line_and_block_merge() -> None:
    events = parse_text(SAMPLE)[2]
    assert events.directives["input"] == {"bigquery": {"project": "my-proj"}}
    assert events.directives["depends_on"] == ["users"]
    assert events.sql.strip() == "SELECT 1 AS x; -- trailing comment kept in body"


def test_plain_comments_pass_through_to_sql() -> None:
    header = parse_text(SAMPLE)[0]
    assert "plain comment" in header.sql


def test_block_line_numbers() -> None:
    blocks = parse_text(SAMPLE)
    assert blocks[0].line == 1
    assert [b.line for b in blocks[1:]] == [11, 14]


def test_block_spans_and_source_slices() -> None:
    lines = SAMPLE.splitlines()
    header, users, events = parse_text(SAMPLE)
    assert (header.line, header.line_end) == (1, 10)
    assert header.source == "\n".join(lines[0:10])
    assert (users.line, users.line_end) == (11, 13)
    assert users.source == "\n".join(lines[10:13])
    assert users.source.startswith("-- @cell users")  # directives stay in source
    assert (events.line, events.line_end) == (14, len(lines))
    assert "-- @depends_on: [users]" in events.source


def test_header_only_before_first_cell_on_line_one() -> None:
    blocks = parse_text("-- @cell a\nSELECT 1;")
    assert (blocks[0].line, blocks[0].line_end) == (1, 0)
    assert blocks[0].source == ""
    assert blocks[1].source == "-- @cell a\nSELECT 1;"


def test_body_hash_stable_under_surrounding_whitespace() -> None:
    assert body_hash("SELECT 1") == body_hash("\n  SELECT 1  \n\n".strip())
    assert body_hash("SELECT 1") != body_hash("SELECT 2")


def test_duplicate_cell_name_raises() -> None:
    with pytest.raises(ParseError, match="duplicate cell"):
        parse_text("-- @cell a\nSELECT 1;\n-- @cell a\nSELECT 2;")


def test_cell_without_name_raises() -> None:
    with pytest.raises(ParseError, match="@cell"):
        parse_text("-- @cell\nSELECT 1;")


def test_bad_cell_name_raises() -> None:
    with pytest.raises(ParseError, match="cell name"):
        parse_text("-- @cell 9lives\nSELECT 1;")


def test_invalid_yaml_reports_line() -> None:
    with pytest.raises(ParseError, match="line 1"):
        parse_text("-- @engine: [unclosed\nSELECT 1;")


def test_non_mapping_directive_raises() -> None:
    with pytest.raises(ParseError, match="mapping"):
        parse_text("-- @just a bare string\nSELECT 1;")


def test_unterminated_block_directive_raises() -> None:
    with pytest.raises(ParseError, match="unterminated"):
        parse_text("/*@\nvars: {}\n-- @cell a\nSELECT 1;")


def test_single_line_block_directive() -> None:
    blocks = parse_text("-- @cell a\n/*@ vars: { x: 1 } */\nSELECT {{ var('x') }};")
    assert blocks[1].directives["vars"] == {"x": 1}
