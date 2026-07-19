# Findings: how the LSP handles `var()`, and value substitution in the Jinja mask

An investigation into how the language server treats `vars:` defined in the notebook
file, the false-positive class it uncovered, how sqlfluff solves the same problem, and
the fix that landed in `lsp/mask.py` + `lsp/analysis.py`.

## How the LSP sees `var()`

The LSP handles vars in two independent layers:

1. **SQL analysis never renders.** Diagnostics and completions run on the *raw* cell
   source through the length-preserving Jinja mask (`lsp/mask.py`): every Jinja run is
   replaced in place by text of the same length, so sqlglot error positions and the
   editor cursor map 1:1 back to the buffer. `ref()`/`source()` become tagged identifier
   placeholders; everything else — including `var()`/`env()` — is classified `Opaque`.
2. **Vars are still validated semantically**, because every LSP request calls
   `compile_text`, which runs the real Jinja render with the real plugin context. An
   undefined `var('x')` with no default raises `ConfigError` and surfaces as a per-line
   diagnostic; the mask layer never needs to know.

There is no type checking in either layer: syntax diagnostics are `sqlglot.parse` (or
googlesql `execute_query` for bigquery cells) — `WHERE order_date > 'banana'` is not
flagged, with or without Jinja involved.

## The false positive

Before this change, `Opaque` expressions blanked to spaces. In operand position that
leaves a dangling operator:

```sql
SELECT * FROM orders WHERE order_date > {{ var('startdate') }}
-- masked:
SELECT * FROM orders WHERE order_date >
```

sqlglot (every dialect tested) reports `Required keyword: 'expression' missing` — an
error squiggle on a line that is fine at runtime. Blanking works where the Jinja stands
alone as a whole clause; in operand position it does not read as a value.

## How sqlfluff handles the same problem

sqlfluff (checked at 4.2.2) takes the opposite bet: render fully with placeholder values
from config (`[sqlfluff:templater:jinja:context]`), lint the rendered SQL, and map
positions back through a source map — a `TemplatedFile` whose `sliced_file` records
typed slices (`literal` / `templated` / block) pairing source spans with output spans.
Simple templates are sliced with Jinja's own lexer; the general case goes through
`JinjaTracer` (~900 lines): the template is rendered **twice**, the second time with
every tag replaced by alternate code emitting `\0<slice-id>_<length>` markers, and the
marker stream is parsed to reconstruct which raw slice produced which output span
(including one-to-many for loop bodies).

Three behaviors worth noting:

- **Violations inside templated regions are dropped by default**
  (`ignore_templated_areas = True`) — the user can only fix the template, not its
  output.
- **Undefined vars degrade gracefully**: an `UndefinedRecorder` (a remember-don't-raise
  `StrictUndefined`) lets the render finish while emitting one templater violation per
  missing var.
- **No type checking either**: `order_date > {{ startdate }}` renders to
  `order_date > 2026-01-01` — unquoted, which parses as integer arithmetic — and no
  rule objects. Render-with-values buys freedom from masking artifacts, not type
  analysis.

The key observation for quicksql: nearly all of sqlfluff's ~2,200 templater+tracer
lines exist to source-map **control flow**. quicksql's LSP already skips cells
containing `{% %}` (the declared v1 limit), and for expression-only templates the
mapping is trivial. So sqlfluff's benefits are reachable here without the tracer.

## What was implemented

Two length-preserving changes to the mask — the 1:1 coordinate guarantee is untouched:

1. **Opaque expressions become identifier placeholders, never spaces.** A single-line
   `{{ }}` that isn't `ref`/`source` masks to the same `qN` identifier generator that
   table-likes use. `> {{ var('startdate') }}` masks to `> q0qqq…`, which parses as a
   column comparison. Spaces remain only for `{% %}` control tags, comments, and
   multi-line runs (newlines preserved so line numbers hold).
2. **Known var values substitute in place when they fit.** `mask_jinja` gained a
   `var_values` parameter; both analysis call sites (`_syntax_diagnostics`,
   `_resolve_scope`) pass the cell's merged `vars:`. A bare `{{ var('key') }}` whose
   value is known becomes the value itself, space-padded to the run's exact length —
   the same text the runtime render produces.

Substitution applies iff **all** of:

- the run is a single-line `{{ }}` expression, and not a `ref()`/`source()`;
- the body is nothing but `var('key')` or `var('key', default)` (`_BARE_VAR`) — any
  surrounding expression (`| upper`, `~` concatenation, `vars.key`) disqualifies;
- `key` exists in the cell's merged vars (the `default` argument is *not* consulted);
- `str(value)` has no newline and is no longer than the `{{ … }}` run.

Anything else falls back to the identifier placeholder. `_resolve_scope` skips
Opaque-tagged placeholders so an unresolvable var in table position is never treated
as a real relation.

| Source | Cell vars | Masked as |
|---|---|---|
| `> {{ var('start') }}` | `start: '2026-01-01'` | `> 2026-01-01      ` |
| `> {{ var('start') }}` | (undefined) | `> q3qqqqqqqqqqqqqq` |
| `FROM {{ var('tbl') }}` | `tbl: main.orders` | `FROM main.orders     ` |
| `{{ var('q') }}` | 60-char string | placeholder (doesn't fit) |
| `{{ var('s') \| upper }}` | anything | placeholder (not a bare call) |

A bonus fell out of substitution for free: `FROM {{ var('tbl') }} t` with a known value
masks to a real engine-native table reference, so column completions for `t.` work
through the normal schema-introspection path.

## Why the placeholder fallback is still necessary

Vars living in the file (quicksql's advantage over sqlfluff's separate config section)
make substitution work *often*, but not always:

1. **Fit** — the mask is length-preserving; a value longer than its run (or multiline)
   cannot be placed without breaking the coordinate guarantee, which is the thing that
   avoids needing sqlfluff's tracer.
2. **Shape** — non-bare expressions would require evaluating Jinja inside the mask.
3. **Availability** — `env()` reads the environment, and a var may be supplied only at
   run time (`--set vars.x=…`, `QUICKSQL_VARS__X=…`) with no file default. Run-time
   overrides are invisible to the LSP in general: a file-level value can differ from
   what a given `quicksql run --set …` will execute.
4. **Undefined keys** — the placeholder keeps the SQL parseable; the compile-time
   `var()` existence check owns the actual diagnostic.

## Follow-ups (not implemented)

- **Undefined-var recorder** (sqlfluff-style): report every missing var in one pass
  instead of failing the compile on the first. Touches render/compiler, not the mask.
- **Templated-area attribution**: when a syntax error's position lands inside a masked
  span, report it at the template expression rather than the placeholder text.
- **Runtime type traps remain out of scope**: `startdate: 2026-01-01` rendered unquoted
  is integer arithmetic (`2024`) to most engines. No layer here catches that; quoting
  discipline (`startdate: "2026-01-01"` + `'{{ var("startdate") }}'`) is on the author.

## Verification

Red-green: four failing tests first (`tests/test_lsp.py` — mask-level placeholder
parseability, in-place substitution, longer-than-run fallback, analyzer-level
no-false-positive), then the mask/analysis changes; full suite green (284 tests).
