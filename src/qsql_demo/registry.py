"""Plugin registries and their decorators.

Four plugin kinds self-register at import time into module-level singletons:

- ``@directive``      config keys (Directive subclasses)
- ``@executor``       compute backends (Executor subclasses)
- ``@sink``           output destinations (Sink subclasses)
- ``@source_reader``  file readers (functions -> DuckDB reader expression)

Each registry supports ``snapshot``/``restore`` so tests can isolate registrations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from .models import Directive, Executor, Scope, Sink


class DirectiveRegistry:
    def __init__(self) -> None:
        self._items: dict[str, type[Directive]] = {}

    def register(self, cls: type[Directive]) -> type[Directive]:
        if not getattr(cls, "key", None):
            raise ValueError("a Directive subclass must set `key`")
        self._items[cls.key] = cls
        return cls

    def get(self, key: str) -> type[Directive] | None:
        return self._items.get(key)

    def by_scope(self, *scopes: Scope) -> list[type[Directive]]:
        return [d for d in self._items.values() if d.scope in scopes]

    def __contains__(self, key: object) -> bool:
        return key in self._items

    def __iter__(self) -> Iterator[type[Directive]]:
        return iter(self._items.values())

    def snapshot(self) -> dict[str, type[Directive]]:
        return dict(self._items)

    def restore(self, snap: dict[str, type[Directive]]) -> None:
        self._items = dict(snap)


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

DIRECTIVES = DirectiveRegistry()
EXECUTORS = ExecutorRegistry()
SINKS = SinkRegistry()
SOURCE_READERS = SourceReaderRegistry()


def directive(cls: type[Directive]) -> type[Directive]:
    return DIRECTIVES.register(cls)


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
