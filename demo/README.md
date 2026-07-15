# demo

The GIF in the project README: Postgres cells running next to the data, a
cross-engine DuckDB cell joining their results, a live nvim edit triggering an
autorun rerun of just the changed cell and its downstream, and the VisiData
deep-dive.

| file | what it is |
|---|---|
| `demo.qsql` | the notebook — two Postgres cells + one DuckDB cell |
| `seed.sql` | the demo tables (8 customers, 5k orders) |
| `scene.sh` | the tmux layout: nvim (left) \| `qsql tui` (right) |
| `demo.tape` | the [VHS](https://github.com/charmbracelet/vhs) script that records it |

## Regenerating the GIF

```console
$ docker compose up -d --wait
$ docker compose exec -T postgres psql -U qsql -d qsql -q < demo/seed.sql
$ uv sync --extra postgres --extra visidata
$ vhs demo/demo.tape                      # from the repo root -> demo/qsql-demo.gif
```

Needs `vhs`, `ttyd`, `ffmpeg`, `tmux` and `nvim` on PATH. VHS shells out to ffmpeg
to encode, so ffmpeg is not optional.

`scene.sh` also runs standalone (`./demo/scene.sh`) if you just want the layout to
poke at by hand — it drops you into the tmux session.

## Note

The tape *really* edits `demo.qsql` — nvim saves it, which is the point (that
save is what autorun reacts to). `scene.sh` therefore starts with
`git checkout -- demo.qsql`, so recordings are repeatable and the file never
drifts. If you edit the notebook, commit it before recording.
