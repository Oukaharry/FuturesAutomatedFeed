#!/usr/bin/env bash
# Option A — from repo root:
#   bash scripts/probe_summary_tracker.sh
#
# Option B — paste PROBE_PY block below into production bash (python -c, no script file).

set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/FuturesAutomatedFeed}"
if [[ ! -d "$APP_DIR" ]]; then
  APP_DIR="/home/$(whoami)/FuturesAutomatedFeed"
fi
if [[ ! -d "$APP_DIR" ]]; then
  echo "Set APP_DIR to your repo root, e.g.: export APP_DIR=/var/www/tradeopss"
  exit 1
fi

cd "$APP_DIR"
export PYTHONPATH="$APP_DIR${PYTHONPATH:+:$PYTHONPATH}"
if [[ -f .env ]]; then set -a; source .env; set +a; fi

echo "Running probe from: $APP_DIR"
python3 scripts/probe_summary_tracker.py
