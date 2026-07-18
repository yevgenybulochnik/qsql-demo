import pytest

from quicksql.errors import CycleError
from quicksql.graph import downstream, topo_sort


def test_topo_sort_chain_and_branch() -> None:
    order = topo_sort(["c", "b", "a"], {"c": ["b"], "b": ["a"], "a": []})
    assert order == ["a", "b", "c"]


def test_topo_sort_is_deterministic_by_given_order() -> None:
    order = topo_sort(["x", "y", "join"], {"x": [], "y": [], "join": ["x", "y"]})
    assert order == ["x", "y", "join"]


def test_cycle_raises_with_path() -> None:
    with pytest.raises(CycleError, match="a -> b -> a"):
        topo_sort(["a", "b"], {"a": ["b"], "b": ["a"]})


def test_self_reference_is_a_cycle() -> None:
    with pytest.raises(CycleError):
        topo_sort(["a"], {"a": ["a"]})


def test_downstream_includes_changed_and_dependents_in_topo_order() -> None:
    nodes = ["a", "b", "c", "d"]
    edges = {"a": [], "b": ["a"], "c": ["b"], "d": []}
    assert downstream(nodes, edges, {"a"}) == ["a", "b", "c"]
    assert downstream(nodes, edges, {"b"}) == ["b", "c"]
    assert downstream(nodes, edges, {"d"}) == ["d"]
