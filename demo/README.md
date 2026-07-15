# demo

The GIF in the project README: Postgres cells running next to the data, a
cross-engine DuckDB cell joining their results, a live nvim edit triggering an
autorun rerun of just the changed cell and its downstream, and the VisiData
deep-dive.

Two tapes, two stories:

- **`demo.tape`** → `qsql-demo.gif` — *the workflow.* Edits an existing cell; the
  rerun cascades to its downstream while the unrelated cell stays untouched.
- **`build.tape`** → `qsql-build.gif` — *the format.* Writes a cross-engine cell
  on camera; saving it makes the cell appear in the DAG and run itself (a new
  cell has no previous hash, so watch mode counts it as changed).

| file | what it is |
|---|---|
| `demo.qsql` | the finished notebook — two Postgres cells + one DuckDB cell |
| `build.qsql` | the same, minus the DuckDB cell — `build.tape` types it live |
| `seed.sql` | the demo tables (8 customers, 5k orders) |
| `scene.sh` | the tmux layout: nvim (left) \| `qsql tui` (right); takes a notebook name |
| `demo.tape`, `build.tape` | the [VHS](https://github.com/charmbracelet/vhs) scripts |

## Regenerating the GIFs

```console
$ docker compose up -d --wait
$ docker compose exec -T postgres psql -U qsql -d qsql -q < demo/seed.sql
$ uv sync --extra postgres --extra visidata
$ vhs demo/demo.tape                      # from the repo root -> demo/qsql-demo.gif
$ vhs demo/build.tape                     #                    -> demo/qsql-build.gif
```

Needs `vhs`, `ttyd`, `ffmpeg`, `tmux` and `nvim` on PATH. VHS shells out to ffmpeg
to encode, so ffmpeg is not optional.

`scene.sh` also runs standalone (`./demo/scene.sh`) if you just want the layout to
poke at by hand — it drops you into the tmux session.

## Notes

The tapes *really* edit the notebook — nvim saves it, which is the point (that
save is what autorun reacts to). `scene.sh` therefore starts with
`git checkout -- <notebook>`, so recordings are repeatable and the file never
drifts. If you edit a notebook, commit it before recording.

`build.tape` runs its `R` beat before ever showing the nvim pane. That is
deliberate: lazy.nvim's startup notification needs a few seconds to fade, and
the TUI beat covers exactly that window.
