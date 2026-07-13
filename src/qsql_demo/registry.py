"""Plugin registries and their decorators.

Plugin kinds self-register at import time into module-level singletons:

- ``@plugin``         config + run-behavior plugins (Plugin subclasses)
- ``@executor``       compute backends (Executor subclasses)
- ``@sink``           output destinations (Sink subclasses)
- ``@source_reader``  file readers (functions -> DuckDB reader expression)

Each registry supports ``snapshot``/``restore`` so tests can isolate registrations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterator

from .models import Executor, Merge, Scope, Sink

if TYPE_CHECKING:  # imported lazily to avoid a cycle through plugins/__init__
    from .plugins.base import Plugin


class PluginRegistry:
    """Registry of ``Plugin`` subclasses plus the field -> owning-plugin map.

    Two plugins may not contribute the same config field name: pydantic's
    multiple inheritance silently MRO-shadows duplicates, so registration
    guards against collisions up front.
    """

    def __init__(self) -> None:
        self._items: dict[str, type[Plugin]] = {}
        self._fields: dict[str, str] = {}  # config field name -> plugin name

    def register(self, cls: type[Plugin]) -> type[Plugin]:
        name = getattr(cls, "name", None)
        if not name:
            raise ValueError("a Plugin subclass must set `name`")
        for f in cls.Config.model_fields:
            owner = self._fields.get(f)
            if owner is not None and owner != name:
                raise ValueError(
                    f"config field {f!r} of plugin {name!r} is already provided by plugin {owner!r}"
                )
        self._fields = {f: o for f, o in self._fields.items() if o != name}
        self._items[name] = cls
        for f in cls.Config.model_fields:
            self._fields[f] = name
        return cls

    def get(self, name: str) -> type[Plugin] | None:
        return self._items.get(name)

    def by_scope(self, *scopes: Scope) -> list[type[Plugin]]:
        return [p for p in self._items.values() if p.scope in scopes]

    def field_owner(self, field: str) -> type[Plugin] | None:
        """The plugin class that contributes config field ``field``, if any."""
        name = self._fields.get(field)
        return self._items.get(name) if name else None

    def field_merge(self, field: str) -> Merge:
        """The merge strategy declared on config field ``field`` (default OVERRIDE)."""
        owner = self.field_owner(field)
        if owner is None:
            return Merge.OVERRIDE
        extra = owner.Config.model_fields[field].json_schema_extra
        if isinstance(extra, dict) and "qsql_merge" in extra:
            return Merge(extra["qsql_merge"])
        return Merge.OVERRIDE

    def __contains__(self, name: object) -> bool:
        return name in self._items

    def __iter__(self) -> Iterator[type[Plugin]]:
        return iter(self._items.values())

    def snapshot(self) -> tuple[dict[str, type[Plugin]], dict[str, str]]:
        return dict(self._items), dict(self._fields)

    def restore(self, snap: tuple[dict[str, type[Plugin]], dict[str, str]]) -> None:
        self._items, self._fields = dict(snap[0]), dict(snap[1])


class _ClassRegistry:
    """A name -> class registry used for executors and sinks."""

    def __init__(self) -> None:
        self._items: dict[str, type] = {}

    def register(self, name: str) -> Callable[[type], type]:
        def decorate(cls: type) -> type:
            cls.name = name  # type: ignore[attr-defined]
            self._items[name] = cls
            return cls

        return decorate

    def get(self, name: str) -> type | None:
        return self._items.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self._items

    def snapshot(self) -> dict[str, type]:
        return dict(self._items)

    def restore(self, snap: dict[str, type]) -> None:
        self._items = dict(snap)


class ExecutorRegistry(_ClassRegistry):
    pass


class SinkRegistry(_ClassRegistry):
    pass


@dataclass
class SourceReaderSpec:
    name: str
    func: Callable[[Any], str]
    extensions: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()


class SourceReaderRegistry:
    def __init__(self) -> None:
        self._items: dict[str, SourceReaderSpec] = {}
        self._by_ext: dict[str, str] = {}

    def register(
        self,
        name: str,
        *,
        extensions: tuple[str, ...] = (),
        requires: tuple[str, ...] = (),
    ) -> Callable[[Callable[[Any], str]], Callable[[Any], str]]:
        def decorate(func: Callable[[Any], str]) -> Callable[[Any], str]:
            spec = SourceReaderSpec(name, func, tuple(extensions), tuple(requires))
            self._items[name] = spec
            for ext in extensions:
                self._by_ext[ext] = name
            return func

        return decorate

    def get(self, name: str) -> SourceReaderSpec | None:
        return self._items.get(name)

    def for_extension(self, ext: str) -> SourceReaderSpec | None:
        name = self._by_ext.get(ext)
        return self._items.get(name) if name else None

    def __contains__(self, name: object) -> bool:
        return name in self._items

    def snapshot(self) -> tuple[dict[str, SourceReaderSpec], dict[str, str]]:
        return dict(self._items), dict(self._by_ext)

    def restore(self, snap: tuple[dict[str, SourceReaderSpec], dict[str, str]]) -> None:
        self._items, self._by_ext = dict(snap[0]), dict(snap[1])


# --- global singletons + decorator shims -----------------------------------

PLUGINS = PluginRegistry()
EXECUTORS = ExecutorRegistry()
SINKS = SinkRegistry()
SOURCE_READERS = SourceReaderRegistry()


def plugin(cls: "type[Plugin]") -> "type[Plugin]":
    return PLUGINS.register(cls)


def executor(name: str) -> Callable[[type], type]:
    return EXECUTORS.register(name)


def sink(name: str) -> Callable[[type], type]:
    return SINKS.register(name)


def source_reader(
    name: str,
    *,
    extensions: tuple[str, ...] = (),
    requires: tuple[str, ...] = (),
) -> Callable[[Callable[[Any], str]], Callable[[Any], str]]:
    return SOURCE_READERS.register(name, extensions=extensions, requires=requires)
