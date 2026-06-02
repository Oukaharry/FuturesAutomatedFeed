# TradeOpss Machine Learning

Learn patterns from **MT5 trade history** stored in `clients_data.deals` (same round-trip logic as `scripts/trade_history_analysis.py`).

## Setup

```bash
pip install -r requirements-ml.txt
```

Set `DATABASE_URL` (or use local Postgres defaults from the dashboard).

## Commands (project root)

```bash
# Export all clients → data/ml/trades.parquet
python -m machine_learning.cli export --all

# Train win classifier for one client (walk-forward + HTML report)
python -m machine_learning.cli train Aaron --open

# Full pipeline: export if missing, then train
python -m machine_learning.cli pipeline Aaron

# Score recent trades
python -m machine_learning.cli predict Aaron --last 15
```

Artifacts:

| Path | Description |
|------|-------------|
| `data/ml/trades.parquet` | All clients, trade-level rows |
| `data/ml/models/{client}_win_classifier.joblib` | Saved model |
| `reports/ml/ml_report_{client}.html` | Metrics & fold table |

## Methodology

- **Unit:** one closed round-trip trade (grouped by `position_id`)
- **Label:** `win = 1` if `net_pnl > 0`
- **Features:** hour, weekday, symbol, direction, volume, hold time, rolling win rate / PnL (prior trades only — no leakage)
- **Validation:** walk-forward (train on past, test on future chunks)

Need **≥30 trades** per client to train by default.

## Package layout

```
machine_learning/
  trades/       # load deals, build round-trips
  features/     # engineering
  evaluation/   # walk-forward, metrics
  models/       # train / predict
  pipeline.py   # orchestration
  cli.py
```

Optional: open `notebooks/trade_ml_walkforward.ipynb` for an interactive walkthrough.
