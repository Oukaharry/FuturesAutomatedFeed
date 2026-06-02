#!/usr/bin/env python3
"""CLI for TradeOpss trade-history ML pipeline."""
from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("FLASK_ENV", "development")


def _cmd_export(args: argparse.Namespace) -> None:
    from machine_learning.pipeline import export_trades

    if args.all:
        df = export_trades(all_clients=True)
    else:
        df = export_trades(all_clients=False, client_query=args.client)
    from machine_learning.config import TRADES_CSV, TRADES_PARQUET

    print(f"Exported {len(df)} trades from {df['client_id'].nunique()} client(s)")
    if TRADES_PARQUET.is_file():
        print(f"Parquet:    {TRADES_PARQUET}")
    print(f"CSV:        {TRADES_CSV}")


def _cmd_train(args: argparse.Namespace) -> None:
    from machine_learning.pipeline import train_client_model

    metrics = train_client_model(
        args.client,
        model_type=args.model,
        n_splits=args.splits,
        min_trades=args.min_trades,
        from_disk=args.from_disk,
    )
    wf = metrics.get("walk_forward") or {}
    print(f"Client:     {args.client}")
    print(f"Trades:     {metrics.get('n_trades')}")
    print(f"WF accuracy:{(wf.get('mean_accuracy') or 0):.1%}")
    print(f"WF F1:      {(wf.get('mean_f1') or 0):.3f}")
    print(f"Model:      {metrics.get('model_path')}")
    print(f"Report:     {metrics.get('report_path')}")
    if args.open and metrics.get("report_path"):
        webbrowser.open(f"file:///{metrics['report_path'].replace(os.sep, '/')}")


def _cmd_predict(args: argparse.Namespace) -> None:
    from machine_learning.pipeline import predict_client_trades
    from machine_learning.trades.loader import resolve_client_id

    client_id = resolve_client_id(args.client)
    df = predict_client_trades(args.client)
    cols = ["entry_time", "symbol", "direction", "net_pnl", "pred_win", "pred_win_prob"]
    cols = [c for c in cols if c in df.columns]
    print(df[cols].tail(args.last).to_string(index=False))
    if args.output:
        df.to_csv(args.output, index=False)
        print(f"Wrote {args.output}")


def _cmd_report(args: argparse.Namespace) -> None:
    from machine_learning.config import REPORTS_DIR, model_path_for_client
    from machine_learning.trades.loader import resolve_client_id

    client_id = resolve_client_id(args.client)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in client_id)
    report = REPORTS_DIR / f"ml_report_{safe}.html"
    if not report.is_file():
        print("No report yet. Run: python -m machine_learning.cli train", client_id)
        sys.exit(1)
    print(report)
    if args.open:
        webbrowser.open(f"file:///{report.resolve()}")


def _cmd_pipeline(args: argparse.Namespace) -> None:
    from machine_learning.pipeline import run_full_pipeline

    metrics = run_full_pipeline(args.client, model_type=args.model)
    print(json.dumps({k: metrics[k] for k in metrics if k != "folds"}, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TradeOpss ML: learn patterns from MT5 trade history in the dashboard DB",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_exp = sub.add_parser("export", help="Export round-trip trades to data/ml/")
    p_exp.add_argument("client", nargs="?", help="Client name (omit with --all)")
    p_exp.add_argument("--all", action="store_true", help="Export all clients")
    p_exp.set_defaults(func=_cmd_export)

    p_tr = sub.add_parser("train", help="Train win classifier with walk-forward validation")
    p_tr.add_argument("client", help="Client name")
    p_tr.add_argument("--model", choices=["random_forest", "logistic"], default="random_forest")
    p_tr.add_argument("--splits", type=int, default=5)
    p_tr.add_argument("--min-trades", type=int, default=30)
    p_tr.add_argument("--from-disk", action="store_true", help="Use data/ml/trades.parquet")
    p_tr.add_argument("--open", action="store_true")
    p_tr.set_defaults(func=_cmd_train)

    p_pr = sub.add_parser("predict", help="Score recent trades with saved model")
    p_pr.add_argument("client", help="Client name")
    p_pr.add_argument("--last", type=int, default=20)
    p_pr.add_argument("--output", "-o", help="Write predictions CSV")
    p_pr.set_defaults(func=_cmd_predict)

    p_rep = sub.add_parser("report", help="Open last ML HTML report")
    p_rep.add_argument("client", help="Client name")
    p_rep.add_argument("--open", action="store_true")
    p_rep.set_defaults(func=_cmd_report)

    p_full = sub.add_parser("pipeline", help="export --all then train client")
    p_full.add_argument("client", help="Client name")
    p_full.add_argument("--model", choices=["random_forest", "logistic"], default="random_forest")
    p_full.set_defaults(func=_cmd_pipeline)

    args = parser.parse_args()
    if args.command == "export" and not args.all and not args.client:
        parser.error("export requires a client name or --all")
    args.func(args)


if __name__ == "__main__":
    main()
