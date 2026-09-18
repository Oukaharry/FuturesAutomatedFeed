#!/usr/bin/env bash
# Apply Aymeric profit-split DB overrides on production (after deploying code).
#
# On PythonAnywhere (example):
#   cd ~/MT5Dashboard
#   git pull origin postgres
#   # Reload web app (Web tab → Reload, or touch wsgi)
#   source ~/.virtualenvs/tradeopss/bin/activate   # adjust venv path
#   export FLASK_ENV=production
#   # DATABASE_URL must already be set in .env or the environment
#   python scripts/fix_aymeric_profit_split.py --dry-run
#   python scripts/fix_aymeric_profit_split.py
#
# Code deploy (required for correct table + header, not just this script):
#   dashboard/watermark_service.py
#   dashboard/templates/index.html

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL is not set. Add it to .env or export it before running."
  exit 1
fi

echo "=== Dry run ==="
python scripts/fix_aymeric_profit_split.py --dry-run
echo
read -r -p "Apply overrides to production DB? [y/N] " ans
if [[ "${ans,,}" != "y" && "${ans,,}" != "yes" ]]; then
  echo "Aborted."
  exit 0
fi

python scripts/fix_aymeric_profit_split.py
echo "Done. Reload the dashboard web app and hard-refresh Aymeric Profit Split tab."
