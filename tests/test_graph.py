"""Tests for the dependency graph: topo sort, cycles, downstream selection."""

from __future__ import annotations

import pytest

from qsql_demo.errors import ConfigError, CycleError
from qsql_demo.graph import downstream, topo_sort


def test_topo_sort_linear() -> None:
    deps = {"a": set(), "b": {"a"}, "c": {"b"}}
    assert topo_sort(deps) == ["a", "b", "c"]


def test_topo_sort_respects_partial_order() -> None:
    deps = {"a": set(), "b": {"a"}, "c": {"a"}, "d": {"b", "c"}}
    order = topo_sort(deps)
    assert order.index("a") < order.index("b") < order.index("d")
    assert order.index("c") < order.index("d")


def test_cycle_raises_cycleerror() -> None:
    with pytest.raises(CycleError):
        topo_sort({"a": {"b"}, "b": {"a"}})


def test_unknown_dependency_raises() -> None:
    with pytest.raises(ConfigError):
        topo_sort({"a": {"ghost"}})


def test_downstream_includes_changed_and_dependents_in_order() -> None:
    deps = {"a": set(), "b": {"a"}, "c": {"b"}, "d": set()}
    assert downstream(deps, ["a"]) == ["a", "b", "c"]
    assert downstream(deps, ["b"]) == ["b", "c"]
    assert downstream(deps, ["d"]) == ["d"]
