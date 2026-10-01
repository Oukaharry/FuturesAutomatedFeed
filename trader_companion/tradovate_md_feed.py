"""
Tradovate market-data feed — MT5-free M1 bars for the AI.

Streams 1-minute NQ bars from Tradovate's market-data WebSocket
(wss://md[-demo].tradovateapi.com/v1/websocket) using the bearer token the
logged-in Tradovate web session already holds. Bars are injected into the
MT5MarketFeed cache under the USTECH alias, so every indicator and the ML
ensemble read them through the existing cache path with zero changes.

Why this exists:
- Removes the hard dependency on a (shared) MT5 terminal for ML decisions.
- Trains/scored on the *actual traded contract* (CME NQ), not a CFD proxy.
- Pure Python (websocket-client) — runs anywhere, including macOS.

Protocol notes (SockJS-flavored):
- Server frames: 'o' open, 'h' heartbeat, 'a<json-array>' data, 'c' close.
- Client frames: "endpoint\\nrequest_id\\nquery\\nbody".
- Client must answer heartbeats with "[]" (any frame within ~2.5 s works).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Matches the MetaTrader5 copy_rates_from_pos structured dtype, so cached
# consumers cannot tell these bars apart from MT5 ones.
MT5_RATES_DTYPE = np.dtype([
    ("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"),
    ("close", "<f8"), ("tick_volume", "<u8"), ("spread", "<i4"),
    ("real_volume", "<u8"),
])

DEFAULT_BAR_COUNT = 2880          # 2 days of M1, same depth as the MT5 feed
TRAIN_M5_BAR_COUNT = 21000        # ~73 days of M5 — ML training depth
CACHE_ALIASES = ("USTECH", "NQ")  # indicators ask for USTECH; NQ for clarity
_QUARTER_MONTHS = (3, 6, 9, 12)
_MONTH_CODES = {3: "H", 6: "M", 9: "U", 12: "Z"}
ROLL_DAYS_BEFORE_EXPIRY = 7


def _third_friday(year: int, month: int) -> datetime:
    d = datetime(year, month, 1, tzinfo=timezone.utc)
    # weekday(): Monday=0 ... Friday=4
    first_friday = 1 + (4 - d.weekday()) % 7
    return datetime(year, month, first_friday + 14, tzinfo=timezone.utc)


def front_quarter_symbol(root: str = "NQ", now: Optional[datetime] = None) -> str:
    """Front quarterly contract in Tradovate's single-digit-year style (NQZ6).

    Rolls to the next quarter ROLL_DAYS_BEFORE_EXPIRY days before the third
    Friday of the contract month — early enough that we always stream the
    liquid contract.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    year, month = now.year, now.month
    for _ in range(8):
        quarter = next((m for m in _QUARTER_MONTHS if m >= month), None)
        if quarter is None:
            year, month = year + 1, 1
            continue
        expiry = _third_friday(year, quarter)
        if (expiry - now).total_seconds() > ROLL_DAYS_BEFORE_EXPIRY * 86400:
            return f"{root}{_MONTH_CODES[quarter]}{year % 10}"
        month = quarter + 1
        if month > 12:
            year, month = year + 1, 1
    return f"{root}Z{year % 10}"  # unreachable in practice


def parse_chart_bars_grouped(event: dict) -> Dict[int, List[dict]]:
    """Normalized bars per chart id from one 'chart' event.

    Tradovate sends {"charts": [{"id":.., "bars":[{"timestamp": ISO8601,
    "open":..,"high":..,"low":..,"close":..,"upVolume":..,"downVolume":..}]}]}.
    End-of-history packets carry "eoh": true and no bars.
    """
    out: Dict[int, List[dict]] = {}
    for chart in (event or {}).get("charts") or []:
        chart_id = chart.get("id")
        for bar in chart.get("bars") or []:
            ts = bar.get("timestamp")
            if ts is None or bar.get("close") is None:
                continue
            try:
                stamp = str(ts).replace("Z", "+00:00")
                epoch = int(datetime.fromisoformat(stamp).timestamp())
            except (ValueError, TypeError):
                continue
            epoch -= epoch % 60  # bar open time, minute-aligned
            out.setdefault(chart_id, []).append({
                "time": epoch,
                "open": float(bar.get("open", bar["close"])),
                "high": float(bar.get("high", bar["close"])),
                "low": float(bar.get("low", bar["close"])),
                "close": float(bar["close"]),
                "volume": int((bar.get("upVolume") or 0) + (bar.get("downVolume") or 0)),
            })
    return out


