"""
Run one ML predictions cache refresh in a separate Python process.

Used on PythonAnywhere so sklearn/pandas training does not block the uWSGI
worker (GIL + harakiri → 502-backend for the whole site).

Usage (from project root):
    python -m dashboard.ml_refresh_worker --reason scheduled
"""

from __future__ import annotations

import argparse
import os
import sys
import time


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    parser = argparse.ArgumentParser(description="ML predictions disk cache refresh")
    parser.add_argument("--reason", default="subprocess", help="scheduled | manual | subprocess")
    args = parser.parse_args()

    root = _project_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    os.chdir(root)

    os.environ.setdefault("ML_RF_N_JOBS", "1")
    # Subprocess must not open a large pool on top of uWSGI workers.
    os.environ.setdefault("ML_REFRESH_SUBPROCESS", "1")
    os.environ.setdefault("DB_POOL_MIN", "1")
    os.environ.setdefault("DB_POOL_MAX", "1")

    from dashboard.ml_predictions_service import run_refresh_once

    return run_refresh_once(reason=args.reason)


if __name__ == "__main__":
    raise SystemExit(main())
