#!/usr/bin/env bash
# Demo layout: nvim (left) | qsql tui (right), one tmux window.
#
#   ./demo/scene.sh [notebook]      # default: demo.qsql
#
# Driven by demo/demo.tape and demo/build.tape (VHS), but runnable by hand.
# Needs the compose postgres up and the venv built with both extras:
#   docker compose up -d --wait
#   uv sync --extra postgres --extra visidata
set -euo pipefail
cd "$(dirname "$0")"

NOTEBOOK="${1:-demo.qsql}"
SESSION=qsqldemo
ACTIVATE="source ../.venv/bin/activate"

# The tapes edit the notebook for real (nvim writes it — that save is what
# autorun reacts to), so start from the committed version; otherwise a second
# run records an already-edited file.
git checkout -- "$NOTEBOOK" 2>/dev/null || true

# Many boxes advertise LANG=en_US.UTF-8 without having generated it, and
# python's setlocale then raises -> visidata prints "unsupported locale
# setting". Passed with -e because an already-running tmux server keeps its
# own environment and would ignore a plain export.
LOCALE=(-e LC_ALL=C.UTF-8 -e LANG=C.UTF-8)

tmux kill-session -t "$SESSION" 2>/dev/null || true

# match the enclosing terminal so VHS's canvas maps 1:1
tmux new-session -d -s "$SESSION" -x "$(tput cols)" -y "$(tput lines)" \
  -c "$PWD" "${LOCALE[@]}"
tmux set-option -t "$SESSION" status off

# left: the notebook in nvim
tmux send-keys -t "$SESSION" "$ACTIVATE && clear && nvim $NOTEBOOK" Enter

# right: the TUI watching it (ends active, so the tape's first keys reach it)
tmux split-window -h -t "$SESSION" -c "$PWD" "${LOCALE[@]}"
tmux send-keys -t "$SESSION" "$ACTIVATE && clear && qsql tui $NOTEBOOK" Enter

tmux attach -t "$SESSION"
