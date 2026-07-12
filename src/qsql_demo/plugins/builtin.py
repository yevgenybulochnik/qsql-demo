"""Builtin config directives.

Each is a ``Directive`` subclass declaring a config key: its pydantic
``annotation`` + ``default`` feed ``config.build_models``'s ``create_model``, and
its ``scope`` + ``merge`` drive resolution.
"""

from __future__ import annotations

from typing import Any

from ..models import Directive, Merge, Scope
from ..registry import directive


@directive
class Engine(Directive):
    key = "engine"
    scope = Scope.BOTH
    annotation = str | None
    default = None


@directive
class Input(Directive):
    key = "input"
    scope = Scope.BOTH
    annotation = dict[str, Any]
    default: dict[str, Any] = {}
    merge = Merge.DEEP


@directive
class Sources(Directive):
    key = "sources"
    scope = Scope.BOTH
    annotation = dict[str, Any]
    default: dict[str, Any] = {}
    merge = Merge.DEEP


@directive
class Extensions(Directive):
    key = "extensions"
    scope = Scope.BOTH
    annotation = list[str]
    default: list[str] = []
    merge = Merge.EXTEND


@directive
class Output(Directive):
    key = "output"
    scope = Scope.BOTH
    annotation = dict[str, Any]
    default: dict[str, Any] = {"type": "parquet", "dir": "data/"}
    merge = Merge.DEEP


@directive
class Autorun(Directive):
    key = "autorun"
    scope = Scope.BOTH
    annotation = bool
    default = True


@directive
class Vars(Directive):
    key = "vars"
    scope = Scope.BOTH
    annotation = dict[str, Any]
    default: dict[str, Any] = {}
    merge = Merge.DEEP


@directive
class DependsOn(Directive):
    key = "depends_on"
    scope = Scope.CELL
    annotation = list[str]
    default: list[str] = []
    merge = Merge.EXTEND


@directive
class Tags(Directive):
    key = "tags"
    scope = Scope.CELL
    annotation = list[str]
    default: list[str] = []
    merge = Merge.EXTEND
