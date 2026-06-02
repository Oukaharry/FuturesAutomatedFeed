"""HTML report for ML training results."""
from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


def _esc(s: Any) -> str:
    return html.escape(str(s))


def render_ml_report(
    client_id: str,
    feature_df: pd.DataFrame,
    metrics: Dict[str, Any],
    output_path: Path,
) -> None:
    wf = metrics.get("walk_forward") or {}
    ins = metrics.get("in_sample") or {}
    folds: List[dict] = metrics.get("folds") or []
    imps: List[dict] = metrics.get("feature_importances") or []

    fold_rows = ""
    for f in folds:
        cls = f.get("classification") or {}
        tr = f.get("trading_filter") or {}
        fold_rows += f"""
        <tr>
          <td>{f.get('fold')}</td>
          <td>{f.get('train_size')}</td>
          <td>{f.get('test_size')}</td>
          <td>{cls.get('accuracy', 0):.1%}</td>
          <td>{cls.get('f1', 0):.3f}</td>
          <td>{cls.get('roc_auc') if cls.get('roc_auc') is not None else '—'}</td>
          <td>${tr.get('net_pnl_taken', 0):,.0f}</td>
          <td>{tr.get('win_rate_taken', 0):.1f}%</td>
        </tr>"""

    imp_rows = ""
    for row in imps[:12]:
        imp_rows += f"<tr><td>{_esc(row.get('feature'))}</td><td>{row.get('importance', 0):.4f}</td></tr>"

    n = len(feature_df)
    wr = float((feature_df["net_pnl"] > 0).mean() * 100) if n else 0

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>ML Report — {_esc(client_id)}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 24px; }}
    h1, h2 {{ color: #a78bfa; }}
    .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 16px 20px; margin-bottom: 20px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #334155; }}
    th {{ color: #94a3b8; }}
    .muted {{ color: #64748b; font-size: 0.85rem; }}
  </style>
</head>
<body>
  <h1>Trade ML Report — {_esc(client_id)}</h1>
  <p class="muted">Win classifier · walk-forward validation · features from MT5 trade history only</p>

  <div class="card">
    <h2>Dataset</h2>
    <p>Trades: <strong>{n}</strong> · Baseline win rate: <strong>{wr:.1f}%</strong></p>
  </div>

  <div class="card">
    <h2>Walk-forward (out-of-sample)</h2>
    <p>Mean accuracy: <strong>{(wf.get('mean_accuracy') or 0):.1%}</strong> ·
       Mean F1: <strong>{(wf.get('mean_f1') or 0):.3f}</strong> ·
       Mean ROC-AUC: <strong>{wf.get('mean_roc_auc') if wf.get('mean_roc_auc') is not None else '—'}</strong></p>
    <p>Sum P/L if only taking predicted wins: <strong>${(wf.get('sum_pnl_filter') or 0):,.0f}</strong></p>
    <table>
      <thead>
        <tr><th>Fold</th><th>Train</th><th>Test</th><th>Acc</th><th>F1</th><th>AUC</th><th>P/L filter</th><th>WR filter</th></tr>
      </thead>
      <tbody>{fold_rows or '<tr><td colspan="8">Not enough data for folds</td></tr>'}</tbody>
    </table>
  </div>

  <div class="card">
    <h2>In-sample (reference only)</h2>
    <p>Accuracy: {(ins.get('accuracy') or 0):.1%} · F1: {(ins.get('f1') or 0):.3f}</p>
    <p class="muted">In-sample metrics overfit; prefer walk-forward above.</p>
  </div>

  <div class="card">
    <h2>Top feature importances</h2>
    <table>
      <thead><tr><th>Feature</th><th>Importance</th></tr></thead>
      <tbody>{imp_rows or '<tr><td colspan="2">Train random_forest for importances</td></tr>'}</tbody>
    </table>
  </div>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(doc, encoding="utf-8")
