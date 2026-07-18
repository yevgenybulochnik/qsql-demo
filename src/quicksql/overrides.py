"""Run-time config overrides: repeatable --set key.path=value and QUICKSQL_* env vars.

Highest-priority config layer; CLI --set beats environment. Values are parsed
as YAML scalars so ``true``/``3``/plain strings do the right thing.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

import yaml

from .errors import ConfigError

ENV_PREFIX = "QUICKSQL_"


def _assign(tree: dict[str, Any], dotted: str, value: Any) -> None:
    keys = dotted.split(".")
    cur = tree
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
        if not isinstance(cur, dict):
            raise ConfigError(f"override key {dotted!r} conflicts with a scalar at {k!r}")
    cur[keys[-1]] = value


def _scalar(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return text


def parse_set(pairs: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for pair in pairs:
        key, eq, value = pair.partition("=")
        if not eq or not key.strip():
            raise ConfigError(f"--set expects key.path=value, got {pair!r}")
        _assign(out, key.strip(), _scalar(value))
    return out


def parse_env(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    environ = os.environ if environ is None else environ
    out: dict[str, Any] = {}
    for name, value in environ.items():
        if not name.startswith(ENV_PREFIX):
            continue
        dotted = name[len(ENV_PREFIX) :].lower().replace("__", ".")
        _assign(out, dotted, _scalar(value))
    return out


def gather_overrides(
    sets: list[str] | None = None, environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    from .config import deep_merge

    return deep_merge(parse_env(environ), parse_set(sets or []))
