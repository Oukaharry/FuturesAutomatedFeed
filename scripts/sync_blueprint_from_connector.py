#!/usr/bin/env python3
"""Sync this repo's prop-firm blueprint to the TradeAccountConnector.

The connector's blueprint is the source of truth (more accurate). This script
re-aligns every firm's ``strategy_configs`` in
``trader_companion/prop_firm_manager.py`` to the connector's values.

DELIBERATELY EXCLUDED: ``TopStep RTP`` -- this repo intentionally keeps RTP on
TopstepX with the standard Funded-phase model, whereas the connector models it
as a Tradovate firm with a Payout-phase taxonomy. Syncing it would switch the
broker and rewrite the phase model. It is left untouched on purpose.

Behaviour:
  * Only ``strategy_configs`` values are rewritten (that is where drift lives).
  * Structural differences (name / account_sizes / trading_phases) are
    REPORTED, never auto-applied -- those mirror the RTP situation and need a
    human decision.
  * Idempotent: a firm already matching is left byte-untouched.
  * The repo's indentation (16/20/24/28 spaces) and int/float literal style
    are preserved.

Usage:
    python scripts/sync_blueprint_from_connector.py [--check] [--connector PATH]

    --check   : report drift and exit non-zero if any; do not modify files.
    --connector PATH : override the connector prop_firm_manager.py location.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys

REPO_PFM = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "trader_companion", "prop_firm_manager.py",
)
DEFAULT_CONNECTOR = (
    r"C:\Users\harry\Downloads\TradeAccountConnector-APP-main"
    r"\TradeAccountConnector-APP-main\src\prop_firm_manager.py"
)
EXCLUDE_FIRMS = {"TopStep RTP"}


def load_blueprint(path: str) -> dict:
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Attribute) and tgt.attr == "firm_blueprints":
                    return ast.literal_eval(node.value)
    raise RuntimeError(f"firm_blueprints not found in {path}")


def _fmt(v):
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, float):
        return repr(v)
    return json.dumps(v)


def render_strategy_configs(scs: dict) -> list[str]:
    S = " "
    lines = [f'{S*16}"strategy_configs": {{']
    stages = list(scs.items())
    for si, (stage, sizes) in enumerate(stages):
        lines.append(f'{S*20}"{stage}": {{')
        for sz, cfg in sizes.items():
            lines.append(f'{S*24}"{sz}": {{')
            items = list(cfg.items())
            for fi, (k, val) in enumerate(items):
                tail = "," if fi < len(items) - 1 else ""
                lines.append(f'{S*28}"{k}": {_fmt(val)}{tail}')
            lines.append(f'{S*24}}}')
        lines.append(f'{S*20}}}' + ("," if si < len(stages) - 1 else ""))
    lines.append(f'{S*16}}}')
    return lines


def splice_firm(src_lines: list[str], firm: str, scs: dict) -> list[str]:
    """Replace one firm's strategy_configs block; return new lines."""
    i_firm = next(i for i, l in enumerate(src_lines)
                  if l.strip() == f'"{firm}": {{')
    i_sc = next(i for i in range(i_firm, len(src_lines))
                if src_lines[i].strip() == '"strategy_configs": {')
    depth = 0
    i_end = None
    for i in range(i_sc, len(src_lines)):
        depth += src_lines[i].count("{") - src_lines[i].count("}")
        if depth == 0:
            i_end = i
            break
    if i_end is None:
        raise RuntimeError(f"could not brace-match strategy_configs for {firm}")
    return src_lines[:i_sc] + render_strategy_configs(scs) + src_lines[i_end + 1:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="report drift only; do not modify files")
    ap.add_argument("--connector", default=DEFAULT_CONNECTOR)
    args = ap.parse_args()

    if not os.path.exists(args.connector):
        print(f"ERROR: connector not found: {args.connector}")
        return 2

    ref = load_blueprint(args.connector)
    mine = load_blueprint(REPO_PFM)

    only_ref = sorted(set(ref) - set(mine))
    only_mine = sorted(set(mine) - set(ref))
    if only_ref:
        print(f"[WARN] firms only in connector (not synced): {only_ref}")
    if only_mine:
        print(f"[WARN] firms only in this repo: {only_mine}")

    drift, structural, synced = [], [], []
    for firm in sorted(set(ref) & set(mine)):
        if firm in EXCLUDE_FIRMS:
            continue
        for meta in ("name", "account_sizes", "trading_phases"):
            if ref[firm].get(meta) != mine[firm].get(meta):
                structural.append(
                    f"  {firm}/{meta}: connector={ref[firm].get(meta)!r} "
                    f"repo={mine[firm].get(meta)!r}")
        if ref[firm].get("strategy_configs") != mine[firm].get("strategy_configs"):
            drift.append(firm)

    if structural:
        print("[WARN] STRUCTURAL differences (NOT auto-applied -- review manually):")
        print("\n".join(structural))

    if not drift:
        print("[OK] strategy_configs already match the connector "
              f"(RTP excluded). {len(set(ref) & set(mine))} firms checked.")
        return 1 if (args.check and structural) else 0

    print(f"strategy_configs drift in: {drift}")
    if args.check:
        print("--check: not modifying files.")
        return 1

    for firm in drift:
        lines = open(REPO_PFM, encoding="utf-8").read().split("\n")
        new_lines = splice_firm(lines, firm, ref[firm]["strategy_configs"])
        open(REPO_PFM, "w", encoding="utf-8", newline="").write(
            "\n".join(new_lines))
        # integrity check after every write
        load_blueprint(REPO_PFM)
        synced.append(firm)
        print(f"  [+] synced {firm}")

    after = load_blueprint(REPO_PFM)
    remaining = [f for f in sorted(set(ref) & set(mine))
                 if f not in EXCLUDE_FIRMS
                 and ref[f].get("strategy_configs")
                 != after[f].get("strategy_configs")]
    print(f"Done. Synced {synced}. "
          f"{'Remaining drift: ' + str(remaining) if remaining else 'All non-RTP firms now match.'}")
    return 0 if not remaining else 1


if __name__ == "__main__":
    sys.exit(main())
