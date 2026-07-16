---
name: verify
description: Drive the qsql TUI end-to-end in tmux to verify changes at the terminal surface.
---

# Verifying qsql changes

The runtime surface is the TUI (and the CLI). Drive it in an isolated tmux:

```bash
SCRATCH=$(mktemp -d)
cat > $SCRATCH/base.qsql <<'EOF'
-- @cell events
SELECT 1 AS id, {'name': 'signup', 'params': [{'key': 'plan', 'value': 9}]} AS event;
EOF
tmux -L qsqlverify new-session -d -x 110 -y 30 -c $SCRATCH \
  "uv run --project <repo> qsql tui $SCRATCH/base.qsql"
sleep 5   # app boot takes a few seconds under uv
tmux -L qsqlverify send-keys R      # run all (arms autorun)
tmux -L qsqlverify capture-pane -p  # evidence
tmux -L qsqlverify kill-server
```

Gotchas:
- Send keys one at a time with sleeps; the app debounces workers ("loading …" in the header means a worker is still going).
- The struct-producing cell above exercises nested schema paths (catalog browser `S`, field-path sheets).
- Quit with `q` until the app exits; the tmux session dies with it.
- Flows worth driving: R (run all), Enter (dive), S (catalog; Enter drills, q pops), f (live regex filter; Enter commits, Esc cancels), y (yank → check the toast), F/I, o (picker).
