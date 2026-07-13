# Writing a qsql plugin

A plugin is one class that bundles a **config directive** (a pydantic model, with
validators) and, optionally, **run-time behavior** that wraps cell execution. It
registers itself with the `@plugin` decorator — no core files change.

```python
from pydantic import BaseModel, field_validator
from qsql_demo.models import Merge, Scope
from qsql_demo.plugins.base import Plugin, qfield
from qsql_demo.registry import plugin


@plugin
class Retries(Plugin):
    name = "retries"              # required, unique
    scope = Scope.BOTH            # GLOBAL (header only), CELL (cell only), BOTH (default)
    priority = 0                  # decorator-chain order; lower wraps outermore

    class Config(BaseModel):
        retries: int = qfield(0, ge=0)

    def run(self, cell, ctx, inner):
        result = inner(cell, ctx)
        for _ in range(cell.config.retries):
            if result.ok:
                break
            result = inner(cell, ctx)
        return result
```

With that registered, cells accept a `-- @retries: 2` directive and failed runs are
retried. Import is registration: the class must be imported before the project
compiles (builtins live in `plugins/builtin.py`; third-party code registers by
importing its own module before calling `Project.from_file`/`run`).

## Config: fields become directives

- Every field of `Config` becomes a directive at the plugin's `scope`. Two plugins
  may not declare the same field name — registration raises.
- `config.build_models()` composes all registered Configs into the
  `GlobalConfig`/`CellConfig` models by multiple inheritance, so `@field_validator`/
  `@model_validator` come along. Validation errors surface as `ConfigError` at
  compile time (see `Output._known_sink_type` in `plugins/builtin.py`).
- `qfield(default, *, merge=..., **field_kwargs)` sets how a cell's value combines
  with the inherited header value: `Merge.OVERRIDE` (default, scalars), `Merge.DEEP`
  (dicts), `Merge.EXTEND` (lists). A plain pydantic field defaults to OVERRIDE.
- Mutable defaults (`= {}`, `= []`) are safe — pydantic copies them per instance.
- Config-only plugins simply don't override `run` (most builtins: `engine`, `vars`,
  `tags`, …).

## run: the decorator chain

For each cell the runner builds `plugin_a(plugin_b(...(base)))` from every registered
plugin that overrides `run`, sorted by `(priority, registration order)` — **lower
priority is outermore** (runs first, sees the final result last). Convention: retries
outside caching outside timing/emission.

- `inner(cell, ctx)` invokes the rest of the chain and returns a `RunResult`; call it
  zero (short-circuit), one, or several (retry) times.
- `cell` is the compiled `RenderedCell` (`.name`, `.sql`, `.config`, `.engine`,
  `.sink`); `ctx` is the shared `RunContext` (conduit DuckDB connection, caches).
- The base runner returns failures as `RunResult(error=...)` rather than raising, so
  handle errors by inspecting `result.ok`. Exceptions from a plugin escape the chain
  and are caught by the runner's outer wrapper — the cell reports the error and the
  run continues.
- The runner chdirs into the project directory for the run: relative paths land next
  to the project file (see `EmitSql`, the `@render_dir` builtin).

## Testing

Use the `registries` fixture (`tests/conftest.py`) — it snapshots and restores all
global registries, so a test can `PLUGINS.register(...)` (or use `@plugin`) without
leaking. Test a `Config` in isolation by instantiating it, and a `run` hook against a
stub `inner`; `tests/test_runner.py` has chain-ordering, failure-envelope, and retry
examples.

## Not pluggable (on purpose)

Rendering globals (`ref`/`source`/`var`/`env`), dependency edges, engine/sink
resolution, and the DuckDB guardrail are core: each is a single-strategy decision,
and hooks there would add indirection without enabling anything. If a plugin needs
compile-time influence, that's a core change — see `docs/plugin-architecture-plan.md`
for the rationale. A `--plugins module.path` / `qsqlrc.py` loader (registering
third-party plugins without an import shim) is deliberately left as future work.
