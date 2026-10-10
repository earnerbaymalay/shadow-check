#!/usr/bin/env bash
# Starts the Shadow Check dashboard if it isn't running, then opens it in the browser.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
PORT="${PORT:-8765}"
URL="http://127.0.0.1:$PORT/"
if ! curl -fs -m 2 -o /dev/null "$URL"; then
  mkdir -p logs
  nohup .venv/bin/python -u -m shadowcheck dashboard --port "$PORT" >> logs/dashboard.log 2>&1 &
  for _ in $(seq 1 25); do curl -fs -m 1 -o /dev/null "$URL" && break; sleep 0.3; done
fi
[ -z "$NO_OPEN" ] && xdg-open "$URL"
exit 0
