import polars as pl

from qsql_demo.sheet import Sheet

FRAME = pl.DataFrame(
    {
        "name": ["ada", "bob", "cyd", "bob"],
        "score": [3, 1, 2, 1],
        "active": [True, False, True, True],
    }
)


def test_cursor_moves_and_clamps() -> None:
    sheet = Sheet(FRAME)
    assert sheet.move(-1, -1).cursor == (0, 0)
    assert sheet.move(2, 1).cursor == (2, 1)
    assert sheet.move(99, 99).cursor == (3, 2)
    assert sheet.bottom().cursor[0] == 3
    assert sheet.bottom().top().cursor[0] == 0


def test_sort_by_cursor_column() -> None:
    sheet = Sheet(FRAME).move(0, 1)  # cursor on "score"
    assert sheet.sort().frame["score"].to_list() == [1, 1, 2, 3]
    assert sheet.sort(desc=True).frame["score"].to_list() == [3, 2, 1, 1]


def test_hide_column() -> None:
    sheet = Sheet(FRAME).move(0, 1).hide_current()
    assert sheet.columns == ["name", "active"]
    assert "score" not in sheet.visible().columns
    assert sheet.cursor[1] <= len(sheet.columns) - 1


def test_select_rows() -> None:
    sheet = Sheet(FRAME).toggle_select().move(1, 0).toggle_select()
    assert sheet.selected == {0, 1}
    assert sheet.toggle_select().selected == {0}
    assert sheet.select_all().selected == {0, 1, 2, 3}
    assert sheet.select_all().select_all().selected == set()


def test_frequency_of_cursor_column() -> None:
    freq = Sheet(FRAME).freq()  # cursor on "name"
    assert freq.frame.columns == ["name", "count", "share"]
    top = freq.frame.row(0, named=True)
    assert top["name"] == "bob" and top["count"] == 2 and abs(top["share"] - 0.5) < 1e-9
    assert freq.title.startswith("freq")


def test_describe_pushes_summary() -> None:
    described = Sheet(FRAME).describe()
    assert "statistic" in described.frame.columns
    assert described.frame.height > 0


def test_search_wraps_and_moves_cursor() -> None:
    sheet = Sheet(FRAME)
    hit = sheet.search("bob")
    assert hit.cursor[0] == 1
    again = hit.search("bob")
    assert again.cursor[0] == 3
    wrapped = again.search("bob")
    assert wrapped.cursor[0] == 1
    missing = sheet.search("zelda")
    assert missing.cursor == sheet.cursor
