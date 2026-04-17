"""
Hedge Protector — Double-SL Prevention Engine

Monitors both MT5 and Tradovate positions in real-time.
When a trade closes via SL on one side, immediately closes the hedge on the other side.
When a trade closes via TP, leaves the hedge running (chance for double TP).

Matching: MT5 comment format = "{TradovateAccountNumber}_{PhaseCode}"
e.g., "FNFTCHHARRISONOUKA85625_CH1", "MFFU_EV_ST_P326057008_FD1"

Architecture:
    - MT5: Polls positions every 500ms, detects removals
    - Tradovate: REST polling every 5s for position change detection
    - Engine: Matches pairs, determines SL vs TP, triggers close
"""

import time
import json
import threading
import logging
from datetime import datetime, timezone
from collections import defaultdict

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None


class HedgeProtector:
    """
    Real-time hedge protection engine.
    
    Monitors MT5 and Tradovate positions. When a position closes:
      - If SL hit → close the matching hedge on the other platform
      - If TP hit → do nothing (let hedge run for potential double TP)
    
    Usage:
        protector = HedgeProtector(
            mt5_api=mt5_api_instance,
            tradovate_accounts={firm_name: tradovate_account_instance, ...},
            on_event=callback_fn,   # (event_type, message) for UI logging
        )
        protector.start()
        ...
        protector.stop()
    """

    def __init__(self, mt5_api=None, tradovate_accounts=None, on_event=None, on_status_change=None):
        """
        Args:
            mt5_api: MT5API instance (from mt5_trading.py) — must be connected
            tradovate_accounts: dict of {firm_name: TradovateAccount} — connected instances
            on_event: callback(event_type: str, message: str) for UI notifications
                      event_type: "info", "warn", "sl_detected", "tp_detected", "close_sent", "error"
            on_status_change: callback(acct_name: str, close_reason: str, phase_key: str)
                              Called immediately when TP/SL detected so dashboard status can be updated.
                              close_reason: "tp_detected" or "sl_detected"
                              phase_key: e.g. "challenge_trade2", "funded_trade1" (from MT5 comment)
        """
        self.mt5_api = mt5_api
        self.tradovate_accounts = tradovate_accounts or {}
        self.on_event = on_event or (lambda t, m: print(f"[HEDGE {t.upper()}] {m}"))
        self.on_status_change = on_status_change

        self._running = False
        self._mt5_thread = None
        self._tv_threads = {}       # {firm_name: polling_thread}

        # Position snapshots for change detection
        self._mt5_positions = {}    # {ticket: {symbol, type, volume, comment, sl, tp, profit, price_open}}
        self._tv_positions = {}     # {firm_name: {contract_id: {netPos, netPrice, ...}}}

        # Tradovate account info cache
        self._tv_account_info = {}  # {firm_name: {id, name, env, token}}

        # Track which hedges we've already closed (prevent re-triggers)
        self._closed_hedges = set()  # set of "mt5_{ticket}" or "tv_{firm}_{acct_id}"

        # Stats
        self.stats = {
            "sl_protected": 0,
            "tp_passed": 0,
            "errors": 0,
            "mt5_polls": 0,
            "tv_events": 0,
        }

    # ── Public API ─────────────────────────────────────────────────────

    def start(self):
        """Start monitoring both MT5 and Tradovate positions."""
        if self._running:
            return
        self._running = True
        self.on_event("info", "Hedge Protector starting...")

        # Start MT5 position poller
        if self.mt5_api:
            self._mt5_thread = threading.Thread(target=self._mt5_poll_loop, daemon=True, name="HedgeProtector-MT5")
            self._mt5_thread.start()
            self.on_event("info", "MT5 position monitor started (500ms poll)")

        # Start Tradovate REST position pollers
        for firm_name, tv_account in self.tradovate_accounts.items():
            self._start_tradovate_rest(firm_name, tv_account)

        self.on_event("info", f"Hedge Protector active — monitoring {len(self.tradovate_accounts)} Tradovate account(s) (REST 5s)")

    def stop(self):
        """Stop all monitoring."""
        self._running = False
        self.on_event("info", "Hedge Protector stopping...")

        # Stop all Tradovate polling threads
        self._tv_threads.clear()
        self.on_event("info", "Hedge Protector stopped")

    @property
    def is_running(self):
        return self._running

    # ── MT5 Position Monitor ──────────────────────────────────────────

    def _mt5_poll_loop(self):
        """Poll MT5 positions every 500ms, detect closures."""
        while self._running:
            try:
                self._mt5_check_positions()
                self.stats["mt5_polls"] += 1
            except Exception as e:
                self.on_event("error", f"MT5 poll error: {e}")
                self.stats["errors"] += 1
            time.sleep(0.5)

    def _mt5_check_positions(self):
        """Snapshot MT5 positions and detect any that disappeared (closed)."""
        if not mt5:
            return

        positions = mt5.positions_get()
        current = {}
        if positions:
            for pos in positions:
                current[pos.ticket] = {
                    "ticket": pos.ticket,
                    "symbol": pos.symbol,
                    "type": pos.type,       # 0=Buy, 1=Sell
                    "volume": pos.volume,
                    "comment": getattr(pos, 'comment', ''),
                    "sl": pos.sl,
                    "tp": pos.tp,
                    "profit": pos.profit,
                    "price_open": pos.price_open,
                    "price_current": pos.price_current,
                }

        # Detect closed positions (were in previous snapshot, gone now)
        for ticket, prev_pos in self._mt5_positions.items():
            if ticket not in current:
                self._on_mt5_position_closed(prev_pos)

        self._mt5_positions = current

    def _on_mt5_position_closed(self, pos):
        """Called when an MT5 position disappears (closed)."""
        ticket = pos['ticket']
        comment = pos.get('comment', '')
        symbol = pos['symbol']
        profit = pos['profit']

        # Skip if no comment (not a hedge trade)
        if not comment or '_' not in comment:
            return

        # Parse the Tradovate account from comment
        # Format: "{TradovateAccountNumber}_{PhaseCode}" 
        # e.g., "FNFTCHHARRISONOUKA85625_CH1"
        parts = comment.rsplit('_', 1)
        if len(parts) < 2:
            return
        
        # The account number is everything before the last underscore
        # But phase codes can have underscores too (e.g., FA_210126)
        # So we need to find the tradovate account by trying different splits
        tv_account_number = self._extract_tradovate_account(comment)
        if not tv_account_number:
            return

        phase_code = comment[len(tv_account_number) + 1:] if len(comment) > len(tv_account_number) else ""

        # Check for duplicate
        hedge_key = f"mt5_{ticket}"
        if hedge_key in self._closed_hedges:
            return
        self._closed_hedges.add(hedge_key)

        # Determine if SL or TP hit
        close_reason = self._determine_mt5_close_reason(pos)

        self.on_event(close_reason, 
                      f"MT5 #{ticket} {symbol} closed — {close_reason.upper()} — "
                      f"P&L: ${profit:+.2f} — Comment: {comment}")

        if close_reason == "sl_detected":
            # SL HIT → Close the Tradovate hedge immediately
            self.stats["sl_protected"] += 1
            self._close_tradovate_hedge(tv_account_number, symbol, pos)
        elif close_reason == "tp_detected":
            # TP HIT → Let the hedge run
            self.stats["tp_passed"] += 1
            self.on_event("tp_detected",
                          f"TP hit on MT5 #{ticket} — letting Tradovate hedge run for double TP potential")
            # Cancel remaining Tradovate bracket orders (stop/limit)
            self._cancel_tradovate_orders(tv_account_number)

        # Fire status change callback with account + phase_key from comment
        if self.on_status_change and phase_code:
            try:
                self.on_status_change(tv_account_number, close_reason, phase_code)
            except Exception as _sc_e:
                self.on_event("error", f"Status change callback failed: {_sc_e}")

    def _determine_mt5_close_reason(self, pos):
        """Determine if an MT5 position closed via SL or TP.
        
        Logic:
          - If profit < 0 → SL (or manual loss close)
          - If profit > 0 AND tp was set AND price reached tp → TP
          - If profit > 0 but no tp set → manual close (treat as neutral, don't close hedge)
        
        For hedging safety, we treat negative profit as SL.
        """
        profit = pos.get('profit', 0)
        sl = pos.get('sl', 0)
        tp = pos.get('tp', 0)
        price_current = pos.get('price_current', 0)
        price_open = pos.get('price_open', 0)
        pos_type = pos.get('type', 0)

        if profit < 0:
            return "sl_detected"
        
        if profit >= 0 and tp > 0:
            # Check if price was near TP
            if pos_type == 0:  # Buy — TP is above
                if price_current >= tp * 0.999:
                    return "tp_detected"
            else:  # Sell — TP is below
                if price_current <= tp * 1.001:
                    return "tp_detected"
        
        if profit >= 0:
            return "tp_detected"
        
        return "sl_detected"

    def _extract_tradovate_account(self, comment):
        """Extract Tradovate account number from MT5 comment.
        
        Tries to match against known connected Tradovate accounts.
        Comment format: "{AccountNumber}_{PhaseCode}"
        """
        # Get all known Tradovate account names
        known_accounts = set()
        for firm_name, info in self._tv_account_info.items():
            acct_name = info.get('name', '')
            if acct_name:
                known_accounts.add(acct_name)

        # Try exact prefix match against known accounts
        for acct_name in known_accounts:
            if comment.startswith(acct_name):
                return acct_name

        # Fallback: split on known phase code patterns
        import re
        # Match everything before _CH\d, _FD\d, _DD\d, _FA, _EV, etc.
        m = re.match(r'^(.+?)_(CH\d|FD\d|DD\d|FA|EV)', comment)
        if m:
            return m.group(1)
        
        # Last resort: everything before the last _
        parts = comment.rsplit('_', 1)
        return parts[0] if len(parts) == 2 else None

    def _close_tradovate_hedge(self, tv_account_number, mt5_symbol, mt5_pos):
        """Close the matching Tradovate position when MT5 SL is hit."""
        self.on_event("close_sent", 
                      f"🛡️ Closing Tradovate hedge for account {tv_account_number} (MT5 SL hit)")

        # Find which Tradovate connection has this account
        for firm_name, tv_account in self.tradovate_accounts.items():
            try:
                # Check if this connection owns the account
                acct_info = self._tv_account_info.get(firm_name, {})
                acct_name = acct_info.get('name', '')
                acct_id = acct_info.get('id')

                if tv_account_number in acct_name or acct_name in tv_account_number:
                    # Found the matching Tradovate connection → liquidate
                    self.on_event("close_sent",
                                  f"🛡️ Liquidating {firm_name} account {acct_name} via API")
                    result = tv_account.liquidate_position_api(account_id=acct_id)
                    if result:
                        self.on_event("close_sent",
                                      f"✅ Tradovate hedge closed for {acct_name}")
                    else:
                        self.on_event("error",
                                      f"❌ Failed to liquidate Tradovate position on {acct_name}")
                    # Cancel remaining bracket orders
                    self._cancel_tradovate_orders_by_firm(firm_name)
                    return
                
                # Also check all accounts under this connection
                accounts = tv_account._api_fetch("/account/list")
                if accounts:
                    for acct in accounts:
                        name = acct.get('name', '')
                        if tv_account_number in name or name in tv_account_number:
                            aid = acct['id']
                            self.on_event("close_sent",
                                          f"🛡️ Liquidating {firm_name} account {name} (id={aid}) via API")
                            result = tv_account.liquidate_position_api(account_id=aid)
                            if result:
                                self.on_event("close_sent",
                                              f"✅ Tradovate hedge closed for {name}")
                            else:
                                self.on_event("error",
                                              f"❌ Failed to liquidate Tradovate position on {name}")
                            # Cancel remaining bracket orders
                            self._cancel_tradovate_orders_by_firm(firm_name)
                            return

            except Exception as e:
                self.on_event("error", f"Error closing Tradovate hedge on {firm_name}: {e}")

        self.on_event("warn", f"⚠ No matching Tradovate account found for: {tv_account_number}")

    # ── Tradovate REST Position Monitor ─────────────────────────────

    def _start_tradovate_rest(self, firm_name, tv_account):
        """Start REST position polling for a Tradovate account."""
        # Cache account info on startup
        try:
            accounts = tv_account._api_fetch("/account/list")
            if accounts and len(accounts) > 0:
                acct = accounts[0]
                self._tv_account_info[firm_name] = {
                    'id': acct['id'],
                    'name': acct.get('name', '?'),
                }
                self.on_event("info", f"Tradovate {firm_name}: account {acct.get('name', '?')} (id={acct['id']})")
                # Cache all accounts for multi-account logins
                for a in accounts:
                    key = f"{firm_name}_{a['id']}"
                    self._tv_account_info[key] = {
                        'id': a['id'],
                        'name': a.get('name', '?'),
                    }
        except Exception as e:
            self.on_event("warn", f"Could not fetch account list for {firm_name}: {e}")

        t = threading.Thread(target=self._tv_rest_poll_loop, args=(firm_name, tv_account),
                             daemon=True, name=f"HedgeProtector-TV-REST-{firm_name}")
        t.start()
        self._tv_threads[firm_name] = t
        self.on_event("info", f"Tradovate REST poller started for {firm_name} (5s interval)")

    def _on_tradovate_position_closed(self, firm_name, tv_account, position_entity, prev_net_pos):
        """Called when a Tradovate position goes to netPos=0 (closed)."""
        acct_info = self._tv_account_info.get(firm_name, {})
        acct_name = acct_info.get('name', '?')
        acct_id = acct_info.get('id', 0)
        contract_id = position_entity.get('contractId', 0)

        # Check for duplicate
        hedge_key = f"tv_{firm_name}_{contract_id}"
        if hedge_key in self._closed_hedges:
            return
        self._closed_hedges.add(hedge_key)

        # Get P&L info from the position entity
        bought_val = position_entity.get('boughtValue', 0)
        sold_val = position_entity.get('soldValue', 0)
        realized_pnl = sold_val - bought_val  # Rough P&L estimate

        # Determine SL or TP: if prev position was closed at a loss → SL
        # For hedging: Tradovate hedge is OPPOSITE of MT5
        # If Tradovate lost money → that's the Tradovate SL → close the MT5 side
        close_reason = "sl_detected" if realized_pnl < 0 else "tp_detected"

        self.on_event(close_reason,
                      f"Tradovate {firm_name} ({acct_name}) position closed — {close_reason.upper()} — "
                      f"Contract: {contract_id}, prev_netPos: {prev_net_pos}")

        if close_reason == "sl_detected":
            self.stats["sl_protected"] += 1
            self._close_mt5_hedge(acct_name, contract_id)
        else:
            self.stats["tp_passed"] += 1
            self.on_event("tp_detected",
                          f"TP hit on Tradovate {acct_name} — letting MT5 hedge run for double TP potential")
        # Cancel remaining Tradovate bracket orders (stop/limit) after any close
        self._cancel_tradovate_orders_by_firm(firm_name)

        # Fire status change callback — extract phase_key from matching MT5 comment
        if self.on_status_change:
            phase_key = self._get_phase_key_from_mt5(acct_name)
            if phase_key:
                try:
                    self.on_status_change(acct_name, close_reason, phase_key)
                except Exception as _sc_e:
                    self.on_event("error", f"Status change callback failed: {_sc_e}")

    def _close_mt5_hedge(self, tv_account_name, tv_contract_id):
        """Close the matching MT5 position when Tradovate SL is hit."""
        if not self.mt5_api or not mt5:
            self.on_event("error", "Cannot close MT5 hedge — MT5 not connected")
            return

        self.on_event("close_sent",
                      f"🛡️ Closing MT5 hedge for Tradovate account {tv_account_name} (Tradovate SL hit)")

        # Find MT5 positions whose comment contains this Tradovate account
        positions = mt5.positions_get()
        if not positions:
            self.on_event("warn", "No open MT5 positions found")
            return

        closed_count = 0
        for pos in positions:
            comment = getattr(pos, 'comment', '')
            if not comment:
                continue
            # Check if comment references this Tradovate account
            if tv_account_name in comment:
                self.on_event("close_sent",
                              f"🛡️ Closing MT5 #{pos.ticket} {pos.symbol} (comment: {comment})")
                try:
                    success = self.mt5_api.close_trade(pos.ticket)
                    if success:
                        self.on_event("close_sent",
                                      f"✅ MT5 #{pos.ticket} closed successfully")
                        closed_count += 1
                    else:
                        self.on_event("error",
                                      f"❌ Failed to close MT5 #{pos.ticket}")
                except Exception as e:
                    self.on_event("error", f"Error closing MT5 #{pos.ticket}: {e}")

        if closed_count == 0:
            self.on_event("warn",
                          f"⚠ No matching MT5 positions found for Tradovate account {tv_account_name}")
        else:
            self.on_event("close_sent",
                          f"🛡️ Closed {closed_count} MT5 position(s) for {tv_account_name}")

    def _get_phase_key_from_mt5(self, tv_account_name):
        """Extract phase_key from the MT5 position comment that matches this Tradovate account.
        
        Checks both open positions and the last snapshot for recently closed ones.
        Comment format: "{AccountNumber}_{phase_key}"
        """
        if not mt5:
            return None
        # Check open positions first
        positions = mt5.positions_get()
        if positions:
            for pos in positions:
                comment = getattr(pos, 'comment', '')
                if comment and tv_account_name in comment:
                    suffix = comment[len(tv_account_name):]
                    if suffix.startswith('_'):
                        return suffix[1:]  # strip leading underscore
        # Check cached snapshot (position may have just closed)
        for ticket, pos_data in self._mt5_positions.items():
            comment = pos_data.get('comment', '')
            if comment and tv_account_name in comment:
                suffix = comment[len(tv_account_name):]
                if suffix.startswith('_'):
                    return suffix[1:]
        return None

    def _cancel_tradovate_orders(self, tv_account_number):
        """Cancel all pending Tradovate orders for the given account number."""
        for firm_name, tv_account in self.tradovate_accounts.items():
            try:
                acct_info = self._tv_account_info.get(firm_name, {})
                acct_name = acct_info.get('name', '')
                acct_id = acct_info.get('id')
                if tv_account_number in acct_name or acct_name in tv_account_number:
                    if hasattr(tv_account, 'cancel_all_orders_api'):
                        cancelled = tv_account.cancel_all_orders_api(account_id=acct_id)
                        if cancelled > 0:
                            self.on_event("info", f"🧹 Cancelled {cancelled} Tradovate order(s) for {acct_name}")
                    return
                # Check all accounts under this connection
                accounts = tv_account._api_fetch("/account/list")
                if accounts:
                    for acct in accounts:
                        name = acct.get('name', '')
                        if tv_account_number in name or name in tv_account_number:
                            if hasattr(tv_account, 'cancel_all_orders_api'):
                                cancelled = tv_account.cancel_all_orders_api(account_id=acct['id'])
                                if cancelled > 0:
                                    self.on_event("info", f"🧹 Cancelled {cancelled} Tradovate order(s) for {name}")
                            return
            except Exception as e:
                self.on_event("error", f"Failed to cancel Tradovate orders for {firm_name}: {e}")

    def _cancel_tradovate_orders_by_firm(self, firm_name):
        """Cancel all pending Tradovate orders for a specific firm connection."""
        tv_account = self.tradovate_accounts.get(firm_name)
        if not tv_account or not hasattr(tv_account, 'cancel_all_orders_api'):
            return
        try:
            acct_info = self._tv_account_info.get(firm_name, {})
            acct_id = acct_info.get('id')
            cancelled = tv_account.cancel_all_orders_api(account_id=acct_id)
            if cancelled > 0:
                self.on_event("info", f"🧹 Cancelled {cancelled} Tradovate order(s) for {firm_name}")
        except Exception as e:
            self.on_event("error", f"Failed to cancel Tradovate orders for {firm_name}: {e}")

    # ── REST Position Polling ─────────────────────────────────────────

    def _tv_rest_poll_loop(self, firm_name, tv_account):
        """Poll Tradovate positions via REST API every 5 seconds."""
        prev_positions = {}

        while self._running:
            try:
                positions = tv_account.get_positions_api()
                current = {}
                for p in positions:
                    key = (p.get('accountId', 0), p.get('contractId', 0))
                    current[key] = p.get('netPos', 0)

                # Detect positions that went to 0
                for key, prev_net in prev_positions.items():
                    cur_net = current.get(key, 0)
                    if prev_net != 0 and cur_net == 0:
                        # Position closed
                        entity = {'accountId': key[0], 'contractId': key[1], 'netPos': 0,
                                  'boughtValue': 0, 'soldValue': 0}
                        self._on_tradovate_position_closed(firm_name, tv_account, entity, prev_net)

                prev_positions = current
                self.stats["tv_events"] += 1

            except Exception as e:
                self.on_event("error", f"Tradovate REST poll error ({firm_name}): {e}")
                self.stats["errors"] += 1

            time.sleep(5)

    # ── Utility ───────────────────────────────────────────────────────

    def get_status(self):
        """Return current status for UI display."""
        mt5_count = len(self._mt5_positions)
        tv_firms = len(self._tv_threads)
        return {
            "running": self._running,
            "mt5_positions": mt5_count,
            "tv_connections": tv_firms,
            "sl_protected": self.stats["sl_protected"],
            "tp_passed": self.stats["tp_passed"],
            "errors": self.stats["errors"],
        }

    def clear_closed_cache(self):
        """Clear the closed hedge cache (for re-monitoring after restart)."""
        self._closed_hedges.clear()
