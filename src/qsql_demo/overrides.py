"""The run-time config override layer: CLI ``--set k=v`` and ``QSQL_*`` env vars.

Both produce a nested dict that is merged (highest priority) over global->cell
config during resolution. Values are parsed as YAML scalars so ``false``/``1``/
flow mappings get typed; dotted (``a.b``) and ``__`` paths address nested keys.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

import yaml

from .errors import ConfigError
from .util import deep_merge

_PREFIX = "QSQL_"


def _parse_scalar(value: str) -> Any:
    try:
        parsed = yaml.safe_load(value)
    except yaml.YAMLError:
        return value
    return parsed


def _nest(path: list[str], value: Any) -> dict[str, Any]:
    node: Any = value
    for key in reversed(path):
        node = {key: node}
    return node


def from_cli(pairs: list[str] | None) -> dict[str, Any]:
    """Turn ``["a.b=c", ...]`` into a nested dict."""
    result: dict[str, Any] = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep:
            raise ConfigError(f"--set expects key=value, got {pair!r}")
        result = deep_merge(result, _nest(key.strip().split("."), _parse_scalar(value)))
    return result


def from_env(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Turn ``QSQL_a__b=c`` env vars into a nested dict."""
    environ = os.environ if environ is None else environ
    result: dict[str, Any] = {}
    for name, value in environ.items():
        if not name.startswith(_PREFIX) or name == _PREFIX:
            continue
        path = name[len(_PREFIX) :].split("__")
        result = deep_merge(result, _nest(path, _parse_scalar(value)))
    return result


def collect(
    set_pairs: list[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Combined overrides; CLI ``--set`` wins over ``QSQL_*`` env."""
    return deep_merge(from_env(environ), from_cli(set_pairs))
