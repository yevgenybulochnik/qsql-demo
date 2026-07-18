"""Registries for every plugin kind, plus the decorators that register into them.

Kinds: config/behavior plugins (``@plugin``), executors (``@executor``),
sinks (``@sink``), and source readers (``@source_reader``). Registration is
import-time; :mod:`quicksql.bootstrap` imports the builtin modules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .errors import ConfigError
from .models import Scope

if TYPE_CHECKING:
    from .plugins.base import Plugin


class Registry:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._items: dict[str, Any] = {}

    def register(self, name: str, obj: Any) -> None:
        if name in self._items:
            raise ConfigError(f"duplicate {self.kind} registration: {name!r}")
        self._items[name] = obj

    def get(self, name: str) -> Any:
        try:
            return self._items[name]
        except KeyError:
            have = ", ".join(self._items) or "none"
            raise ConfigError(f"unknown {self.kind}: {name} (registered: {have})") from None

    def names(self) -> list[str]:
        return list(self._items)

    def values(self) -> list[Any]:
        return list(self._items.values())

    def __contains__(self, name: object) -> bool:
        return name in self._items

    def snapshot(self) -> dict[str, Any]:
        return dict(self._items)

    def restore(self, snap: dict[str, Any]) -> None:
        self._items = dict(snap)


@dataclass
class FieldEntry:
    """One config field: which plugin owns it and its pydantic FieldInfo."""

    plugin: Plugin
    field_name: str
    info: Any

    @property
    def key(self) -> str:
        return self.info.alias or self.field_name


def _config_fields(p: Plugin) -> dict[str, FieldEntry]:
    out: dict[str, FieldEntry] = {}
    for fname, info in type(p).Config.model_fields.items():
        entry = FieldEntry(plugin=p, field_name=fname, info=info)
        out[entry.key] = entry
    return out


class PluginRegistry(Registry):
    """Also derives the directive-key -> plugin map; duplicate fields are an error
    (pydantic would silently MRO-shadow them during model composition)."""

    def register(self, name: str, obj: Any) -> None:
        existing = self.field_map()
        for key in _config_fields(obj):
            if key in existing:
                raise ConfigError(
                    f"plugin {name!r} redefines config field {key!r} "
                    f"(already provided by plugin {existing[key].plugin.name!r})"
                )
        super().register(name, obj)

    def field_map(self) -> dict[str, FieldEntry]:
        out: dict[str, FieldEntry] = {}
        for p in self.values():
            out.update(_config_fields(p))
        return out

    def by_scope(self, *scopes: Scope) -> list[Plugin]:
        return [p for p in self.values() if p.scope in scopes]

    def overriding(self, method: str) -> list[Plugin]:
        """Plugins overriding a base hook, in (priority, registration) order."""
        from .plugins.base import Plugin

        base = getattr(Plugin, method)
        hooked = [
            (p.priority, i, p)
            for i, p in enumerate(self.values())
            if getattr(type(p), method) is not base
        ]
        return [p for _, _, p in sorted(hooked, key=lambda t: (t[0], t[1]))]

    def first_result(self, method: str, *args: Any) -> Any:
        """Ask plugins in (priority, registration) order; first non-None wins."""
        for p in self.overriding(method):
            result = getattr(p, method)(*args)
            if result is not None:
                return result
        return None

    def chain(self) -> list[Plugin]:
        """Plugins participating in the execution chain, outermost first."""
        from .plugins.base import RUN_HOOKS, Plugin

        hooked = [
            (p.priority, i, p)
            for i, p in enumerate(self.values())
            if any(getattr(type(p), m) is not getattr(Plugin, m) for m in RUN_HOOKS)
        ]
        return [p for _, _, p in sorted(hooked, key=lambda t: (t[0], t[1]))]


PLUGINS = PluginRegistry("plugin")
EXECUTORS = Registry("executor")
SINKS = Registry("sink")
SOURCE_READERS = Registry("source reader")

ALL_REGISTRIES: list[Registry] = [PLUGINS, EXECUTORS, SINKS, SOURCE_READERS]


def _snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def plugin(cls: type) -> type:
    cls.name = getattr(cls, "name", "") or _snake(cls.__name__)
    PLUGINS.register(cls.name, cls())
    return cls


def executor(name: str):
    def deco(cls: type) -> type:
        cls.name = name
        EXECUTORS.register(name, cls())
        return cls

    return deco


def sink(name: str):
    def deco(cls: type) -> type:
        cls.name = name
        SINKS.register(name, cls)  # class: sinks are instantiated per cell with (cfg, root)
        return cls

    return deco


def source_reader(name: str):
    def deco(cls: type) -> type:
        cls.name = name
        SOURCE_READERS.register(name, cls())
        return cls

    return deco