def parse_chart_bars(event: dict) -> List[dict]:
    """Flat bar list from one 'chart' event (all charts merged)."""
    out: List[dict] = []
    for bars in parse_chart_bars_grouped(event).values():
        out.extend(bars)
    return out


def bars_to_mt5_rates(bars_by_time: Dict[int, dict], limit: int = DEFAULT_BAR_COUNT):
    """Sorted numpy structured array (MT5 dtype) from the minute-bar map."""
    if not bars_by_time:
        return None
    times = sorted(bars_by_time)[-limit:]
    rates = np.zeros(len(times), dtype=MT5_RATES_DTYPE)
    for i, t in enumerate(times):
        b = bars_by_time[t]
        rates[i] = (t, b["open"], b["high"], b["low"], b["close"], b["volume"], 0, b["volume"])
    return rates


class TradovateMDFeed:
    """Background WS client streaming M1 bars into the shared market cache."""

    def __init__(self, token_provider: Callable[[], Optional[Tuple[str, str]]],
                 symbol: Optional[str] = None, bar_count: int = DEFAULT_BAR_COUNT,
                 log_fn: Optional[Callable[[str], None]] = None):
        self._token_provider = token_provider
        self._symbol = symbol  # None → front quarter resolved at (re)connect
        self._bar_count = int(bar_count)
        self._log_fn = log_fn
        # {timeframe_minutes: {bar_open_epoch: bar}}
        self._bars_by_tf: Dict[int, Dict[int, dict]] = {1: {}, 5: {}}
        self._tf_limits = {1: self._bar_count, 5: TRAIN_M5_BAR_COUNT}
        self._chart_tf: Dict[int, int] = {}  # server chart id → timeframe
        self._bars_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._ws = None
        self._req_id = 0
        self.last_error: Optional[str] = None
        self.connected = False

    # ── public API ──────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

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
            self._log("⚠ websocket-client not installed — Tradovate data feed unavailable")
            return False
        self._running = True
        self._thread = threading.Thread(target=self._run, name="tradovate-md-feed", daemon=True)
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
        logger.info("[TradovateMD] %s", msg)
        if self._log_fn:
            try:
                self._log_fn(msg)
            except Exception:
                pass

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _send(self, endpoint: str, body=None, query: str = "") -> int:
        rid = self._next_id()
        frame = f"{endpoint}\n{rid}\n{query}\n"
        if isinstance(body, str):
            frame += body  # raw body (authorize token)
        elif body is not None:
            frame += json.dumps(body)
        self._ws.send(frame)
        return rid

    def _md_access_token(self, token: str, env: str) -> str:
        """The md host rejects web-session tokens; renew returns the md one."""
        try:
            import requests
            host = "live" if env == "live" else "demo"
            r = requests.get(
                f"https://{host}.tradovateapi.com/v1/auth/renewaccesstoken",
                headers={"Authorization": f"Bearer {token}"}, timeout=20)
            md = (r.json() or {}).get("mdAccessToken")
            if md:
                return md
        except Exception as exc:
            self.last_error = f"renewaccesstoken: {exc}"
        return token

    def _run(self) -> None:
        import websocket
        backoff = 5
        while self._running:
            creds = None
            try:
                creds = self._token_provider()
            except Exception as exc:
                self.last_error = f"token provider: {exc}"
            if not creds or not creds[0]:
                time.sleep(15)
                continue
            token, env = creds[0], (creds[1] or "demo").lower()
            md_token = self._md_access_token(token, env)
            host = "md.tradovateapi.com" if env == "live" else "md-demo.tradovateapi.com"
            symbol = self._symbol or front_quarter_symbol("NQ")
            try:
                self._ws = websocket.create_connection(
                    f"wss://{host}/v1/websocket", timeout=30)
                self._session(md_token, symbol)
                backoff = 5  # clean session → reset backoff
            except Exception as exc:
                self.last_error = str(exc)
                self.connected = False
                if self._running:
                    self._log(f"⚠ Tradovate data feed dropped ({exc}) — retrying in {backoff}s")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 120)
            finally:
                try:
                    if self._ws:
                        self._ws.close()
                except Exception:
                    pass
                self._ws = None
                self.connected = False

    def _session(self, token: str, symbol: str) -> None:
        """One authorized WS session: subscribe M1 + M5, pump events until drop."""
        authorized = False
        auth_id = None
        chart_req_tf: Dict[int, int] = {}  # request id → timeframe
        last_heartbeat = time.time()
        self._chart_tf = {}

        def _subscribe(tf: int, elements: int) -> None:
            rid = self._send("md/getchart", body={
                "symbol": symbol,
                "chartDescription": {
                    "underlyingType": "MinuteBar",
                    "elementSize": tf,
                    "elementSizeUnit": "UnderlyingUnits",
                    "withHistogram": False,
                },
                "timeRange": {"asMuchAsElements": elements},
            })
            chart_req_tf[rid] = tf

        while self._running:
            raw = self._ws.recv()
            if raw is None:
                break
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            if not raw:
                continue

            kind, payload = raw[0], raw[1:]
            if kind == "o":
                # Token rides in the frame body per the WS API spec
                auth_id = self._send("authorize", body=token)
            elif kind == "h":
                self._ws.send("[]")
                last_heartbeat = time.time()
            elif kind == "c":
                break
            elif kind == "a":
                for msg in json.loads(payload):
                    if not isinstance(msg, dict):
                        continue
                    if msg.get("i") == auth_id and not authorized:
                        if msg.get("s") == 200:
                            authorized = True
                            self.connected = True
                            self._log(f"📶 Tradovate data feed authorized — "
                                      f"streaming {symbol} M1 + M5")
                            _subscribe(1, self._bar_count)
                            _subscribe(5, TRAIN_M5_BAR_COUNT)
                        else:
                            raise RuntimeError(f"authorize rejected (status {msg.get('s')})")
                    elif msg.get("i") in chart_req_tf:
                        tf = chart_req_tf[msg["i"]]
                        d = msg.get("d") or {}
                        for key in ("historicalId", "realtimeId"):
                            if d.get(key) is not None:
                                self._chart_tf[d[key]] = tf
                    elif msg.get("e") == "chart":
                        for chart_id, bars in parse_chart_bars_grouped(
                                msg.get("d") or {}).items():
                            self._ingest(self._chart_tf.get(chart_id, 1), bars)
                    elif msg.get("e") == "shutdown":
                        raise RuntimeError(f"server shutdown: {msg.get('d')}")

            # Belt-and-suspenders keepalive if server heartbeats stall
            if time.time() - last_heartbeat > 2.4:
                try:
                    self._ws.send("[]")
                except Exception:
                    pass
                last_heartbeat = time.time()

    def _ingest(self, timeframe_minutes: int, bars: List[dict]) -> None:
        if not bars:
            return
        tf = int(timeframe_minutes)
        limit = self._tf_limits.get(tf, self._bar_count)
        with self._bars_lock:
            store = self._bars_by_tf.setdefault(tf, {})
            for bar in bars:
                store[bar["time"]] = bar
            if len(store) > limit * 1.2:
                for t in sorted(store)[:-limit]:
                    del store[t]
            depth = len(store)
            m1 = dict(self._bars_by_tf.get(1) or {}) if tf == 1 else None
        if tf == 5 and depth >= 500 and not getattr(self, "_m5_depth_logged", False):
            self._m5_depth_logged = True
            self._log(f"📚 Tradovate M5 history loaded ({depth} bars) — ML training can start")
        if m1 is None:
            return
        rates = bars_to_mt5_rates(m1, self._bar_count)
        if rates is None or len(rates) == 0:
            return
        try:
            from trader_companion.mt5_market_feed import get_market_feed
            feed = get_market_feed()
            for alias in CACHE_ALIASES:
                feed.inject_rates(alias, rates, source="tradovate")
        except Exception as exc:
            logger.debug("[TradovateMD] cache inject failed: %s", exc)


_md_feed_singleton: Optional[TradovateMDFeed] = None
_md_feed_lock = threading.Lock()


def start_tradovate_md_feed(token_provider, log_fn=None) -> TradovateMDFeed:
    """Start (or return) the singleton feed."""
    global _md_feed_singleton
    with _md_feed_lock:
        if _md_feed_singleton is None:
            _md_feed_singleton = TradovateMDFeed(token_provider, log_fn=log_fn)
        _md_feed_singleton.start()
        return _md_feed_singleton


def get_tradovate_md_feed() -> Optional[TradovateMDFeed]:
    return _md_feed_singleton
