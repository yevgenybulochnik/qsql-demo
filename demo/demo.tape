# qsql demo GIF — regenerate with:  vhs demo/demo.tape   (run from the repo root)
#
# Shows: Postgres cells running next to the data, a cross-engine DuckDB cell
# joining their results, a live nvim edit triggering an autorun rerun of just
# the changed cell + its downstream, and the VisiData deep-dive.
#
# Prereqs: docker compose up -d --wait; uv sync --extra postgres --extra visidata;
#          demo data seeded (see demo/README.md).

Output "demo/qsql-demo.gif"

Require tmux
Require nvim

Set Shell "zsh"
Set FontSize 12
Set Width 1500
Set Height 850
Set Padding 10
Set TypingSpeed 55ms

# --- setup off camera -------------------------------------------------------
Hide
Type "cd demo" Enter
Type "clear" Enter
Show

# --- the layout: nvim | qsql tui --------------------------------------------
Type "./scene.sh" Sleep 700ms Enter
Sleep 8s

# --- beat 1: run every cell (focus starts on the TUI pane) -------------------
Type "R"
Sleep 7s

# --- beat 2: edit the SQL in nvim -------------------------------------------
# Filtering out a whole tier takes shipped_by_tier from 3 rows to 2, which
# cascades to tier_share (downstream) but leaves top_customers alone — the
# rerun is legible in the row counts, not just the timings.
Ctrl+B
Type "o"
Sleep 1500ms
Type "/'shipped'" Sleep 400ms Enter
Sleep 800ms
Escape
Type ":noh" Enter
Type "A"
Sleep 400ms
Type " AND c.tier <> 'bronze'"
Escape
Sleep 700ms
Type ":w" Sleep 300ms Enter
Sleep 1500ms

# --- beat 3: autorun reruns the changed cell AND its downstream --------------
Ctrl+B
Type "o"
Sleep 7s

# --- beat 4: VisiData on the landed parquet ---------------------------------
Type "V"
Sleep 6s
Type "q"
Sleep 2s
