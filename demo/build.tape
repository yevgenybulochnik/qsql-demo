# qsql "build a cell live" GIF — regenerate with:  vhs demo/build.tape
#
# The notebook starts with two Postgres cells; the cross-engine DuckDB cell is
# typed on camera. A newly written cell has no previous hash, so watch mode
# treats it as changed: saving it makes it appear in the TUI *and* run.
#
# Prereqs: docker compose up -d --wait; uv sync --extra postgres --extra visidata;
#          demo data seeded (see demo/README.md).

Output "demo/qsql-build.gif"

Require tmux
Require nvim

Set Shell "zsh"
Set FontSize 12
Set Width 1500
Set Height 850
Set Padding 10
Set TypingSpeed 45ms

# --- setup off camera -------------------------------------------------------
Hide
Type "cd demo" Enter
Type "clear" Enter
Show

# --- the layout: nvim | qsql tui --------------------------------------------
Type "./scene.sh build.qsql" Sleep 700ms Enter
Sleep 8s

# --- beat 1: run the two Postgres cells (focus starts on the TUI pane) -------
# Doubles as cover: lazy.nvim's startup notification fades while this runs.
Type "R"
Sleep 6s

# --- beat 2: write a new cross-engine cell, on camera ------------------------
Ctrl+B
Type "o"
Sleep 1s
Type "G"
Type "o"
Sleep 700ms
Enter
Type "-- @cell tier_share"
Enter
Type "-- @engine: duckdb"
Enter
Type "SELECT tier, revenue"
Enter
Type "FROM {{ ref('shipped_by_tier') }}"
Enter
Type "ORDER BY revenue DESC;"
Escape
Sleep 1s
Type ":w" Sleep 300ms Enter
Sleep 1s

# --- beat 3: the new cell appears in the DAG and runs itself ----------------
Ctrl+B
Type "o"
Sleep 7s

# --- beat 4: VisiData on what it landed -------------------------------------
# The TUI suspends itself while vd runs, so the pane blanks for a beat.
Type "V"
Sleep 6s
Type "q"
Sleep 2500ms
