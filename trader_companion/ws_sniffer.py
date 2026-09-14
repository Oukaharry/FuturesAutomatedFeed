"""WebSocket frame capture for the Tradovate web app.

Diagnostic tool: uses Chrome's "performance" log (CDP Network domain events)
to observe websocket traffic on an already-logged-in Tradovate tab, without
any extra API credentials or a separate CDP connection. The goal is to find
the message format Tradovate's own web app uses for quotes/charts, so a
future price-feed integration can read bars from it instead of MT5.

Performance logging must be enabled on the ChromeOptions BEFORE the driver
is created (see enable_network_logging) — it cannot be toggled afterward.
"""

import json
import logging
import os
import time


def enable_network_logging(chrome_options):
    """Turn on Chrome's performance log so websocket frames are captured.

    Must be called on the ChromeOptions instance before driver creation —
    logging preferences are a launch-time capability.
    """
    chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    chrome_options.add_experimental_option(
        "perfLoggingPrefs", {"enableNetwork": True, "enablePage": False})


def capture_websocket_frames(driver, out_path, duration_sec=90,
                             text_filter=None, poll_interval=1.0):
    """Poll the performance log and dump websocket frames to a JSONL file.

    Args:
        driver: Active Selenium Chrome driver with performance logging
            enabled (see enable_network_logging).
        out_path: File to append captured frames to (one JSON object/line).
        duration_sec: How long to capture before returning.
        text_filter: Optional case-insensitive substring — only frames
            whose payload contains it are written. None captures everything.
        poll_interval: Seconds between log drains.

    Returns:
        (frame_count, socket_urls) — frames written and the set of distinct
        websocket URLs seen, so the market-data socket can be identified
        among auth/heartbeat/other sockets.
    """
    socket_urls = {}  # requestId -> url
    frame_count = 0
    deadline = time.time() + duration_sec

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(out_path, "a", encoding="utf-8") as fh:
        while time.time() < deadline:
            try:
                entries = driver.get_log("performance")
            except Exception as e:
                logging.warning(f"[WSSniff] get_log('performance') failed: {e}")
                break

            for entry in entries:
                try:
                    msg = json.loads(entry["message"])["message"]
                except Exception:
                    continue
                method = msg.get("method")
                params = msg.get("params", {})

                if method == "Network.webSocketCreated":
                    socket_urls[params.get("requestId")] = params.get("url")
                    continue
                if method not in ("Network.webSocketFrameReceived",
                                  "Network.webSocketFrameSent"):
                    continue

                payload = (params.get("response") or {}).get("payloadData", "")
                if not payload:
                    continue
                if text_filter and text_filter.lower() not in payload.lower():
                    continue

                record = {
                    "ts": time.time(),
                    "direction": "recv" if method.endswith("Received") else "sent",
                    "socket_url": socket_urls.get(params.get("requestId"), "unknown"),
                    "payload": payload,
                }
                fh.write(json.dumps(record) + "\n")
                fh.flush()
                frame_count += 1

            time.sleep(poll_interval)

    return frame_count, set(socket_urls.values())
