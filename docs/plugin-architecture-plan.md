# Plan: plugin config + a run-time decorator chain (trimmed)

## Context & goal

Today a `@directive` is **declarative config only** (registry `DIRECTIVES`, assembled by
`config.build_models` via `create_model`). Two things the current architecture genuinely cannot
serve:

1. **Directive-specific validation** — a `Directive` is annotation + default only; there is no
   home for "`output.type` must be a registered sink" or "`retries >= 0`" short of smearing
   checks across `config.py`/`compiler.py`.
2. **Cross-cutting run behavior** — retries, caching, timing, emit-rendered-SQL all mean editing
   `runner._run_cell` and tangling there.

Goal: a **plugin bundles (1) its config, (2) validation for that config, and (3) optionally
run-time behavior** that decorates cell execution. The compile pipeline stays explicit core.
Executors, sinks, and source readers stay **Strategy leaves** (selected, not wrapped) with their
existing registries. The `.qsql` file format, the CLI, and the full test suite keep working;
migration is incremental and green at every step.

An earlier draft also plugin-ized the compile-time seams (`render_globals`, `edges`,
`select_executor`, `select_sink`). Those are cut — see "Explicitly kept core" below.

## Explicitly kept core (and why)

- **`render.py` globals** (`ref`/`source`/`var`/`env`) — `ref` and `source` record side-channel
  state during rendering (dependency edges, required DuckDB extensions) that a globals-dict hook
  can't carry; all four stay core.
- **`depends_on` edge collection** — one line in the compiler (`compiler.py:118`).
- **`resolve_engine`/`resolve_sink`** (`config.py:111-127`) and the engine guardrail
  (`compiler._check_engine_guardrail`) — single-strategy decisions; only one plugin would ever
  answer each question, so hooks there are indirection without payoff.
- Revisit only if third-party *compile-time* extension becomes a real goal.

## The `Plugin` base

```python
class Plugin:
    Config: type[BaseModel] = EmptyConfig   # fields + @field_validator/@model_validator
    scope: Scope = Scope.BOTH
    priority: int = 0                        # decorator-chain order (lower = outermore)

    def run(self, cell, ctx, inner) -> RunResult:   # default: pass-through
        return inner(cell, ctx)
```

`@plugin` registers into a single `PLUGINS` registry (snapshot/restore like the others). The
registry derives a **field → plugin map** from each `Config.model_fields`; registering a duplicate
field name **raises** — pydantic silently MRO-shadows duplicate fields under multiple inheritance
(verified by spike), so the guard is mandatory, not optional.

Merge strategy moves onto the field as metadata, read back during resolution:

```python
def qfield(default, *, merge=Merge.OVERRIDE, **kw):
    return Field(default, json_schema_extra={"qsql_merge": merge.value}, **kw)
```

## Config composition

Compose each plugin's `Config` into the runtime models by **multiple inheritance**:

```python
def build_models(plugins=PLUGINS):
    g = tuple(p.Config for p in plugins.by_scope(Scope.GLOBAL, Scope.BOTH)) or (BaseModel,)
    c = tuple(p.Config for p in plugins.by_scope(Scope.CELL,   Scope.BOTH)) or (BaseModel,)
    return (create_model("GlobalConfig", __base__=g, __config__=ConfigDict(extra="forbid")),
            create_model("CellConfig",   __base__=c, __config__=ConfigDict(extra="forbid")))
```

Settled by spike against the pinned pydantic 2.13.4:

- `__base__` + `__config__` compose and the config **applies** (extra fields rejected);
  validators and `json_schema_extra` survive composition.
- Mutable defaults are safe (pydantic deep-copies per instantiation) — plugin Configs use plain
  `= {}` defaults; the `_field_spec` deepcopy dance (`config.py:25-29`) is deleted.

## Migration phases (each ends green; test-first, conventional commits)

**Phase 0 — scaffolding, no behavior change.** Add `plugins/base.py` (`Plugin`, `EmptyConfig`,
`qfield`), a `PLUGINS` registry + `@plugin` in `registry.py`. Leave `Directive`/`DIRECTIVES`
intact. Tests: register/lookup, `by_scope`, snapshot/restore, field-map extraction,
field-collision error.

