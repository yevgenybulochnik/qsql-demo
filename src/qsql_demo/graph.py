"""The cell dependency graph: topological order, cycle detection, downstream sets.

``deps`` maps each cell name to the set of cell names it depends on (from
explicit ``@depends_on`` plus implicit ``ref()`` edges).
"""

from __future__ import annotations

import heapq
from typing import Iterable

from .errors import ConfigError, CycleError


def _ensure_known(deps: dict[str, set[str]]) -> None:
    nodes = set(deps)
    for node, upstreams in deps.items():
        for upstream in upstreams:
            if upstream not in nodes:
                raise ConfigError(f"cell {node!r} depends on unknown cell {upstream!r}")


def _dependents(deps: dict[str, set[str]]) -> dict[str, list[str]]:
    rev: dict[str, list[str]] = {node: [] for node in deps}
    for node, upstreams in deps.items():
        for upstream in upstreams:
            rev[upstream].append(node)
    return rev


def _find_cycle(deps: dict[str, set[str]]) -> list[str]:
    WHITE, GREY, BLACK = 0, 1, 2
    color = {node: WHITE for node in deps}
    stack: list[str] = []
    found: list[str] = []

    def visit(node: str) -> bool:
        color[node] = GREY
        stack.append(node)
        for upstream in deps[node]:
            if color[upstream] == GREY:
                found.extend(stack[stack.index(upstream) :] + [upstream])
                return True
            if color[upstream] == WHITE and visit(upstream):
                return True
        color[node] = BLACK
        stack.pop()
        return False

    for node in deps:
        if color[node] == WHITE and visit(node):
            break
    return found


def topo_sort(deps: dict[str, set[str]]) -> list[str]:
    """Return cell names in dependency order (upstreams first); ties broken alphabetically."""
    _ensure_known(deps)
    indegree = {node: len(upstreams) for node, upstreams in deps.items()}
    dependents = _dependents(deps)

    ready = [node for node, deg in indegree.items() if deg == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        node = heapq.heappop(ready)
        order.append(node)
        for dependent in dependents[node]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, dependent)

    if len(order) != len(deps):
        raise CycleError(_find_cycle(deps))
    return order


def downstream(deps: dict[str, set[str]], changed: Iterable[str]) -> list[str]:
    """Changed cells plus everything transitively depending on them, in topo order."""
    _ensure_known(deps)
    dependents = _dependents(deps)
    affected: set[str] = set()
    stack = [c for c in changed if c in deps]
    while stack:
        node = stack.pop()
        if node in affected:
            continue
        affected.add(node)
        stack.extend(dependents[node])
    return [node for node in topo_sort(deps) if node in affected]
