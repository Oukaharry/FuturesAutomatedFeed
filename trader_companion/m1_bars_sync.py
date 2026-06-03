"""
Sync MT5 M1 OHLC bars to the dashboard Postgres (PythonAnywhere).

All PlexyTrade companions share one canonical series: client_id=PLEXY, symbol=USTECH.
Any registered companion may push; email is auth only. Non-Plexy brokers are skipped.

Flow (auto on MT5 connect):
  1. Ask dashboard for last saved bar_time (GET /api/client/m1_bars/status)
  2. If gap since last bar → fetch missing range from MT5 and POST (one pass)
  3. If DB oldest is after HISTORY_START → one-time backfill paging MT5 backwards
  4. Every 60s → POST latest bar(s) (live append)

Note: stores M1 OHLC bars (not tick-by-tick). Dashboard sync uses HTTPS POST
      (same pattern as /api/client/push). Local signal cache is separate (mt5_market_feed).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_SYMBOL = "ustech"
DEFAULT_HISTORY_DAYS = 365  # legacy; backfill uses HISTORY_START_UTC
# One-time backfill floor: Jun 1 2025 UTC → live append keeps data current
HISTORY_START_UTC = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
BATCH_SIZE = 2000
PUSH_TIMEOUT = 120
STATUS_TIMEOUT = 30
CHUNK_BARS = 50000  # MT5 max per request ~100k; stay under


def is_plexy_trade_mt5() -> bool:
    """True when connected MT5 account is PlexyTrade (shared USTECH feed)."""
    try:
        import MetaTrader5 as mt5
        from trader_companion.mt5_market_feed import MT5_API_LOCK

        with MT5_API_LOCK:
            if not mt5.terminal_info():
                return False
            account = mt5.account_info()
            if account is None:
                return False
            server = (account.server or "").lower()
            company = (account.company or "").lower()
            return "plexy" in server or "plexy" in company
    except Exception:
        return False


class M1BarsDashboardSync:
    """Background sync: MT5 M1 → dashboard Postgres."""

    def __init__(
        self,
        dashboard_url: str,
        email: str,
        symbol: str = DEFAULT_SYMBOL,
        history_days: int = DEFAULT_HISTORY_DAYS,
        interval_sec: int = 60,
        log_fn: Optional[Callable[[str, str], None]] = None,
    ):
        self.dashboard_url = (dashboard_url or "").rstrip("/")
        self.email = (email or "").strip().lower()
        self.symbol_raw = symbol
        self.history_days = max(30, int(history_days))
        self.interval_sec = max(30, int(interval_sec))
        self._log_fn = log_fn
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._resolved_symbol: Optional[str] = None
        self._run_generation = 0
        self._broker_company: str = ""
        self._broker_server: str = ""

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            self._log("M1 sync already running on this instance — skip duplicate start", "WARN")
            return
        if not self.dashboard_url or not self.email:
            self._log("M1 sync skipped — dashboard URL or email missing", "WARN")
            return
        self._stop.clear()
        self._run_generation += 1
        gen = self._run_generation
        self._thread = threading.Thread(
            target=self._run,
            args=(gen,),
            name="m1-dashboard-sync",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _log(self, msg: str, level: str = "INFO") -> None:
        try:
            from trader_companion.audit_log import ensure_mt5_trading_log_handler, get_companion_logger
            ensure_mt5_trading_log_handler()
            lg = get_companion_logger("TradeOpssAI.m1")
            lvl = (level or "INFO").upper()
            if lvl == "ERROR":
                lg.error(msg)
            elif lvl in ("WARN", "WARNING"):
                lg.warning(msg)
            else:
                lg.info(msg)
        except Exception:
            logger.info("[M1Sync] %s", msg)
        if self._log_fn:
            try:
                self._log_fn(msg, level)
            except Exception:
                pass

    def _audit(self, event: str, **fields) -> None:
        try:
            from trader_companion.audit_log import audit_m1
            audit_m1(
                event,
                email=self.email,
                dashboard=self.dashboard_url,
                symbol=self._resolved_symbol or self.symbol_raw,
                **fields,
            )
        except Exception:
            pass

    def _alive(self, generation: int) -> bool:
        return (
            not self._stop.is_set()
            and generation == self._run_generation
        )

    def _run(self, generation: int) -> None:
        try:
            from trader_companion.audit_log import ensure_mt5_trading_log_handler
            log_path = ensure_mt5_trading_log_handler()
            self._audit("sync_thread_started", log_file=log_path, history_days=self.history_days, generation=generation)
            self._log(f"M1 dashboard sync starting → {self.dashboard_url} | email={self.email}")
            self._log(f"Monitor log file: {log_path}")
            self._resolved_symbol = self._resolve_symbol()
            if not self._resolved_symbol:
                self._log("Could not resolve symbol in MT5 — sync aborted", "ERROR")
                self._audit("symbol_resolve_failed", raw=self.symbol_raw)
                return

            if not self._capture_broker_info():
                self._log(
                    "M1 sync skipped — not PlexyTrade (shared USTECH feed is Plexy-only)",
                    "WARN",
                )
                self._audit("sync_skipped", reason="non_plexy_broker")
                return

            self._audit("symbol_resolved", raw=self.symbol_raw, resolved=self._resolved_symbol)

            server_newest = self._fetch_server_newest()
            stats = self._fetch_server_status()
            self._log(
                f"Dashboard DB: count={stats.get('count', 0)} "
                f"oldest={stats.get('oldest')} newest={stats.get('newest')} "
                f"| MT5 symbol={self._resolved_symbol}"
            )
            self._audit(
                "server_status",
                db_count=stats.get("count"),
                db_oldest=stats.get("oldest"),
                db_newest=stats.get("newest"),
            )

            if not self._alive(generation):
                return

            # Gap fill: bars newer than last saved (single fetch — no paging loop)
            if server_newest:
                self._audit("gap_fill_start", after_ts=server_newest)
                n = self._gap_fill_since(int(server_newest), generation)
                self._audit("gap_fill_done", bars_pushed=n)

            if not self._alive(generation):
                return

            # Fill holes inside the span (e.g. missing May between April and June)
            self._fill_internal_gaps(generation)

            if not self._alive(generation):
                return

            # One-time backfill: Jun 1 2025 UTC through existing oldest bar (then live keeps current)
            target_start = HISTORY_START_UTC
            target_ts = int(target_start.timestamp())
            target_label = target_start.strftime("%Y-%m-%d")
            stats = self._fetch_server_status()
            oldest = stats.get("oldest")
            if oldest is None or int(oldest) > target_ts:
                if self._alive(generation):
                    self._log(
                        f"One-time backfill toward {target_label} UTC "
                        f"(DB oldest={oldest}) …"
                    )
                    self._audit("backfill_start", target_date=target_label, db_oldest=oldest)
                    self._backfill_to_date(target_start, generation)
                    stats_after = self._fetch_server_status()
                    self._log(
                        f"Backfill done — DB has {stats_after.get('count', 0)} bars "
                        f"(oldest={stats_after.get('oldest')}, newest={stats_after.get('newest')})"
                    )
                    self._audit(
                        "backfill_done",
                        db_count=stats_after.get("count"),
                        db_oldest=stats_after.get("oldest"),
                        db_newest=stats_after.get("newest"),
                    )
            else:
                self._log(
                    f"History OK from {target_label} "
                    f"({stats.get('count', 0)} bars — backfill not needed)"
                )
                self._audit("backfill_skipped", db_count=stats.get("count"), db_oldest=oldest)

            if not self._alive(generation):
                return

            # Live loop
            self._log(f"Live M1 append every {self.interval_sec}s → dashboard (POST /api/client/m1_bars)")
            self._audit("live_loop_start", interval_sec=self.interval_sec, generation=generation)
            live_cycles = 0
            while self._alive(generation):
                pushed = self._push_latest_bars(phase="live", generation=generation)
                live_cycles += 1
                if live_cycles <= 3 or live_cycles % 10 == 0:
                    self._audit("live_tick", cycle=live_cycles, bars_pushed=pushed)
                self._stop.wait(self.interval_sec)
        except Exception as exc:
            self._log(f"M1 sync error: {exc}", "ERROR")
            self._audit("sync_error", error=str(exc))
            logger.exception("[M1Sync] run failed")

    def _capture_broker_info(self) -> bool:
        """Read MT5 account broker; return False if not PlexyTrade."""
        try:
            import MetaTrader5 as mt5
            from trader_companion.mt5_market_feed import MT5_API_LOCK

            with MT5_API_LOCK:
                account = mt5.account_info()
                if account is None:
                    return False
                self._broker_server = (account.server or "").strip()
                self._broker_company = (account.company or "").strip()
        except Exception:
            return False
        blob = f"{self._broker_server} {self._broker_company}".lower()
        return "plexy" in blob

    def _resolve_symbol(self) -> Optional[str]:
        from trader_companion.mt5_market_feed import MT5_API_LOCK, resolve_mt5_symbol

        with MT5_API_LOCK:
            return resolve_mt5_symbol(self.symbol_raw)

    def _fetch_server_status(self) -> Dict[str, Any]:
        import requests

        sym = self._resolved_symbol or self.symbol_raw
        try:
            r = requests.get(
                f"{self.dashboard_url}/api/client/m1_bars/status",
                params={"email": self.email, "symbol": sym},
                timeout=STATUS_TIMEOUT,
            )
            if r.status_code == 200:
                data = r.json() or {}
                self._audit("status_ok", **{k: data.get(k) for k in ("count", "oldest", "newest", "client_id")})
                return data
            self._log(f"Status HTTP {r.status_code}: {r.text[:200]}", "WARN")
            self._audit("status_http_error", status=r.status_code)
        except Exception as exc:
            self._log(f"Status check failed: {exc}", "WARN")
            self._audit("status_error", error=str(exc))
        return {}

    def _fetch_server_newest(self) -> Optional[int]:
        return self._fetch_server_status().get("newest")

    def _push_bars(
        self,
        bars: List[Dict[str, Any]],
        phase: str,
        generation: Optional[int] = None,
        min_bar_time: Optional[int] = None,
    ) -> int:
        if not bars:
            return 0
        import requests

        sym = self._resolved_symbol or self.symbol_raw
        total = 0
        last_db_newest = min_bar_time
        payload_base = {
            "email": self.email,
            "symbol": sym,
            "broker": self._broker_company,
            "mt5_server": self._broker_server,
        }
        for i in range(0, len(bars), BATCH_SIZE):
            if self._stop.is_set():
                break
            if generation is not None and generation != self._run_generation:
                break
            chunk = bars[i : i + BATCH_SIZE]
            if min_bar_time is not None:
                chunk = [b for b in chunk if int(b["time"]) > int(min_bar_time)]
                if not chunk:
                    continue
            try:
                r = requests.post(
                    f"{self.dashboard_url}/api/client/m1_bars",
                    json={
                        **payload_base,
                        "bars": chunk,
                        "phase": phase,
                    },
                    headers={"Content-Type": "application/json"},
                    timeout=PUSH_TIMEOUT,
                )
                if r.status_code == 429:
                    self._log(f"Rate limited (429) — waiting 3s before retry ({phase})", "WARN")
                    time.sleep(3)
                    r = requests.post(
                        f"{self.dashboard_url}/api/client/m1_bars",
                        json={
                            **payload_base,
                            "bars": chunk,
                            "phase": phase,
                        },
                        headers={"Content-Type": "application/json"},
                        timeout=PUSH_TIMEOUT,
                    )
                resp = r.json() or {}
                if r.status_code == 200 and resp.get("status") == "skipped":
                    self._log(
                        f"Dashboard skipped M1 push ({phase}) — {resp.get('message', 'non-Plexy')}",
                        "WARN",
                    )
                    self._audit("push_skipped", phase=phase, reason=resp.get("message"))
                    return total
                if r.status_code == 200 and resp.get("status") == "success":
                    written = int(resp.get("written") or len(chunk))
                    total += written
                    db_newest = resp.get("newest")
                    db_count = resp.get("count")
                    if phase == "gap" and last_db_newest is not None and db_newest is not None:
                        if int(db_newest) <= int(last_db_newest):
                            self._log(
                                f"Gap push made no DB progress (newest still {db_newest}) — stopping",
                                "WARN",
                            )
                            self._audit(
                                "gap_fill_stalled",
                                db_newest=db_newest,
                                batch=len(chunk),
                            )
                            return total
                        last_db_newest = int(db_newest)
                        min_bar_time = last_db_newest
                    if phase == "live":
                        self._log(
                            f"Live push — DB total={resp.get('count')} newest={db_newest}"
                        )
                    elif i == 0 or i + BATCH_SIZE >= len(bars):
                        self._log(
                            f"Pushed {written}/{len(chunk)} bars ({phase}) — "
                            f"DB total={resp.get('count')} newest={db_newest}"
                        )
                    self._audit(
                        "push_ok",
                        phase=phase,
                        batch=len(chunk),
                        written=written,
                        db_count=resp.get("count"),
                        db_newest=db_newest,
                    )
                else:
                    self._log(f"Push failed HTTP {r.status_code}: {r.text[:200]}", "WARN")
                    self._audit("push_http_error", phase=phase, status=r.status_code, body=r.text[:300])
            except Exception as exc:
                self._log(f"Push error: {exc}", "WARN")
                self._audit("push_error", phase=phase, error=str(exc))
                break
        return total

    def _rates_to_bars(self, rates) -> List[Dict[str, Any]]:
        if rates is None or len(rates) == 0:
            return []
        out = []
        for r in rates:
            out.append({
                "time": int(r["time"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "tick_volume": int(r["tick_volume"]),
            })
        return out

    def _fetch_rates_from_pos(self, count: int):
        import MetaTrader5 as mt5
        from trader_companion.mt5_market_feed import MT5_API_LOCK

        sym = self._resolved_symbol
        if not sym:
            return None
        with MT5_API_LOCK:
            if not mt5.terminal_info():
                return None
            mt5.symbol_select(sym, True)
            try:
                from trader_companion.signals.price_data import copy_rates_from_pos_raw
                return copy_rates_from_pos_raw(sym, mt5.TIMEFRAME_M1, 0, count)
            except ImportError:
                return mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, count)

    def _fetch_rates_from(self, date_from: datetime, count: int):
        import MetaTrader5 as mt5
        from trader_companion.mt5_market_feed import MT5_API_LOCK

        sym = self._resolved_symbol
        if not sym:
            return None
        # MT5 expects naive datetime in terminal timezone
        dt = date_from.replace(tzinfo=None) if date_from.tzinfo else date_from
        with MT5_API_LOCK:
            if not mt5.terminal_info():
                return None
            mt5.symbol_select(sym, True)
            return mt5.copy_rates_from(sym, mt5.TIMEFRAME_M1, dt, count)

    def _fetch_rates_range(self, date_from: datetime, date_to: datetime):
        import MetaTrader5 as mt5
        from trader_companion.mt5_market_feed import MT5_API_LOCK

        sym = self._resolved_symbol
        if not sym:
            return None
        dt_from = date_from.replace(tzinfo=None) if date_from.tzinfo else date_from
        dt_to = date_to.replace(tzinfo=None) if date_to.tzinfo else date_to
        with MT5_API_LOCK:
            if not mt5.terminal_info():
                return None
            mt5.symbol_select(sym, True)
            return mt5.copy_rates_range(sym, mt5.TIMEFRAME_M1, dt_from, dt_to)

    def _fill_internal_gaps(self, generation: int) -> None:
        """
        If DB has fewer bars than the oldest→newest span suggests, pull missing
        ranges from MT5 (fixes April→June holes / missing May).
        """
        stats = self._fetch_server_status()
        count = int(stats.get("count") or 0)
        oldest = stats.get("oldest")
        newest = stats.get("newest")
        if not oldest or not newest or count < 100:
            return

        span_minutes = max(1, (int(newest) - int(oldest)) // 60)
        expected = max(int(span_minutes * 0.55), 1000)
        if count >= expected * 0.85:
            return

        self._log(
            f"Internal gap fill — {count} bars vs ~{expected} expected "
            f"({span_minutes} min span); fetching from MT5 in 14-day chunks"
        )
        self._audit(
            "internal_gap_start",
            db_count=count,
            expected=expected,
            span_minutes=span_minutes,
        )

        cursor = datetime.fromtimestamp(int(oldest), tz=timezone.utc)
        end = datetime.fromtimestamp(int(newest), tz=timezone.utc)
        chunk_days = 14
        pages = 0
        while cursor < end and self._alive(generation) and pages < 80:
            chunk_end = min(cursor + timedelta(days=chunk_days), end)
            rates = self._fetch_rates_range(cursor, chunk_end)
            if rates is not None and len(rates) > 0:
                bars = self._rates_to_bars(rates)
                if bars:
                    self._push_bars(bars, "backfill", generation=generation)
                    pages += 1
                    if pages == 1 or pages % 5 == 0:
                        self._log(
                            f"Internal gap chunk {pages}: {len(bars)} bar(s) "
                            f"({cursor.date()} → {chunk_end.date()})"
                        )
            cursor = chunk_end
            time.sleep(0.12)

        stats_after = self._fetch_server_status()
        self._log(
            f"Internal gap fill done — DB has {stats_after.get('count', 0)} bars "
            f"(oldest={stats_after.get('oldest')}, newest={stats_after.get('newest')})"
        )
        self._audit(
            "internal_gap_done",
            db_count=stats_after.get("count"),
            db_oldest=stats_after.get("oldest"),
            db_newest=stats_after.get("newest"),
            chunks=pages,
        )

    def _gap_fill_since(self, after_ts: int, generation: int) -> int:
        """
        Push bars with bar_time strictly greater than after_ts.
        Uses copy_rates_from_pos (recent tail) — one pass, no paging loop.
        """
        now_ts = int(datetime.now(timezone.utc).timestamp())
        if after_ts >= now_ts - 120:
            self._log("Gap fill skipped — DB is current (within ~2 min of now)")
            self._audit("gap_fill_skipped", after_ts=after_ts, reason="current")
            return 0

        gap_minutes = max(10, (now_ts - after_ts) // 60 + 10)
        fetch_count = min(gap_minutes + 5, 80000)
        after_dt = datetime.fromtimestamp(after_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._log(
            f"Gap fill: fetch last {fetch_count} M1 bars, push only bar_time > {after_ts} ({after_dt})"
        )

        if not self._alive(generation):
            return 0

        rates = self._fetch_rates_from_pos(fetch_count)
        bars = self._rates_to_bars(rates)
        new_bars = sorted(
            (b for b in bars if int(b["time"]) > int(after_ts)),
            key=lambda b: int(b["time"]),
        )
        if not new_bars:
            self._log("Gap fill: no bars newer than DB newest in MT5 fetch", "WARN")
            self._audit("gap_fill_empty", after_ts=after_ts)
            return 0

        self._log(
            f"Gap fill: {len(new_bars)} bar(s) to push "
            f"(t={new_bars[0]['time']} … t={new_bars[-1]['time']})"
        )
        pushed = self._push_bars(new_bars, "gap", generation=generation, min_bar_time=after_ts)
        stats = self._fetch_server_status()
        new_newest = stats.get("newest")
        self._log(
            f"Gap fill done — wrote {pushed} bar(s), "
            f"DB count={stats.get('count')} newest={new_newest}"
        )
        if pushed and new_newest is not None and int(new_newest) <= int(after_ts):
            self._log(
                "Gap fill finished but DB newest did not advance — check MT5 history / symbol",
                "WARN",
            )
            self._audit("gap_fill_no_progress", after_ts=after_ts, db_newest=new_newest)
        return pushed

    def _fetch_and_push_range(
        self,
        start: datetime,
        end: datetime,
        phase: str,
        min_ts: Optional[int] = None,
    ) -> int:
        """Fetch M1 bars between start and end (UTC) and push to dashboard."""
        start_ts = int(min_ts if min_ts is not None else start.timestamp())
        end_ts = int(end.timestamp())
        if start_ts >= end_ts:
            return 0

        total_pushed = 0
        cursor_ts = start_ts
        empty_streak = 0
        while cursor_ts < end_ts and not self._stop.is_set():
            cursor_dt = datetime.utcfromtimestamp(cursor_ts)
            rates = self._fetch_rates_from(cursor_dt, CHUNK_BARS)
            if rates is None or len(rates) == 0:
                empty_streak += 1
                if empty_streak >= 5:
                    break
                cursor_ts += 6 * 3600
                continue
            empty_streak = 0
            bars = [
                b for b in self._rates_to_bars(rates)
                if start_ts <= int(b["time"]) <= end_ts
            ]
            if not bars:
                break
            total_pushed += self._push_bars(bars, phase)
            next_ts = int(bars[-1]["time"]) + 60
            if next_ts <= cursor_ts:
                break
            cursor_ts = next_ts
            if len(rates) < CHUNK_BARS:
                break
            time.sleep(0.05)

        if total_pushed:
            self._log(f"Range push complete ({phase}): {total_pushed} bar(s) written")
        return total_pushed

    def _backfill_to_date(self, target_start: datetime, generation: int) -> None:
        """
        Page MT5 backwards, inserting bars older than current DB oldest down to target_start.
        Only pushes [target_start, db_oldest) — does not re-upload bars already in DB.
        """
        if not self._resolved_symbol:
            return

        target_ts = int(target_start.timestamp())
        target_label = target_start.strftime("%Y-%m-%d")
        empty_streak = 0
        pages = 0
        max_pages = 500

        while self._alive(generation) and pages < max_pages:
            stats = self._fetch_server_status()
            db_oldest = stats.get("oldest")
            if db_oldest is not None and int(db_oldest) <= target_ts:
                self._log(f"Backfill reached {target_label} (DB oldest={db_oldest})")
                return

            if db_oldest is not None:
                upper_ts = int(db_oldest) - 60
            else:
                upper_ts = int(datetime.now(timezone.utc).timestamp())

            if upper_ts <= target_ts:
                return

            fetch_from = datetime.utcfromtimestamp(upper_ts) - timedelta(days=45)
            rates = self._fetch_rates_from(fetch_from, CHUNK_BARS)
            if rates is None or len(rates) == 0:
                empty_streak += 1
                if empty_streak >= 5:
                    self._log(
                        f"Backfill stopped — MT5 has no more bars before "
                        f"{datetime.fromtimestamp(upper_ts, tz=timezone.utc).date()}",
                        "WARN",
                    )
                    return
                time.sleep(0.3)
                continue

            empty_streak = 0
            bars = [
                b for b in self._rates_to_bars(rates)
                if target_ts <= int(b["time"]) <= upper_ts
            ]
            if not bars:
                chunk_oldest = int(rates[0]["time"])
                if chunk_oldest <= target_ts:
                    self._log(f"Backfill reached {target_label}")
                    return
                empty_streak += 1
                if empty_streak >= 5:
                    self._log("Backfill stopped — no bars in target window from MT5", "WARN")
                    return
                time.sleep(0.3)
                continue

            prev_oldest = int(db_oldest) if db_oldest is not None else None
            self._push_bars(bars, "backfill", generation=generation)
            pages += 1
            if pages == 1 or pages % 5 == 0:
                self._log(
                    f"Backfill page {pages}: pushed {len(bars)} bar(s) "
                    f"(t={bars[0]['time']} … t={bars[-1]['time']})"
                )

            stats = self._fetch_server_status()
            new_oldest = stats.get("oldest")
            if prev_oldest is not None and new_oldest is not None:
                if int(new_oldest) >= prev_oldest:
                    empty_streak += 1
                    if empty_streak >= 3:
                        self._log(
                            "Backfill stalled — DB oldest did not move backward; "
                            "MT5 may not expose earlier USTECH history",
                            "WARN",
                        )
                        return
                else:
                    empty_streak = 0

            time.sleep(0.15)

    def _push_latest_bars(self, phase: str = "live", generation: Optional[int] = None) -> int:
        if generation is not None and not self._alive(generation):
            return 0
        rates = self._fetch_rates_from_pos(5)
        bars = self._rates_to_bars(rates)
        if not bars:
            self._audit("fetch_empty", phase=phase)
            return 0
        chunk = bars[-2:]
        last = chunk[-1]
        pushed = self._push_bars(chunk, phase, generation=generation)
        if pushed and phase == "live":
            self._log(
                f"Live bar t={last['time']} close={last['close']:.2f} "
                f"(pushed {pushed} bar(s) to dashboard)"
            )
        return pushed


_sync_singleton: Optional[M1BarsDashboardSync] = None
_sync_lock = threading.Lock()


def is_m1_dashboard_sync_running() -> bool:
    with _sync_lock:
        return bool(
            _sync_singleton
            and _sync_singleton._thread
            and _sync_singleton._thread.is_alive()
        )


def start_m1_dashboard_sync(
    dashboard_url: str,
    email: str,
    symbol: str = DEFAULT_SYMBOL,
    log_fn: Optional[Callable[[str, str], None]] = None,
    *,
    force: bool = False,
) -> M1BarsDashboardSync:
    global _sync_singleton
    with _sync_lock:
        if (
            not force
            and _sync_singleton
            and _sync_singleton._thread
            and _sync_singleton._thread.is_alive()
            and _sync_singleton.dashboard_url == (dashboard_url or "").rstrip("/")
            and _sync_singleton.email == (email or "").strip().lower()
        ):
            return _sync_singleton

        old = _sync_singleton
        if old and old._thread and old._thread.is_alive():
            old.stop()
            old._thread.join(timeout=15.0)
            if old._thread.is_alive():
                logger.warning("[M1Sync] previous sync thread did not stop within 15s")

        _sync_singleton = M1BarsDashboardSync(
            dashboard_url=dashboard_url,
            email=email,
            symbol=symbol,
            log_fn=log_fn,
        )
        _sync_singleton.start()
        return _sync_singleton


def stop_m1_dashboard_sync() -> None:
    global _sync_singleton
    with _sync_lock:
        if _sync_singleton:
            _sync_singleton.stop()
            if _sync_singleton._thread and _sync_singleton._thread.is_alive():
                _sync_singleton._thread.join(timeout=10.0)
            _sync_singleton = None
