"""Import the builtin plugin modules so their decorators self-register."""


def load_builtins() -> None:
    from . import executors, plugins, sinks, sources  # noqa: F401
