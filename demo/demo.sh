#!/usr/bin/env bash
# Demo for the README GIF: start the flawed toy agent, red-team it, open the report.
# Record with e.g. `vhs` or `asciinema rec -c demo/demo.sh`, then convert to media/demo.gif.
# Needs either ANTHROPIC_API_KEY (default backend) or the `claude` CLI (BACKEND=claude-cli).
set -euo pipefail
cd "$(dirname "$0")/.."

BACKEND="${BACKEND:-claude-cli}"
PORT="${PORT:-8765}"
AU="${AU:-angry-users}"   # or: AU="uvx --from git+https://github.com/isaacbitran/angry-users angry-users"

python3 examples/toy_agent.py --serve "$PORT" >/dev/null 2>&1 &
TOY=$!
trap 'kill $TOY 2>/dev/null' EXIT
sleep 1

echo "$ angry-users run --target http://127.0.0.1:$PORT/chat --personas prompt-injector,label-lawyer,memory-poisoner,privacy-prober --turns 2"
$AU run \
  --target "http://127.0.0.1:$PORT/chat" \
  --backend "$BACKEND" \
  --personas prompt-injector,label-lawyer,memory-poisoner,privacy-prober \
  --turns 2 \
  --describe-file examples/toy_description.txt \
  --facts-file examples/toy_facts.json \
  --personas-see-facts \
  --out angry-users-report

if command -v open >/dev/null; then open angry-users-report/report.html
elif command -v xdg-open >/dev/null; then xdg-open angry-users-report/report.html; fi