**Phase 1 — config through plugins.** Rewrite the 9 builtins in `plugins/builtin.py` as `Plugin`
subclasses with a `Config` model, adding real validators (`output.type` ∈ registered `SINKS`,
`extensions` entries are strings, …). Switch `config.build_models` to the composition above;
`_combine`/`resolve_global`/`resolve_cell` read merge + scope from the field→plugin map.
**Keep the pre-validation `_check_scope`** so the friendly `ConfigError: unknown directive: @key`
/ `@key is not allowed …` messages (asserted in `test_config.py`) survive — don't lean on
`extra="forbid"`. Delete `Directive`, `DirectiveRegistry`, `DIRECTIVES` and update their
consumers: `models.py`, `registry.py`, `config.py`, `compiler.py` imports/signature defaults,
`tests/conftest.py` snapshot fixtures, `tests/test_registry.py`. Every `test_config.py` behavior
assertion (defaults/merge/scope) stays green; add validator-rejection tests.

**Phase 2 — the execution decorator chain (payoff).** Extract the `runner._run_cell` core
(`runner.py:46-73`) into a base cell-runner callable; per cell, wrap it with
`sorted(plugins_overriding_run, key=priority)` and invoke the chain.

- The catch-all error wrapper stays **outside** the chain, so a buggy plugin degrades to
  `RunResult(error=...)` and the run continues — same failure envelope as today.
- Upstream-sink `prepare` (`runner.py:57-63`) needs `project`; keep it in the base runner via
  closure over `project` — the chain signature stays `(cell, ctx)`.
- **Consolidate extension loading**: today both `runner.py:65-66` and
  `executors/duckdb_exec.py:27` load `cell.extensions`; keep one site (the base runner).
- **Wire the dead `@extensions` directive** (red test first): nothing reads `cfg.extensions`
  today — `RenderedCell.extensions` (`compiler.py:115`) is render-collected only. New behavior:
  union of config-declared + render-collected. Knock-on: a non-DuckDB cell declaring
  `@extensions` now (correctly) trips the engine guardrail — test that.
- Ship two demonstrators that need **zero core edits**: `EmitSql` (global `render_dir` config +
  a `run` hook that writes each `cell.sql` before delegating) and a `Retries` plugin (tests
  only, re-invokes `inner` on error results).

Tests: `test_runner.py` stays green; chain-ordering test with stub plugins; `run`-hook tests
against a stub `inner`; `@extensions` wiring + guardrail tests; EmitSql end-to-end.

**Phase 3 — cleanup + docs + escape hatch.** Remove dead paths; write a plugin-authoring guide
(Config + validators + `run`, priority conventions); update README + CLAUDE.md. Optional: load a
user `qsqlrc.py` / `--plugins module.path` so third parties register config/behavior plugins
without editing core (VisiData-style config-as-code).

## Cross-cutting concerns

- **Ordering** is load-bearing: document a `priority` convention (outermost → innermost, e.g.
  retries > cache > timing > base) and sort deterministically (priority, then registration order).
- **Back-compat**: file format + CLI unchanged; `RenderedCell`/`RunResult`/`RunContext` shapes
  preserved, so `watcher.py`, `tui.py`, and `cli.py` need no changes (verified: they read only
  `config.autorun`, `hash`, and `RunResult` fields).
- **Keep strategies as strategies**: `@executor`/`@sink`/`@source_reader` registries stay. Only
  cross-cutting *behavior* moves to decorators.

## Non-goals / risks

- Do **not** plugin-ize the compile pipeline (parser, render globals, edge collection,
  engine/sink resolution, Kahn `topo_sort`, dict merge) — single-strategy indirection, no benefit.
- Over-abstraction risk is structurally mitigated: only the two seams with proven need are
  plugin-ized, and `EmitSql`/`Retries` prove the run seam immediately.

## Verification

Green suite after every phase (`uv run pytest`), plus: validator-rejection tests; a `run`-chain
ordering test; an end-to-end `uv run qsql run --set render_dir=build/sql` that emits
`build/sql/<cell>.sql`; and a scratch third-party plugin (custom `@plugin`) proving config + a
behavior extend the tool without core edits.
