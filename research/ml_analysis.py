"""ML timing & phase analysis (book-style: features, classifier, walk-forward)."""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from research.eat_time import (
    DOW_NAMES,
    TRADING_WEEKDAY_NAMES,
    coordinated_entry_dow_name,
    format_hour_eat,
    is_trading_day_eat,
    is_trading_weekday_name,
    now_eat,
    today_eat_date_str,
    today_eat_dow_name,
    to_eat_series,
    eat_dow_name,
)


def _phase_group(code: Any) -> str:
    s = str(code or "UNK").upper()
    if s.startswith("CH"):
        return "CH"
    if s.startswith("FD"):
        return "FD"
    if s.startswith("FA"):
        return "FA"
    if s.startswith("DD"):
        return "DD"
    if s in ("UNK", "NONE", "", "NAN"):
        return "UNK"
    return s


def _infer_unk_from_position_comment(comment: str) -> Optional[str]:
    """e.g. Unknown_FD1 -> FD"""
    c = (comment or "").upper()
    m = re.search(r"UNKNOWN[_\s]*(CH|FD|FA|DD)", c)
    if m:
        return m.group(1)
    for ph in ("CH", "FD", "FA", "DD"):
        if ph in c and "UNK" not in c[:4]:
            return ph
    return None


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build ML-ready columns (no lookahead on labels for UNK prediction)."""
    from research.phase_labels import enrich_trade_labels

    out = df.copy()
    out["phase_group"] = out["phase_code"].map(_phase_group)
    out["won"] = (out["net_pnl"] > 0).astype(int)

    for col in ("entry_time", "close_time"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")

    if "entry_time" in out.columns:
        entry_eat = to_eat_series(out["entry_time"])
        out["entry_time_eat"] = entry_eat
        out["entry_hour"] = entry_eat.dt.hour.fillna(-1).astype(int)
        out["entry_dow"] = entry_eat.dt.dayofweek.fillna(-1).astype(int)
        out["entry_dow_name"] = eat_dow_name(entry_eat)
        out["trade_date"] = entry_eat.dt.strftime("%Y-%m-%d")
    else:
        out["entry_hour"] = -1
        out["entry_dow"] = -1
        out["entry_dow_name"] = "?"
    out["holding_min"] = (
        (out["close_time"] - out["entry_time"]).dt.total_seconds() / 60.0
    ).fillna(0)

    open_px = out["open_price"].fillna(0).astype(float)
    close_px = out["close_price"].fillna(0).astype(float)
    sl = out["sl"].fillna(0).astype(float)
    tp = out["tp"].fillna(0).astype(float)

    out["price_move"] = close_px - open_px
    out["price_move_pct"] = np.where(open_px > 0, (close_px - open_px) / open_px * 100.0, 0.0)

    # TP/SL distances in points (when set on MT5 position)
    out["sl_dist"] = np.where((sl > 0) & (open_px > 0), np.abs(open_px - sl), 0.0)
    out["tp_dist"] = np.where((tp > 0) & (open_px > 0), np.abs(tp - open_px), 0.0)
    out["rr_ratio"] = np.where(out["sl_dist"] > 0, out["tp_dist"] / out["sl_dist"], 0.0)

    # Outcome-based proxy when sl/tp missing (Inglese-style risk geometry)
    out["realized_move"] = np.abs(out["price_move"])
    out["pseudo_sl"] = np.where(out["net_pnl"] < 0, out["realized_move"], out["sl_dist"])
    out["pseudo_tp"] = np.where(out["net_pnl"] > 0, out["realized_move"], out["tp_dist"])

    if "position_comment" in out.columns:
        out["unk_hint"] = out["position_comment"].map(
            lambda c: _infer_unk_from_position_comment(str(c) if pd.notna(c) else "")
        )
    else:
        out["unk_hint"] = None

    out["side_code"] = out["side"].map(lambda s: 1 if str(s).upper() == "BUY" else 0)
    return enrich_trade_labels(out)


_BASE_FEATURES = [
    "entry_hour", "entry_dow", "side_code", "volume",
    "open_price", "sl_dist", "tp_dist", "rr_ratio",
    "pseudo_sl", "pseudo_tp", "holding_min", "price_move_pct",
]


def _feature_matrix(
    df: pd.DataFrame,
    symbol_columns: Optional[List[str]] = None,
) -> Tuple[pd.DataFrame, List[str]]:
    sym_dummies = pd.get_dummies(df["symbol"].fillna("?"), prefix="sym", dtype=float)
    if symbol_columns is not None:
        sym_dummies = sym_dummies.reindex(columns=symbol_columns, fill_value=0.0)
    X = pd.concat([df[_BASE_FEATURES].fillna(0), sym_dummies], axis=1)
    return X, list(X.columns)


def _align_feature_matrix(X: pd.DataFrame, feat_names: List[str]) -> pd.DataFrame:
    """Exact training columns only (ignore unseen symbols at predict time)."""
    names = list(feat_names)
    out = pd.DataFrame(0.0, index=X.index, columns=names)
    for col in X.columns:
        if col in out.columns:
            out[col] = X[col].values
    return out


def _model_feature_names(ml: Dict[str, Any], clf: Any) -> List[str]:
    """Must match columns used at fit time (not a wider symbol set from full history)."""
    if clf is not None:
        fitted = getattr(clf, "feature_names_in_", None)
        if fitted is not None and len(fitted):
            return list(fitted)
    return list(ml.get("feature_names") or [])


def _predict_aligned(clf: Any, Xa: pd.DataFrame, feat_names: List[str]):
    """DataFrame with sklearn feature_names_in_ column order (avoids numpy warnings)."""
    fitted = getattr(clf, "feature_names_in_", None)
    if fitted is not None and len(fitted):
        names = list(fitted)
    else:
        names = list(feat_names)
    Xp = Xa.reindex(columns=names, fill_value=0.0)
    return clf.predict(Xp), clf.predict_proba(Xp)


def train_phase_classifier(
    df: pd.DataFrame,
    min_train: int = 200,
) -> Dict[str, Any]:
    """
    Train RandomForest to predict phase (CH/FD/FA/DD) from timing + TP/SL geometry.
    Evaluate on time-ordered 30% holdout; predict UNK rows.
    """
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, classification_report

    known = df[df["phase_group"].isin(["CH", "FD", "FA", "DD"])].copy()
    result: Dict[str, Any] = {"trained": False, "reason": ""}

    if len(known) < min_train:
        result["reason"] = f"Need {min_train}+ labeled trades, have {len(known)}"
        return result

    known = known.sort_values("close_time")
    split = int(len(known) * 0.7)
    train_df = known.iloc[:split]
    test_df = known.iloc[split:]

    X_train, feat_names = _feature_matrix(train_df)
    y_train = train_df["phase_group"]
    sym_cols = [c for c in feat_names if c.startswith("sym_")]
    X_test, _ = _feature_matrix(test_df, symbol_columns=sym_cols)
    X_test = X_test.reindex(columns=feat_names, fill_value=0.0)
    y_test = test_df["phase_group"]

    try:
        rf_n_jobs = int(os.environ.get("ML_RF_N_JOBS", "-1"))
    except ValueError:
        rf_n_jobs = -1

    clf = RandomForestClassifier(
        n_estimators=120,
        max_depth=12,
        min_samples_leaf=25,
        class_weight="balanced",
        random_state=42,
        n_jobs=rf_n_jobs,
    )
    clf.fit(X_train, y_train)
    pred_test = clf.predict(X_test)
    acc = accuracy_score(y_test, pred_test)

    imp = sorted(
        zip(feat_names, clf.feature_importances_),
        key=lambda x: -x[1],
    )[:12]

    unk = df[df["phase_group"] == "UNK"].copy()
    unk_pred = pd.DataFrame()
    if len(unk):
        Xu, _ = _feature_matrix(unk, symbol_columns=sym_cols)
        Xu = _align_feature_matrix(Xu, feat_names)
        pred, probs = _predict_aligned(clf, Xu, feat_names)
        unk["ml_predicted_phase"] = pred
        unk["ml_confidence"] = probs.max(axis=1)
        unk_pred = unk

    result.update({
        "trained": True,
        "accuracy_test": round(float(acc), 4),
        "train_n": len(train_df),
        "test_n": len(test_df),
        "report": classification_report(y_test, pred_test, zero_division=0),
        "feature_importance": imp,
        "feature_names": feat_names,
        "symbol_columns": sym_cols,
        "model": clf,
        "unk_predictions": unk_pred,
    })
    return result


def timing_tables_by_phase(
    df: pd.DataFrame,
    min_trades: int = 15,
) -> Dict[str, Any]:
    """Best/worst day and hour per phase (empirical + edge score)."""
    out: Dict[str, Any] = {}
    for phase in ["CH", "FD", "FA", "DD", "UNK"]:
        sub = df[df["phase_group"] == phase]
        if len(sub) < min_trades:
            continue
        if "entry_dow_name" in sub.columns:
            sub = sub[sub["entry_dow_name"].isin(TRADING_WEEKDAY_NAMES)]

        by_dow = (
            sub.groupby("entry_dow_name")
            .agg(n=("net_pnl", "count"), win_rate=("won", "mean"), avg_pnl=("net_pnl", "mean"), total_pnl=("net_pnl", "sum"))
            .reset_index()
            .rename(columns={"entry_dow_name": "bucket"})
        )
        by_dow = by_dow[by_dow["n"] >= max(5, min_trades // 3)].sort_values("avg_pnl", ascending=False)

        by_hour = (
            sub.groupby("entry_hour")
            .agg(n=("net_pnl", "count"), win_rate=("won", "mean"), avg_pnl=("net_pnl", "mean"), total_pnl=("net_pnl", "sum"))
            .reset_index()
        )
        by_hour["bucket"] = by_hour["entry_hour"].map(
            lambda h: format_hour_eat(h) if int(h) >= 0 else "—"
        )
        by_hour = by_hour[by_hour["n"] >= max(5, min_trades // 5)].sort_values("avg_pnl", ascending=False)

        by_side = (
            sub.groupby("side")
            .agg(n=("net_pnl", "count"), win_rate=("won", "mean"), avg_pnl=("net_pnl", "mean"), total_pnl=("net_pnl", "sum"))
            .reset_index()
            .rename(columns={"side": "bucket"})
        )

        best_dow = by_dow.head(3).to_dict("records") if len(by_dow) else []
        worst_dow = by_dow.tail(3).sort_values("avg_pnl").to_dict("records") if len(by_dow) else []
        best_hour = by_hour.head(5).to_dict("records") if len(by_hour) else []
        worst_hour = by_hour.tail(5).sort_values("avg_pnl").to_dict("records") if len(by_hour) else []

        out[phase] = {
            "n": len(sub),
            "by_dow": by_dow,
            "by_hour": by_hour,
            "by_side": by_side,
            "best_dow": best_dow,
            "worst_dow": worst_dow,
            "best_hours": best_hour,
            "worst_hours": worst_hour,
            "prefer_side": by_side.sort_values("avg_pnl", ascending=False).iloc[0]["bucket"]
            if len(by_side) else "?",
        }
    return out


def buy_sell_summary(df: pd.DataFrame) -> Dict[str, Any]:
    overall = (
        df.groupby("side")
        .agg(n=("net_pnl", "count"), win_rate=("won", "mean"), avg_pnl=("net_pnl", "mean"), total=("net_pnl", "sum"))
        .reset_index()
    )
    by_phase_side = (
        df.groupby(["phase_group", "side"])
        .agg(n=("net_pnl", "count"), win_rate=("won", "mean"), avg_pnl=("net_pnl", "mean"))
        .reset_index()
    )
    return {"overall": overall, "by_phase_side": by_phase_side}


def _account_side_preference(
    historical: pd.DataFrame,
    client_id: str,
    account_number: Any,
    phase: str,
) -> Tuple[str, str]:
    """Best side for a prop account from closed trades on same account + phase."""
    sub = historical[
        (historical["client_id"] == client_id)
        & (historical["account_number"] == account_number)
    ]
    if phase and phase != "UNK":
        sub = sub[sub["phase_group"] == phase]
    if sub.empty:
        sub = historical[
            (historical["client_id"] == client_id)
            & (historical["account_number"] == account_number)
        ]
    if sub.empty:
        return "BUY", "no history for account"
    by_side = (
        sub.groupby("side")
        .agg(n=("net_pnl", "count"), wr=("won", "mean"), avg=("net_pnl", "mean"))
        .reset_index()
        .sort_values(["avg", "wr"], ascending=False)
    )
    side = str(by_side.iloc[0]["side"])
    row = by_side.iloc[0]
    return side, f"historical {side} avg ${row['avg']:,.2f} (n={int(row['n'])})"


def analyze_business_rules(
    active: pd.DataFrame,
    historical: pd.DataFrame,
    timing: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Enforce: all accounts same entry day; one direction per prop-firm account.
    """
    today_dow = today_eat_dow_name()
    today_date = today_eat_date_str()
    coord_dow = coordinated_entry_dow_name()
    out: Dict[str, Any] = {
        "active_count": 0,
        "active_clients": 0,
        "active_accounts": 0,
        "same_day_ok": True,
        "active_dates": [],
        "unified_entry_date": None,
        "direction_violations": [],
        "active_phases": [],
        "recommended_dow": coord_dow,
        "best_historical_dow": None,
        "today_eat": today_date,
        "today_dow_name": today_dow,
        "timezone": "Africa/Nairobi (EAT)",
        "recommended_date_hint": "",
    }
    if active is None or active.empty:
        return out

    act = engineer_features(active)
    out["active_count"] = len(act)
    out["active_clients"] = int(act["client_id"].nunique())
    accts = act["account_number"].dropna().unique()
    out["active_accounts"] = len(accts)

    dates = sorted({str(d) for d in act["trade_date"].dropna().unique() if str(d) and str(d) != "NaT"})
    out["active_dates"] = dates
    out["same_day_ok"] = len(dates) <= 1
    if dates:
        out["unified_entry_date"] = dates[0]
    elif out["same_day_ok"]:
        out["unified_entry_date"] = today_date

    phases = sorted(act["phase_group"].dropna().unique().tolist())
    out["active_phases"] = [p for p in phases if p != "?"]

    # Portfolio best day: weighted avg P/L by DOW across active phases
    dow_scores: Dict[str, float] = {}
    dow_weights: Dict[str, float] = {}
    for ph in out["active_phases"]:
        block = timing.get(ph)
        if not block or block.get("by_dow") is None:
            continue
        by_dow = block["by_dow"]
        if isinstance(by_dow, pd.DataFrame):
            for _, r in by_dow.iterrows():
                d = str(r.get("bucket", ""))
                w = float(r.get("n", 1))
                dow_scores[d] = dow_scores.get(d, 0) + float(r.get("avg_pnl", 0)) * w
                dow_weights[d] = dow_weights.get(d, 0) + w
    best_hist_dow: Optional[str] = None
    if dow_scores:
        trading_scores = {d: s for d, s in dow_scores.items() if is_trading_weekday_name(d)}
        if trading_scores:
            best_hist_dow = max(
                trading_scores.keys(),
                key=lambda d: dow_scores[d] / max(dow_weights.get(d, 1), 1),
            )
            out["recommended_date_hint"] = f"historically strongest weekday (EAT): {best_hist_dow}"
    elif not historical.empty:
        hist = engineer_features(historical)
        by_d = (
            hist.groupby("entry_dow_name")
            .agg(avg=("net_pnl", "mean"), n=("net_pnl", "count"))
            .reset_index()
            .sort_values("avg", ascending=False)
        )
        by_d = by_d[by_d["entry_dow_name"].isin(TRADING_WEEKDAY_NAMES)]
        if len(by_d):
            best_hist_dow = str(by_d.iloc[0]["entry_dow_name"])
            out["recommended_date_hint"] = f"historically strongest weekday (EAT): {best_hist_dow}"

    out["best_historical_dow"] = best_hist_dow
    # Coordinated trading day: current EAT weekday, or Monday on weekends (no Sat/Sun trading).
    out["recommended_dow"] = coord_dow
    if not out["same_day_ok"]:
        out["recommended_date_hint"] = (
            f"Split entry days — coordinate all accounts to {coord_dow} ({today_date} EAT)."
            + (f" Historical best weekday: {best_hist_dow}." if best_hist_dow else "")
        )

    hist_en = engineer_features(historical) if not historical.empty else pd.DataFrame()
    violations = []
    for (cid, acct), grp in act.groupby(["client_id", "account_number"]):
        if acct is None or (isinstance(acct, float) and pd.isna(acct)):
            continue
        sides = set(grp["side"].dropna().unique()) - {"?"}
        if len(sides) > 1:
            phase = str(grp["phase_group"].mode().iloc[0]) if len(grp["phase_group"].mode()) else "UNK"
            rec_side, reason = _account_side_preference(hist_en, cid, acct, phase)
            ps = timing[phase].get("prefer_side") if phase in timing else None
            if ps in ("BUY", "SELL"):
                rec_side = str(ps)
                reason = f"phase {phase} historical edge → {ps}"
            violations.append(
                {
                    "client_id": cid,
                    "account_number": acct,
                    "buy_count": int((grp["side"] == "BUY").sum()),
                    "sell_count": int((grp["side"] == "SELL").sum()),
                    "recommended_side": rec_side,
                    "reason": reason,
                }
            )
    out["direction_violations"] = violations
    return out


