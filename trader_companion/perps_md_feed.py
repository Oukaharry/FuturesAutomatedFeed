"""MyFundedPerps public market-data feed: live M1 + M5 candles over WebSocket.

No authentication — never send the trading API key to this socket. Live and
sandbox share the same feed. Mirrors TradovateMDFeed's interface
(get_rates_minutes → MT5-dtype rates) so signal code can consume either.

Subscribe to `coin` (e.g. BTCUSDT) with an explicit provider; candle prices
arrive as decimal strings keyed by openTime (ms). History is backfilled with
candles.history after each (re)connect.

Docs: https://docs.myfundedperpetuals.com/market-streaming.md
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from typing import Callable, Dict, List, Optional

from trader_companion.tradovate_md_feed import bars_to_mt5_rates

logger = logging.getLogger(__name__)

MARKET_STREAM_URL = "wss://api-stream.myfundedperpetuals.com/v1/market-data"
DEFAULT_SYMBOL = "BTCUSDT"
DEFAULT_PROVIDER = "binance"
M1_BAR_COUNT = 2880     # 2 days of M1
M5_BAR_COUNT = 21000    # training depth, same as the Tradovate feed

_INTERVAL_BY_TF = {1: "1m", 5: "5m"}
_TF_BY_INTERVAL = {v: k for k, v in _INTERVAL_BY_TF.items()}


def candle_to_bar(event: dict) -> Optional[dict]:
    """Minute bar dict (epoch-sec key fields, float prices) from a candle event."""
    try:
        return {
            "time": int(event["openTime"]) // 1000,
            "open": float(event["open"]),
            "high": float(event["high"]),
            "low": float(event["low"]),
            "close": float(event["close"]),
            "volume": float(event.get("volume") or 0),
        }
    except (KeyError, TypeError, ValueError):
        return None


class PerpsMDFeed:
    """Background WS client streaming perps candles into an in-memory bar map."""

    def __init__(self, symbol: str = DEFAULT_SYMBOL, provider: str = DEFAULT_PROVIDER,
                 log_fn: Optional[Callable[[str], None]] = None):
        self._symbol = symbol
        self._provider = provider
        self._log_fn = log_fn
        # {timeframe_minutes: {bar_open_epoch_sec: bar}}
        self._bars_by_tf: Dict[int, Dict[int, dict]] = {1: {}, 5: {}}
        self._tf_limits = {1: M1_BAR_COUNT, 5: M5_BAR_COUNT}
        self._bars_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._ws = None
        self._req_id = 0
        self.connected = False
        self.last_error: Optional[str] = None

    # ── public API (TradovateMDFeed-compatible) ─────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def symbol(self) -> str:
        return self._symbol

    def bar_count(self, timeframe_minutes: int = 1) -> int:
        with self._bars_lock:
            return len(self._bars_by_tf.get(int(timeframe_minutes)) or {})

    def get_rates_minutes(self, timeframe_minutes: int, count: int):
        """MT5-dtype rates for one of the streamed timeframes, or None."""
        with self._bars_lock:
            bars = dict(self._bars_by_tf.get(int(timeframe_minutes)) or {})
        if not bars:
            return None
        return bars_to_mt5_rates(bars, max(1, int(count)))

    def start(self) -> bool:
        if self._running:
            return True
        try:
            import websocket  # noqa: F401  (websocket-client)
        except ImportError:
            self._log("⚠ websocket-client not installed — perps market feed unavailable")
            return False
        self._running = True
        self._thread = threading.Thread(target=self._run, name="perps-md-feed",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._running = False
        try:
            if self._ws:
                self._ws.close()
        except Exception:
            pass

    # ── internals ───────────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        logger.info("[PerpsMD] %s", msg)
        if self._log_fn:
            try:
                self._log_fn(msg)
            except Exception:
                pass

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _send(self, obj: dict) -> None:
        self._ws.send(json.dumps(obj))

    def _run(self) -> None:
        import websocket
        backoff = 1.0
        while self._running:
            try:
                self._ws = websocket.create_connection(MARKET_STREAM_URL, timeout=75)
                self.connected = True
                backoff = 1.0
                self._session()
            except Exception as exc:
                self.last_error = str(exc)
                if self._running:
                    self._log(f"feed error: {exc} — reconnecting in {backoff:.0f}s")
            finally:
                self.connected = False
                try:
                    if self._ws:
                        self._ws.close()
                except Exception:
                    pass
            if not self._running:
                break
            time.sleep(backoff + random.uniform(0, backoff / 2))
            backoff = min(backoff * 2, 60)

    def _session(self) -> None:
        self._req_id = 0
        self._send({
            "op": "sub", "id": self._next_id(), "channel": "candles",
            "payload": {"symbols": [self._symbol], "providers": [self._provider],
                        "intervals": list(_INTERVAL_BY_TF.values())},
        })
        # Backfill beyond the retained replay window.
        history_ids = {}
        for tf, interval in _INTERVAL_BY_TF.items():
            rid = self._next_id()
            history_ids[rid] = tf
            self._send({
                "op": "req", "id": rid, "method": "candles.history",
                "payload": {"provider": self._provider, "symbol": self._symbol,
                            "interval": interval,
                            "limit": min(self._tf_limits[tf], 5000)},
            })
        self._log(f"subscribed candles {self._symbol}@{self._provider} (1m, 5m)")

        last_ping = time.time()
        while self._running:
            if time.time() - last_ping > 25:
                self._send({"op": "req", "id": self._next_id(), "method": "ping"})
                last_ping = time.time()
            raw = self._ws.recv()
            if not raw:
                continue
            frame = json.loads(raw)
            op = frame.get("op")
            if op == "events":
                self._ingest(frame.get("events") or [])
            elif op == "res" and frame.get("id") in history_ids:
                result = frame.get("result") or []
                self._ingest(result)
                self._log(f"history backfill: {len(result)} bars "
                          f"({_INTERVAL_BY_TF[history_ids[frame['id']]]})")
            elif op in ("sub_err", "err"):
                self._log(f"server error: {frame.get('error')}")
                if op == "sub_err":
                    raise ConnectionError(f"subscription rejected: {frame.get('error')}")
            elif op == "draining":
                raise ConnectionResetError("server draining — reconnect")

    def _ingest(self, events: List[dict]) -> None:
        new_final = {1: None, 5: None}
        with self._bars_lock:
            for event in events:
                tf = _TF_BY_INTERVAL.get(event.get("interval"))
                if tf is None:
                    continue
                bar = candle_to_bar(event)
                if not bar:
                    continue
                store = self._bars_by_tf[tf]
                store[bar["time"]] = bar
                if event.get("isFinal"):
                    new_final[tf] = bar
                limit = self._tf_limits[tf]
                if len(store) > limit + 200:
                    for t in sorted(store)[:len(store) - limit]:
                        store.pop(t, None)
        for tf, bar in new_final.items():
            if bar:
                ts = time.strftime("%H:%M:%S", time.gmtime(bar["time"]))
                self._log(f"M{tf} close {ts}Z O={bar['open']} C={bar['close']}")


_feed_singleton: Optional[PerpsMDFeed] = None


def start_perps_md_feed(symbol: str = DEFAULT_SYMBOL, provider: str = DEFAULT_PROVIDER,
                        log_fn=None) -> PerpsMDFeed:
    global _feed_singleton
    if _feed_singleton and _feed_singleton.is_running:
        return _feed_singleton
    _feed_singleton = PerpsMDFeed(symbol=symbol, provider=provider, log_fn=log_fn)
    _feed_singleton.start()
    return _feed_singleton


def get_perps_md_feed() -> Optional[PerpsMDFeed]:
    return _feed_singleton
