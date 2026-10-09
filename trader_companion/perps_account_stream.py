"""MyFundedPerps authenticated account stream (orders, fills, positions, balances).

One WebSocket covers every account the API key can reach. The server speaks
first: hello → one snapshot per account → snapshot_end → live events. On
reconnect we pass resume/last_seq/since so the server either resumes the
stream in place or replays what we missed (~100s window).

Docs: https://docs.myfundedperpetuals.com/account-streaming.md
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)

LIVE_STREAM_URL = "wss://account-stream.myfundedperpetuals.com/v1/stream"
SANDBOX_STREAM_URL = "wss://account-stream.myfundedperpetuals.com/v1/sandbox/stream"
# No frame of any kind for this long means the connection is dead.
SILENCE_TIMEOUT_SEC = 45


def stream_url_for_key(api_key: str) -> str:
    if str(api_key or "").strip().startswith("fp_test_"):
        return SANDBOX_STREAM_URL
    return LIVE_STREAM_URL


class MFPAccountStream:
    """Background thread mirroring account state from the MFP account stream.

    on_event(frame) is invoked for every snapshot/event frame (not heartbeats).
    Latest account/position/order state is kept per account for polling-free
    breach and fill tracking.
    """

    def __init__(self, api_key: str, on_event: Optional[Callable[[dict], None]] = None,
                 url: str = None, log_fn: Optional[Callable[[str], None]] = None):
        self._api_key = str(api_key or "").strip()
        if not self._api_key:
            raise ValueError("API key required")
        self._url = url or stream_url_for_key(self._api_key)
        self._on_event = on_event
        self._log_fn = log_fn
        self._lock = threading.Lock()
        self.accounts: Dict[str, dict] = {}
        self.positions: Dict[str, Dict[str, dict]] = {}  # account_id → {pos_id: pos}
        self.orders: Dict[str, Dict[str, dict]] = {}     # account_id → {order_id: order}
        self._stream_id: Optional[str] = None
        self._last_seq: Optional[int] = None
        self._last_frame_time: Optional[int] = None  # server epoch ms
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._ws = None
        self.connected = False
        self.last_error: Optional[str] = None

    # ── public API ──────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    def get_account(self, account_id: str) -> Optional[dict]:
        with self._lock:
            acct = self.accounts.get(account_id)
            return dict(acct) if acct else None

    def get_positions(self, account_id: str) -> list:
        with self._lock:
            return list((self.positions.get(account_id) or {}).values())

    def start(self) -> bool:
        if self._running:
            return True
        try:
            import websocket  # noqa: F401  (websocket-client)
        except ImportError:
            self._log("⚠ websocket-client not installed — MFP account stream unavailable")
            return False
        self._running = True
        self._thread = threading.Thread(target=self._run, name="mfp-account-stream",
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
        logger.info("[MFPAccountStream] %s", msg)
        if self._log_fn:
            try:
                self._log_fn(msg)
            except Exception:
                pass

    def _connect_url(self) -> str:
        if self._stream_id and self._last_seq:
            since = self._last_frame_time or int(time.time() * 1000)
            return (f"{self._url}?resume={self._stream_id}"
                    f"&last_seq={self._last_seq}&since={since}")
        return self._url

    def _run(self) -> None:
        import websocket
        backoff = 1.0
        while self._running:
            try:
                self._ws = websocket.create_connection(
                    self._connect_url(),
                    header=[f"Authorization: Bearer {self._api_key}"],
                    timeout=SILENCE_TIMEOUT_SEC)
                self.connected = True
                backoff = 1.0
                self._log(f"connected ({'sandbox' if 'sandbox' in self._url else 'live'})")
                while self._running:
                    raw = self._ws.recv()
                    if not raw:
                        continue
                    self._handle_frame(json.loads(raw))
            except Exception as exc:
                self.last_error = str(exc)
                if self._running:
                    self._log(f"stream error: {exc} — reconnecting in {backoff:.0f}s")
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

    def _handle_frame(self, frame: dict) -> None:
        ftype = frame.get("type")
        if "seq" in frame:
            self._last_seq = frame["seq"]
        if "time" in frame:
            self._last_frame_time = frame["time"]

        if ftype == "heartbeat":
            return
        if ftype == "hello":
            self._stream_id = frame.get("stream_id") or self._stream_id
            if frame.get("resumed"):
                self._log("resumed existing stream — no snapshot expected")
            return
        if ftype == "reconnect":
            raise ConnectionResetError("server requested reconnect")
        if ftype == "error":
            self._log(f"server error: {frame.get('code')} {frame.get('message')}")
            return
        if ftype == "snapshot":
            self._apply_snapshot(frame)
        elif ftype == "account":
            self._apply_account_event(frame)
        elif ftype == "position":
            self._apply_position_event(frame)
        elif ftype == "order":
            self._apply_order_event(frame)
        # fills carry no state to merge; they flow through on_event only

        if ftype in ("snapshot", "snapshot_end", "account", "position",
                     "order", "fill") and self._on_event:
            try:
                self._on_event(frame)
            except Exception:
                logger.exception("[MFPAccountStream] on_event callback failed")

    def _apply_snapshot(self, frame: dict) -> None:
        acct = frame.get("account") or {}
        aid = acct.get("id") or frame.get("account_id")
        if not aid:
            return
        with self._lock:
            self.accounts[aid] = acct
            self.positions[aid] = {p["id"]: p for p in frame.get("positions") or []}
            self.orders[aid] = {o["id"]: o for o in frame.get("orders") or []}

    def _apply_account_event(self, frame: dict) -> None:
        aid = frame.get("account_id")
        if not aid:
            return
        with self._lock:
            if frame.get("event") == "removed":
                self.accounts.pop(aid, None)
                self.positions.pop(aid, None)
                self.orders.pop(aid, None)
            elif frame.get("account"):
                self.accounts[aid] = frame["account"]

    def _apply_position_event(self, frame: dict) -> None:
        aid, pos = frame.get("account_id"), frame.get("position") or {}
        if not (aid and pos.get("id")):
            return
        with self._lock:
            store = self.positions.setdefault(aid, {})
            if frame.get("event") == "closed":
                store.pop(pos["id"], None)
            else:
                store[pos["id"]] = pos

    def _apply_order_event(self, frame: dict) -> None:
        aid, order = frame.get("account_id"), frame.get("order") or {}
        if not (aid and order.get("id")):
            return
        terminal = frame.get("event") in ("filled", "canceled", "rejected", "expired")
        with self._lock:
            store = self.orders.setdefault(aid, {})
            if terminal:
                store.pop(order["id"], None)
            else:
                store[order["id"]] = order
