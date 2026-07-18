# Plan: capability render context — render behavior moves into plugins

## Context

The render seam shipped with a deliberate limit: plugins may *add* Jinja globals via
`render_context`, but the built-in globals (`ref`/`source`/`var`/`env`) stay hard-coded
in `render.py`, applied last so nothing can shadow them. The reason was the side-channel:
`ref()`/`source()` record dependency edges and required extensions into a private
`Recorder` that plugins can't (and shouldn't) touch.

Consequence: the `Vars` and `Sources` plugins define config *only*; their behavior lives
in core. That contradicts the design goal that a plugin bundles config, validation, and
behavior.

**The fix is a capability contract, not exposure.** Replace the private `Recorder` with a
`RenderContext` object passed to render hooks, carrying sanctioned verbs
(`add_edge`, `producer_expr`, `require_extensions`, `mark_source_used`, `resolve_path`).
Then the four built-in globals become ordinary plugin contributions, and a **collision
guard** replaces "core wins" with a compile-time error — stronger, and symmetric with the
config-field collision guard the registry already enforces.

## Contract changes (breaking, pre-1.0)

- `Plugin.render_context(self, rctx) -> dict | None` — **contribute-only**: return the
  globals you provide; you no longer receive or mutate the shared context dict.
  `rctx.name`, `rctx.config`, `rctx.root` replace the old `(name, config)` arguments.
- `Plugin.after_render(self, rctx, sql) -> str | None` — same `rctx` instead of
  `(name, config)`.
- Two plugins contributing the same context key (or a core-seeded key: `config`) is a
  `ConfigError` naming both providers — shadowing is now loud, not silently ignored.
- `render_sql` returns `(sql, rctx)`; `rctx.edges/.extensions/.used_source` replace the
  `Recorder` fields (same names — compiler churn is minimal).

## New/changed plugins (`plugins/builtin.py`)

- **Refs** (new, behavior-only): contributes `ref(name)` = `rctx.add_edge` +
  `rctx.producer_expr`.
- **Sources** (gains behavior): contributes `source(name_or_path, **opts)` — named-spec
  lookup from its own config, reader resolution, `rctx.require_extensions` +
  `rctx.mark_source_used`.
- **Vars** (gains behavior): contributes `var(key, default)` and `vars`.
- **Env** (new, behavior-only): contributes `env(key, default)`.
- **DevLimit**: signature update only.

`render.py` shrinks to: build `RenderContext`, seed `{"config": ...}`, collect plugin
contributions under the collision guard, render with Jinja, run `after_render`
transformers. What stays core: the Jinja engine itself, the guard, and the pipeline
call order.

## Phases (each ends green; test-first, conventional commits)

**Phase 1 — RenderContext + contribute-only hooks.** Introduce `RenderContext` (absorbs
Recorder), switch both render hooks to the new signatures, add the collision guard.
Core still provides the four globals (as core seeds). Update the two existing
signature-dependent tests; the shadow test becomes a collision-error test. New tests:
capability verbs (unknown ref cell, extension dedupe, path resolution), same-key
collision between two plugins.

**Phase 2 — behaviors move.** Refs/Sources/Vars/Env contribute the globals; core stops
seeding them. All existing render/compiler behavior tests pass unchanged (they drive
`compile_text`). New test proving ownership: restoring the registry *without* the vars
plugin makes `{{ var(...) }}` an undefined-template error — delete the plugin, lose the
feature.

**Phase 3 — introspection + docs.** `quicksql explain` already lists `render_context`
participants (now: refs, sources, vars, env — assert in the CLI test). Update
`docs/plugin-authoring.md` (contribute-only contract, capability verbs, collision
guard) and CLAUDE.md.

## Explicitly out of scope (later ratchet steps, rule of two)

- First-result decision hooks (`resolve_engine`/`should_rerun`/`sink_config`) for
  Engine/Autorun/Schema.
- Compile passes with declared ordering (edge-contribution for DependsOn).

## Verification

Full suite green after each phase; `uv run quicksql run` + `explain` against the scaffold;
the ownership-deletion test; a scratch third-party plugin contributing a custom global
and colliding on purpose to see the error message.