def predict_active_positions(
    active: pd.DataFrame,
    ml: Dict[str, Any],
    timing: Dict[str, Any],
    historical: pd.DataFrame,
    business: Dict[str, Any],
    *,
    market_prediction: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """Apply phase model + market ML bias (when trained) + timing rules to open positions."""
    if active is None or active.empty:
        return pd.DataFrame()

    act = engineer_features(active)
    clf = ml.get("model")
    sym_cols = [c for c in (ml.get("feature_names") or []) if str(c).startswith("sym_")]

    if ml.get("trained") and clf is not None:
        feat_names = _model_feature_names(ml, clf)
        # Never use `sym_cols or None` — empty [] is falsy and would allow all symbol dummies
        X, _ = _feature_matrix(act, symbol_columns=sym_cols)
        Xa = _align_feature_matrix(X, feat_names)
        pred, probs = _predict_aligned(clf, Xa, feat_names)
        act["ml_predicted_phase"] = pred
        act["ml_confidence"] = probs.max(axis=1)
    else:
        act["ml_predicted_phase"] = act["phase_group"]
        act["ml_confidence"] = 0.0

    # Effective phase: parsed comment wins when known
    act["effective_phase"] = act.apply(
        lambda r: r["phase_group"]
        if r["phase_group"] in ("CH", "FD", "FA", "DD")
        else r.get("ml_predicted_phase", "UNK"),
        axis=1,
    )

    hist_en = engineer_features(historical) if not historical.empty else pd.DataFrame()
    rec_sides = []
    statuses = []
    rec_sources: List[str] = []
    rec_confidences: List[float] = []

    viol_map = {
        (v["client_id"], v["account_number"]): v["recommended_side"]
        for v in business.get("direction_violations") or []
    }

    mp = market_prediction or business.get("market_prediction") or {}
    market_bias = str(mp.get("bias") or "")
    market_conf = float(mp.get("confidence") or 0.0)
    use_market_ml = bool(mp.get("use_for_recommendations")) and market_bias in ("BUY", "SELL")

    market_statuses: List[str] = []

    for _, row in act.iterrows():
        ph = row["effective_phase"]
        block = timing.get(ph, {})
        pref = block.get("prefer_side", "?")
        cid, acct = row["client_id"], row["account_number"]
        key = (cid, acct)
        cur_side = str(row.get("side") or "?")
        try:
            profit = float(row.get("profit") or row.get("net_pnl") or 0)
        except (TypeError, ValueError):
            profit = 0.0

        rec_source = "historical"
        rec_conf = market_conf if use_market_ml else 0.0

        if key in viol_map:
            rec = viol_map[key]
            status = "FIX: mixed direction on account"
            rec_source = "violation_fix"
        elif use_market_ml:
            rec = market_bias
            status = "OK" if cur_side == str(rec) else "align direction"
            rec_source = "momentum_forecast"
        else:
            rec = str(pref) if str(pref) in ("BUY", "SELL") else cur_side
            if acct is not None and not (isinstance(acct, float) and pd.isna(acct)) and not hist_en.empty:
                rec_hist, _ = _account_side_preference(hist_en, cid, acct, ph)
                if pref == "?":
                    rec = rec_hist
            status = "OK" if cur_side == str(rec) else "align direction"

        # P/L vs recommendation: matched side losing = market against rec on this leg
        aligned = cur_side == str(rec)
        if aligned:
            if profit < 0:
                market_st = "against rec (underwater)"
            elif profit > 0:
                market_st = "with rec (winning)"
            else:
                market_st = "with rec (flat)"
        else:
            if profit < 0:
                market_st = "misaligned + losing"
            else:
                market_st = "misaligned + winning"

        rec_sides.append(rec)
        statuses.append(status)
        market_statuses.append(market_st)
        rec_sources.append(rec_source)
        rec_confidences.append(rec_conf)

    act["recommended_side"] = rec_sides
    act["rule_status"] = statuses
    act["market_status"] = market_statuses
    act["rec_source"] = rec_sources
    act["rec_confidence"] = rec_confidences
    if use_market_ml:
        act["market_bias"] = market_bias
    act["phase_group"] = act["effective_phase"]
    return act


def build_portfolio_recommendations(
    active_pred: pd.DataFrame,
    business: Dict[str, Any],
    timing: Dict[str, Any],
    *,
    market_prediction: Optional[Dict[str, Any]] = None,
    market_backtest: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    mp = market_prediction or business.get("market_prediction") or {}
    bt = market_backtest or business.get("market_backtest") or {}

    if active_pred is None or active_pred.empty:
        coord = business.get("recommended_dow") or coordinated_entry_dow_name()
        mkt_side = mp.get("bias") if mp.get("trained") else "—"
        return {
            "trading_day": coord,
            "today_eat": business.get("today_eat", today_eat_date_str()),
            "today_dow_name": business.get("today_dow_name", today_eat_dow_name()),
            "best_historical_dow": business.get("best_historical_dow") or "—",
            "market_bias": mkt_side,
            "market_confidence": mp.get("confidence"),
            "market_entry_window": mp.get("best_entry_window") or "—",
            "timezone": business.get("timezone", "Africa/Nairobi (EAT)"),
            "best_hour_window": "—",
            "portfolio_side": "—",
            "accounts_needing_fix": 0,
            "summary": (
                f"No active positions. Coordinated entry day (EAT): {coord}. "
                "Use closed-history timing below for the next Mon-Fri session."
            ),
        }

    phases = active_pred["phase_group"].dropna().unique().tolist()
    hour_scores: Dict[int, float] = {}
    for ph in phases:
        block = timing.get(ph)
        if not block:
            continue
        by_h = block.get("by_hour")
        if isinstance(by_h, pd.DataFrame):
            for _, r in by_h.iterrows():
                h = int(r["entry_hour"])
                hour_scores[h] = hour_scores.get(h, 0) + float(r.get("avg_pnl", 0))

    best_hours = sorted(hour_scores.keys(), key=lambda h: hour_scores[h], reverse=True)[:3]
    if best_hours:
        hist_window = ", ".join(format_hour_eat(h) for h in best_hours)
    else:
        hist_window = "—"

    mkt_window = (
        mp.get("expected_hold")
        or mp.get("best_entry_window")
        or (mp.get("window") or {}).get("hold_display")
        or "—"
    )
    use_mkt = bool(mp.get("use_for_recommendations")) and str(mp.get("bias") or "") in ("BUY", "SELL")
    window = mkt_window if use_mkt and mkt_window != "—" else hist_window

    if use_mkt:
        port_side = str(mp.get("bias"))
    else:
        sides = active_pred["recommended_side"].value_counts()
        port_side = sides.index[0] if len(sides) else "—"
    n_fix = int((active_pred["rule_status"].str.contains("FIX", na=False)).sum())
    n_against = 0
    if not active_pred.empty and "market_status" in active_pred.columns:
        n_against = int(
            active_pred["market_status"].str.contains("against rec", na=False).sum()
        )

    coord_day = business.get("recommended_dow") or coordinated_entry_dow_name()
    today_name = business.get("today_dow_name", today_eat_dow_name())
    weekend_note = ""
    if not is_trading_day_eat():
        weekend_note = (
            f" Calendar day is {today_name} (no EAT trading session); "
            f"coordinate new entries for {coord_day}."
        )
    return {
        "trading_day": coord_day,
        "today_eat": business.get("today_eat", today_eat_date_str()),
        "today_dow_name": today_name,
        "best_historical_dow": business.get("best_historical_dow") or "—",
        "timezone": business.get("timezone", "Africa/Nairobi (EAT)"),
        "best_hour_window": window,
        "portfolio_side": str(port_side),
        "accounts_needing_fix": n_fix,
        "underwater_on_recommendation": n_against,
        "market_bias": mp.get("bias") if mp.get("trained") else "—",
        "market_confidence": mp.get("confidence"),
        "market_entry_window": mkt_window,
        "market_backtest_hit_rate": bt.get("hit_rate_confident"),
        "rec_source": "momentum_forecast" if use_mkt else "historical",
        "forecast_hold": mkt_window,
        "forecast_entry_note": mp.get("entry_note") or (mp.get("window") or {}).get("entry_note", ""),
        "summary": (
            f"Active {len(active_pred)} legs across {active_pred['client_id'].nunique()} clients "
            f"(times in EAT). "
            f"Coordinated entry day: {coord_day} ({business.get('today_eat', '')})."
            f"{weekend_note} "
            f"Historical best weekday: {business.get('best_historical_dow') or '—'}. "
            f"Resolve {len(business.get('direction_violations') or [])} direction conflict(s); "
            f"{n_against} leg(s) underwater on recommended side."
            + (f" Momentum: {mp.get('bias')} now — expected hold {mkt_window}." if use_mkt else "")
        ),
    }


def run_full_analysis(
    df: pd.DataFrame,
    *,
    active_df: Optional[pd.DataFrame] = None,
    m1_bars: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    closed = df[df.get("is_active", False) != True] if "is_active" in df.columns else df  # noqa: E712
    if closed.empty:
        closed = df

    enriched = engineer_features(closed)
    ml = train_phase_classifier(enriched)
    # feature_names must stay the training matrix columns (16), not all-history symbols (19)
    if ml.get("trained") and not ml.get("feature_names"):
        clf = ml.get("model")
        ml["feature_names"] = _model_feature_names(ml, clf)
        ml["symbol_columns"] = [c for c in ml["feature_names"] if str(c).startswith("sym_")]

    timing = timing_tables_by_phase(enriched)
    buy_sell = buy_sell_summary(enriched)

    active = active_df if active_df is not None else pd.DataFrame()

    market_ml: Dict[str, Any] = {}
    market_prediction: Dict[str, Any] = {}
    market_backtest: Dict[str, Any] = {}
    market_model: Dict[str, Any] = {}
    if m1_bars:
        try:
            from research.prediction_ml import run_market_pipeline

            market_ml = run_market_pipeline(m1_bars, active_df=active)
            market_prediction = dict(market_ml.get("prediction") or {})
            market_backtest = dict(market_ml.get("backtest") or {})
            mdl = market_ml.get("model") or {}
            market_model = {
                k: v
                for k, v in mdl.items()
                if k != "model"
            }
        except Exception as e:
            market_prediction = {"trained": False, "reason": str(e)}
            market_backtest = {"error": str(e)}

    business = analyze_business_rules(active, enriched, timing)
    business["market_prediction"] = market_prediction
    business["market_backtest"] = market_backtest
    active_pred = predict_active_positions(
        active, ml, timing, enriched, business, market_prediction=market_prediction
    )
    portfolio_recs = build_portfolio_recommendations(
        active_pred,
        business,
        timing,
        market_prediction=market_prediction,
        market_backtest=market_backtest,
    )

    insight_tips: List[str] = []
    if business.get("active_count"):
        insight_tips.append(
            f"<strong>{business['active_count']}</strong> open positions across "
            f"<strong>{business['active_clients']}</strong> clients — predictions use live SL/TP."
        )
    if business.get("direction_violations"):
        insight_tips.append(
            f"<strong>{len(business['direction_violations'])}</strong> prop account(s) have mixed BUY+SELL; "
            "resolve before adding new legs."
        )
    if not business.get("same_day_ok") and business.get("active_dates"):
        insight_tips.append(
            f"Entry dates split: <code>{', '.join(business['active_dates'])}</code> — coordinate to one day."
        )
    uw = int((portfolio_recs or {}).get("underwater_on_recommendation", 0) or 0)
    if uw > 0:
        insight_tips.append(
            f"<strong>{uw}</strong> open leg(s) match recommended direction but float P/L is negative "
            "(market moved against the recommended side on the hedge book)."
        )
    if market_prediction.get("ready") or market_prediction.get("use_for_recommendations"):
        conf = float(market_prediction.get("confidence") or 0)
        win = (market_prediction.get("window") or {})
        range_s = market_prediction.get("best_entry_window") or win.get("range_display") or "—"
        hold_s = (
            market_prediction.get("expected_hold")
            or (market_prediction.get("window") or {}).get("hold_display")
            or "—"
        )
        mwin = market_prediction.get("momentum_window") or range_s
        insight_tips.insert(
            0,
            f"<strong>{market_prediction.get('bias')} momentum</strong> — active 15m window: "
            f"<strong>{mwin}</strong>. Expected hold: <strong>{hold_s}</strong>. "
            f"{market_prediction.get('momentum_note', '')}"
        )
    elif m1_bars and market_prediction.get("reason"):
        insight_tips.append(
            f"Market ML unavailable: {market_prediction.get('reason')} "
            "(using closed-trade historical bias for recommendations)."
        )

    from research.phase_labels import sort_for_report

    closed_sorted = sort_for_report(enriched)
    active_sorted = sort_for_report(active_pred) if not active_pred.empty else active_pred

    timing_meta = _portfolio_timing_meta()

    return {
        "df": closed_sorted,
        "ml": ml,
        "timing": timing,
        "buy_sell": buy_sell,
        "business_rules": business,
        "active_predictions": active_sorted,
        "closed_trades": closed_sorted,
        "portfolio_recommendations": portfolio_recs,
        "market_prediction": market_prediction,
        "market_backtest": market_backtest,
        "market_model": market_model,
        "market_meta": market_ml.get("meta") or {},
        "market_momentum": market_ml.get("momentum") or {},
        "market_forecast": market_ml.get("forecast") or {},
        "insight_tips": insight_tips,
        "generated_at": now_eat().strftime("%Y-%m-%d %H:%M:%S EAT"),
        "timing_meta": timing_meta,
        "timing_note": timing_meta.get("note", ""),
        "n_trades": len(enriched),
        "n_active": len(active_pred) if not active_pred.empty else 0,
    }


def _portfolio_timing_meta() -> Dict[str, Any]:
    """Summarize per-client UTC calibration used for entry-hour buckets."""
    from research.mt5_time import timing_for_client
    from research.trade_dataset import (
        _utc_correction_for_client,
        load_clients_deals,
        load_clients_identity,
    )

    deals_map = load_clients_deals()
    identity_map = load_clients_identity()
    corrections: List[int] = []
    stored = 0
    for cid, deals in deals_map.items():
        if not deals:
            continue
        ident = identity_map.get(cid, {})
        if timing_for_client(ident):
            stored += 1
        corrections.append(_utc_correction_for_client(cid, deals, ident))

    if not corrections:
        return {
            "note": (
                "Entry hours: East Africa Time (Africa/Nairobi). "
                "No deal history loaded for calibration."
            ),
        }

    uniq = sorted(set(corrections))
    meta: Dict[str, Any] = {
        "clients_with_deals": len(corrections),
        "clients_with_stored_timing": stored,
        "correction_sec_min": min(uniq),
        "correction_sec_max": max(uniq),
        "correction_hours_range": f"{min(uniq) / 3600:+.1f}h … {max(uniq) / 3600:+.1f}h",
    }
    if len(uniq) == 1 and uniq[0] == 0:
        note = (
            "Entry hours: East Africa Time (Africa/Nairobi, UTC+3). "
            "MT5 Unix timestamps align with stored deal times (no per-client skew)."
        )
    else:
        note = (
            "Entry hours: East Africa Time (Africa/Nairobi, UTC+3). "
            f"Per-client calibration applied ({meta['correction_hours_range']}). "
            "Uses MT5 TimeCurrent vs Nairobi when stored on push; otherwise inferred from deals. "
            "Re-push from TradeopssAI (MT5 connected) for best accuracy."
        )
    if stored < len(corrections):
        note += f" {stored}/{len(corrections)} clients have mt5_timing (TimeCurrent probe) from a recent push."
    meta["note"] = note
    return meta


def render_ml_html_report(
    analysis: Dict[str, Any],
    *,
    data_source_line: str = "",
    title: str = "ML Trade Timing Analysis",
) -> str:
    from research.ml_html_report import render_ml_html_report as _render

    return _render(analysis, data_source_line=data_source_line, title=title)
