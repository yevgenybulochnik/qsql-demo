#!/usr/bin/env bash
# Demo layout: nvim (left) | qsql tui (right), one tmux window.
#
# Driven by demo/demo.tape (VHS), but runnable by hand:  ./demo/scene.sh
# Needs the compose postgres up and the venv built with both extras:
#   docker compose up -d --wait
#   uv sync --extra postgres --extra visidata
set -euo pipefail
cd "$(dirname "$0")"

SESSION=qsqldemo
ACTIVATE="source ../.venv/bin/activate"

# The tape edits demo.qsql for real (nvim writes it), so start from the
# committed version — otherwise a second run records an already-edited file.
git checkout -- demo.qsql 2>/dev/null || true

# visidata warns "unsupported locale setting" without this
export LC_ALL=C.UTF-8 LANG=C.UTF-8

tmux kill-session -t "$SESSION" 2>/dev/null || true

# match the enclosing terminal so VHS's canvas maps 1:1
tmux new-session -d -s "$SESSION" -x "$(tput cols)" -y "$(tput lines)" -c "$PWD"
tmux set-option -t "$SESSION" status off

# left: the notebook in nvim
tmux send-keys -t "$SESSION" "$ACTIVATE && clear && nvim demo.qsql" Enter

# right: the TUI watching it (ends active, so the tape's first keys reach it)
tmux split-window -h -t "$SESSION" -c "$PWD"
tmux send-keys -t "$SESSION" "$ACTIVATE && clear && qsql tui demo.qsql" Enter

tmux attach -t "$SESSION"
