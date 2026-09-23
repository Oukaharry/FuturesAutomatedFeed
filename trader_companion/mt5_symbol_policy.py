"""Resolve MT5 hedge symbols for prop-firm blueprints vs broker naming (USTECH vs NAS100)."""

from __future__ import annotations

from typing import Any, Mapping, Optional

DEFAULT_NASDAQ_HEDGE_SYMBOL = "USTECH"

# Brokers / servers that use NAS100 instead of USTECH on MT5.
_VT_MARKET_MARKERS = (
    "vt market",
    "vt markets",
    "vtmarkets",
    "vt-markets",
    "vt_markets",
)

# IC Markets / similar CFD books list the index as USTEC (not Plexy's USTECH).
_IC_MARKET_MARKERS = (
    "ic markets",
    "icmarkets",
    "ic-markets",
    "ic_markets",
    "icmarket",
)

_NASDAQ_CANONICAL = frozenset({
    "ustech", "ustec", "us100", "nas100", "nasdaq", "nq", "ndx", "nasdaq100", "tech100",
})


def _norm(text: Any) -> str:
    return str(text or "").strip()


def _norm_key(text: Any) -> str:
    return _norm(text).lower().replace("_", " ").replace("-", " ")


def is_nasdaq_hedge_symbol(symbol: Any) -> bool:
    raw = _norm(symbol)
    if not raw:
        return True
    key = raw.lower().replace("_", "").replace("-", "").replace(".", "")
    if key in _NASDAQ_CANONICAL:
        return True
    return any(token in key for token in ("ustech", "ustec", "nas100", "nasdaq", "us100"))


def infer_hedge_symbol_from_server(server: Any) -> Optional[str]:
    key = _norm_key(server)
    if not key:
        return None
    if any(marker in key for marker in _VT_MARKET_MARKERS):
        return "NAS100"
    if any(marker in key for marker in _IC_MARKET_MARKERS):
        return "USTEC"
    if "plexy" in key:
        return "USTECH"
    return None


def infer_hedge_symbol_from_broker(broker: Any) -> Optional[str]:
    key = _norm_key(broker)
    if not key:
        return None
    if any(marker in key for marker in _VT_MARKET_MARKERS):
        return "NAS100"
    if any(marker in key for marker in _IC_MARKET_MARKERS):
        return "USTEC"
    if key in ("plexytrade", "plexy trade", "plexy"):
        return "USTECH"
    return None


def model_symbol_for_ml(symbol: Any) -> str:
    """On-disk / bundled ML model key (one ustech model for all Nasdaq tickers)."""
    raw = _norm(symbol)
    if not raw or is_nasdaq_hedge_symbol(raw):
        return "ustech"
    return raw.lower()


def preferred_nasdaq_mt5_symbol(
    *,
    server: Any = None,
    broker: Any = None,
    hedge_account: Optional[Mapping[str, Any]] = None,
    config: Optional[Mapping[str, Any]] = None,
) -> str:
    """Broker-aware Nasdaq ticker before MT5 symbol_select (USTECH vs USTEC vs NAS100)."""
    return resolve_hedge_mt5_symbol(
        config=config,
        hedge_account=hedge_account,
        server=server,
        default=DEFAULT_NASDAQ_HEDGE_SYMBOL,
    )


def resolve_hedge_mt5_symbol(
    *,
    config: Optional[Mapping[str, Any]] = None,
    hedge_account: Optional[Mapping[str, Any]] = None,
    server: Any = None,
    default: str = DEFAULT_NASDAQ_HEDGE_SYMBOL,
) -> str:
    """
    Pick the MT5 symbol for a Nasdaq hedge leg.

    Priority:
      1. hedge_accounts.hedge_symbol / mt5_symbol (dashboard)
      2. Broker or MT5 server inference (VT Markets -> NAS100)
      3. Blueprint config mt5_symbol
      4. default (USTECH for legacy Plexy setups)
    """
    hedge_account = hedge_account if isinstance(hedge_account, Mapping) else {}
    config = config if isinstance(config, Mapping) else {}

    for key in ("hedge_symbol", "mt5_symbol", "symbol"):
        explicit = _norm(hedge_account.get(key))
        if explicit:
            return explicit

    for infer_fn, value in (
        (infer_hedge_symbol_from_broker, hedge_account.get("broker")),
        (infer_hedge_symbol_from_server, server or hedge_account.get("server")),
        (infer_hedge_symbol_from_broker, None),
    ):
        if value is None and infer_fn is infer_hedge_symbol_from_broker:
            continue
        inferred = infer_fn(value)
        if inferred:
            return inferred

    blueprint_sym = _norm(config.get("mt5_symbol"))
    if blueprint_sym:
        return blueprint_sym

    return _norm(default) or DEFAULT_NASDAQ_HEDGE_SYMBOL
