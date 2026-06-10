"""
MT5 M1 market feed for Trader Companion signals.

- Polls MT5 copy_rates_from_pos (M1) every 60 seconds for subscribed symbols.
- Uses whichever MT5 terminal is connected on this machine (any logged-in client).
- Keeps an in-memory cache for signals (no WebSocket — dashboard sync uses HTTPS).

Threading model (important):
  ALL MetaTrader5 API calls happen on ONE dedicated poll thread.
  MetaTrader5's IPC is not safe for concurrent use, so this single-owner design
  is what makes the feed reliable.

Signals should read bars via signals.price_data.copy_rates_from_pos_cached().
Dashboard Postgres sync is handled separately by m1_bars_sync.py.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_SEC = 60
# 2 days of M1 bars. Indicators need ~110, but deeper consumers (ML feature
# warmup, research) ask for more — keeping the cache deep means those reads
# are served instantly instead of falling through to the MT5 API. Memory cost
# is trivial (~250 KB per symbol); the poll is a local IPC call, not network.
DEFAULT_BAR_COUNT = 2880
DEFAULT_SYMBOL_CANDIDATES = (
    "USTECH",   # PlexyTrade API name (history UI may show "ustech")
    "USTEC",
    "US100",
    "NAS100",
    "NQ100",
    "SPX500",
    "EURUSD",
)

_feed_singleton: Optional["MT5MarketFeed"] = None
_feed_lock = threading.Lock()
# Serialize ALL MetaTrader5 API calls (feed poll + dashboard backfill share one terminal).
MT5_API_LOCK = threading.Lock()


def _audit_feed(event: str, **fields) -> None:
    try:
        from trader_companion.audit_log import audit_m1
        audit_m1(event, **fields)
    except Exception:
        pass


def resolve_mt5_symbol(name: str) -> Optional[str]:
    """
    Map a user/broker alias to the exact MT5 symbol name (e.g. ustech -> USTECH).

    MUST only be called from the poll thread (it touches the MT5 API).
    """
    raw = str(name or "").strip()
    if not raw:
        return None
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return raw
    if not mt5.terminal_info():
        return raw

    for candidate in (raw, raw.upper(), raw.lower(), raw.capitalize()):
        if mt5.symbol_info(candidate) is not None and mt5.symbol_select(candidate, True):
            return candidate

    key = raw.lower()
    try:
        all_syms = mt5.symbols_get()
    except Exception:
        all_syms = None
    if all_syms:
        for sym in all_syms:
            if sym.name.lower() == key and mt5.symbol_select(sym.name, True):
                return sym.name

    logger.warning("[MT5Feed] Could not resolve symbol %r (%s)", raw, mt5.last_error())
    return None


def get_market_feed() -> "MT5MarketFeed":
    global _feed_singleton
    with _feed_lock:
        if _feed_singleton is None:
            _feed_singleton = MT5MarketFeed()
        return _feed_singleton


def start_mt5_market_feed(symbols=None) -> bool:
    """Start (or keep) the M1 poller after MT5 is initialized."""
    feed = get_market_feed()
    for sym in symbols or []:
        feed.queue_symbol(str(sym).strip())
    return feed.start()


def stop_mt5_market_feed() -> None:
    get_market_feed().stop()


def get_market_feed_status() -> Dict[str, Any]:
    """Diagnostics for UI / troubleshooting."""
    feed = get_market_feed()

    mt5_ready = False
    try:
        import MetaTrader5 as mt5
        mt5_ready = bool(mt5.terminal_info())
    except ImportError:
        pass

    with feed._data_lock:
        cached = {}
        for sym, e in feed._cache.items():
            rates = e.get("rates")
            cached[sym] = len(rates) if rates is not None else 0

    return {
        "running": feed.is_running,
        "mt5_ready": mt5_ready,
        "subscribed_symbols": sorted(feed._symbols),
        "cached_symbols": cached,
        "interval_sec": feed.interval_sec,
    }


def format_market_feed_status_for_user() -> str:
    """One-line status for the TradeOpssAI activity log."""
    s = get_market_feed_status()
    if not s["mt5_ready"]:
        return "M1 feed: not started — connect MT5 first (terminal must be open)."
    if not s["running"]:
        return "M1 feed: failed to start — check MT5 and reconnect."
    cached = s["cached_symbols"]
    if cached:
        parts = ", ".join(f"{k}({v} bars)" for k, v in cached.items())
        return f"M1 feed active — poll every {s['interval_sec']}s. Cached: {parts}."
    return f"M1 feed active — poll every {s['interval_sec']}s, fetching first bars…"


class MT5MarketFeed:
    """Background M1 poller with in-memory cache (single MT5-owner thread)."""

    def __init__(
        self,
        interval_sec: int = DEFAULT_INTERVAL_SEC,
        bar_count: int = DEFAULT_BAR_COUNT,
    ):
        self.interval_sec = max(5, int(interval_sec))
        self.bar_count = max(50, int(bar_count))

        # Resolved MT5 symbol names actively polled.
        self._symbols: Set[str] = set()
        # Raw names queued from any thread, resolved on the poll thread.
        self._pending: Set[str] = set()
        self._pending_lock = threading.Lock()

        self._cache: Dict[str, Dict[str, Any]] = {}
        self._data_lock = threading.Lock()

        self._poll_thread: Optional[threading.Thread] = None
        self._running = False
        self._refresh_now = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._running

    def queue_symbol(self, symbol: str) -> None:
        """Queue a raw symbol name to be resolved + polled by the poll thread."""
        sym = str(symbol or "").strip()
        if not sym:
            return
        with self._pending_lock:
            self._pending.add(sym)
        self._refresh_now.set()

    def start(self) -> bool:
        """Start poll loop. Returns False if MT5 unavailable."""
        try:
            import MetaTrader5 as mt5
        except ImportError:
            logger.warning("[MT5Feed] MetaTrader5 not installed")
            return False
        if not mt5.terminal_info():
            logger.warning("[MT5Feed] MT5 not initialized — connect terminal first")
            return False

        if self._running:
            self._refresh_now.set()
            return True

        try:
            from trader_companion.audit_log import ensure_mt5_trading_log_handler
            log_path = ensure_mt5_trading_log_handler()
        except Exception:
            log_path = None

        self._running = True
        self._poll_thread = threading.Thread(target=self._poll_loop, name="mt5-m1-feed", daemon=True)
        self._poll_thread.start()
        logger.info("[MT5Feed] Started M1 poll every %ss", self.interval_sec)
        _audit_feed(
            "feed_started",
            interval_sec=self.interval_sec,
            log_file=log_path,
        )
        return True

    def stop(self) -> None:
        self._running = False
        self._refresh_now.set()
        _audit_feed("feed_stopped")

    def request_refresh(self) -> None:
        self._refresh_now.set()

    def get_rates(self, symbol: str, count: int):
        """Latest cached M1 numpy rates (newest at end), or None."""
        sym = str(symbol or "").strip()
        with self._data_lock:
            entry = self._cache.get(sym)
            if not entry:
                for k, v in self._cache.items():
                    if k.lower() == sym.lower():
                        entry = v
                        break
        if not entry:
            return None
        rates = entry.get("rates")
        if rates is None or len(rates) == 0:
            return None
        need = max(1, int(count))
        return rates if len(rates) <= need else rates[-need:]

    def get_snapshot(self) -> Dict[str, Any]:
        with self._data_lock:
            symbols = {}
            for sym, entry in self._cache.items():
                rates = entry.get("rates")
                symbols[sym] = {
                    "bar_count": len(rates) if rates is not None else 0,
                    "updated_at": entry.get("updated_at"),
                    "last_bar": entry.get("last_bar"),
                }
        return {
            "type": "snapshot",
            "interval_sec": self.interval_sec,
            "timeframe": "M1",
            "symbols": symbols,
        }

    def _poll_loop(self) -> None:
        while self._running:
            try:
                self._refresh_all_symbols()
            except Exception as exc:
                logger.warning("[MT5Feed] Poll error: %s", exc)
                _audit_feed("poll_error", error=str(exc))
            self._refresh_now.clear()
            self._refresh_now.wait(timeout=self.interval_sec)

    def _drain_pending(self) -> None:
        with self._pending_lock:
            pending = list(self._pending)
            self._pending.clear()
        for raw in pending:
            resolved = resolve_mt5_symbol(raw)
            if resolved:
                self._symbols.add(resolved)
                _audit_feed("symbol_resolved", raw=raw, resolved=resolved)
            else:
                logger.warning("[MT5Feed] dropping unresolvable symbol: %r", raw)
                _audit_feed("symbol_resolve_failed", raw=raw)

    def _ensure_default_symbol(self) -> None:
        for cand in DEFAULT_SYMBOL_CANDIDATES:
            resolved = resolve_mt5_symbol(cand)
            if resolved:
                self._symbols.add(resolved)
                logger.info("[MT5Feed] auto-selected default symbol: %s", resolved)
                _audit_feed("default_symbol", resolved=resolved)
                return

    def _refresh_all_symbols(self) -> None:
        with MT5_API_LOCK:
            self._refresh_all_symbols_locked()

    def _refresh_all_symbols_locked(self) -> None:
        try:
            import MetaTrader5 as mt5
        except ImportError:
            return
        if not mt5.terminal_info():
            return

        self._drain_pending()
        if not self._symbols:
            self._ensure_default_symbol()
            if not self._symbols:
                return

        tf = mt5.TIMEFRAME_M1
        for sym in list(self._symbols):
            if not mt5.symbol_select(sym, True):
                logger.warning("[MT5Feed] symbol_select failed: %s (%s)", sym, mt5.last_error())
                _audit_feed("symbol_select_failed", symbol=sym, error=str(mt5.last_error()))
                continue
            try:
                from trader_companion.signals.price_data import copy_rates_from_pos_raw
                rates = copy_rates_from_pos_raw(sym, tf, 0, self.bar_count)
            except ImportError:
                rates = mt5.copy_rates_from_pos(sym, tf, 0, self.bar_count)
            if rates is None or len(rates) == 0:
                logger.warning("[MT5Feed] No M1 bars for %s (%s)", sym, mt5.last_error())
                _audit_feed("no_bars", symbol=sym, error=str(mt5.last_error()))
                continue

            last = rates[-1]
            last_bar = {
                "time": int(last["time"]),
                "open": float(last["open"]),
                "high": float(last["high"]),
                "low": float(last["low"]),
                "close": float(last["close"]),
                "tick_volume": int(last["tick_volume"]),
            }
            updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            with self._data_lock:
                self._cache[sym] = {"rates": rates, "updated_at": updated_at, "last_bar": last_bar}

            logger.info("[MT5Feed] %s M1 updated (%s bars, close=%.2f)", sym, len(rates), last_bar["close"])
            _audit_feed(
                "bar_updated",
                symbol=sym,
                bar_count=len(rates),
                bar_time=last_bar["time"],
                close=last_bar["close"],
            )
