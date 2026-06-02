#!/usr/bin/env python3
"""Thin wrapper: export all client trades for ML (see machine_learning package)."""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from machine_learning.cli import main

if __name__ == "__main__":
    sys.argv = [sys.argv[0], "export", "--all"] + sys.argv[1:]
    main()
