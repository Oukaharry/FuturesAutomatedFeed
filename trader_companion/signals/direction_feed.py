"""Share one ML direction across every companion, via the dashboard.

Only a companion with MT5 attached can run the ensemble, so that companion
publishes its reading and the dashboard rebroadcasts it. Companions with no
MT5 — which would otherwise coin-flip — subscribe instead.

The signal is a LIVE reading, not a daily bias: it is re-scored every bar and
may flip during the session. Consumers accept any signal published within
SIGNAL_MAX_AGE_SEC, so a momentarily neutral or missed score falls back to the
last actionable reading rather than stopping the trade.
"""
import json
from datetime import datetime, timedelta, timezone

import requests

EAT = timezone(timedelta(hours=3))

# The publisher scores every 5 minutes, so this always spans several reads.
SIGNAL_MAX_AGE_SEC = 60

SETTING_KEY = "ml_direction_signal"
PUBLISH_PATH = "/api/signals/direction"
_TIMEOUT_SEC = 15


def eat_now():
    return datetime.now(EAT)


def eat_today():
    return eat_now().strftime("%Y-%m-%d")


def build_signal(ml_result, symbol="ustech", source=""):
    """Shape a get_ml_direction() result for broadcast, or None if unusable.

    A neutral reading is deliberately not published — it carries no direction
    and would only bury the last actionable one inside the lookback window.
    """
    if not isinstance(ml_result, dict) or not ml_result.get("ready"):
        return None
    direction = str(ml_result.get("direction") or "").lower()
    if direction not in ("buy", "sell"):
        return None
    now = eat_now()
    return {
        "direction": direction,
        "confidence": ml_result.get("confidence"),
        "probability": ml_result.get("probability"),
        "symbol": symbol,
        "model": ml_result.get("model"),
        "source": source,
        "date": now.strftime("%Y-%m-%d"),
        "published_at": now.isoformat(timespec="seconds"),
    }


def signal_age_seconds(signal, now=None):
    """Seconds since the signal was published, or None when it is untimed."""
    if not isinstance(signal, dict):
        return None
    raw = str(signal.get("published_at") or "").strip()
    if not raw:
        return None
    try:
        published = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if published.tzinfo is None:
        published = published.replace(tzinfo=EAT)
    return (now or eat_now()).timestamp() - published.timestamp()


def direction_from(signal, max_age_sec=SIGNAL_MAX_AGE_SEC, now=None):
    """The live direction, or None when it is missing or outside the window."""
    if not isinstance(signal, dict):
        return None
    direction = str(signal.get("direction") or "").lower()
    if direction not in ("buy", "sell"):
        return None
    age = signal_age_seconds(signal, now=now)
    # A signal dated well ahead of us means a clock skew we cannot reason about.
    if age is None or age > max_age_sec or age < -60:
        return None
    return direction


def publish(dashboard_url, signal, headers=None):
    """Send this companion's reading to the dashboard. True when stored."""
    if not dashboard_url or not signal:
        return False
    response = requests.post(
        f"{str(dashboard_url).rstrip('/')}{PUBLISH_PATH}",
        json=signal,
        headers=headers or {"Content-Type": "application/json"},
        timeout=_TIMEOUT_SEC,
    )
    return response.status_code == 200


def fetch(dashboard_url, headers=None):
    """Latest broadcast signal, or None when the dashboard has none."""
    if not dashboard_url:
        return None
    response = requests.get(
        f"{str(dashboard_url).rstrip('/')}{PUBLISH_PATH}",
        headers=headers or {"Content-Type": "application/json"},
        timeout=_TIMEOUT_SEC,
    )
    if response.status_code != 200:
        return None
    payload = response.json() or {}
    signal = payload.get("signal")
    return signal if isinstance(signal, dict) else None


def loads(raw):
    """Decode a stored signal; {} when absent or corrupt."""
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}
