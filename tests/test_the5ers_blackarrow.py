"""
tests/test_the5ers_blackarrow.py

Targeted tests for The5ers → BlackArrow connector integration.
Covers:
  1. Platform routing  — all "5ers" name variants resolve to "BlackArrow"
  2. API surface       — BlackArrowConnector exposes buy_market / sell_market
  3. Delegation        — buy_market / sell_market call place_order correctly
  4. Order mock        — full place_order execution path with a fake Selenium driver
  5. Failure guard     — place_order raises on disconnected state
"""

import sys
import os
import types
import unittest
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Make project root importable without installing the package
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Stub out heavy / GUI-only imports so the connector module loads in tests
# ---------------------------------------------------------------------------
def _stub_selenium():
    """Insert minimal selenium stubs so connectors/blackarrow_connector.py imports."""
    if "selenium" in sys.modules:
        return
    selenium = types.ModuleType("selenium")
    webdriver_mod = types.ModuleType("selenium.webdriver")
    chrome_mod = types.ModuleType("selenium.webdriver.chrome")
    chrome_options = types.ModuleType("selenium.webdriver.chrome.options")
    common = types.ModuleType("selenium.webdriver.common")
    by_mod = types.ModuleType("selenium.webdriver.common.by")
    keys_mod = types.ModuleType("selenium.webdriver.common.keys")
    support = types.ModuleType("selenium.webdriver.support")
    ec_mod = types.ModuleType("selenium.webdriver.support.expected_conditions")
    ui_mod = types.ModuleType("selenium.webdriver.support.ui")

    class _By:
        XPATH = "xpath"
        CSS_SELECTOR = "css selector"
        TAG_NAME = "tag name"
        ID = "id"

    class _Keys:
        ENTER = "\n"

    class _Options:
        def add_argument(self, *a): pass
        def add_experimental_option(self, *a, **kw): pass

    class _Chrome:
        pass

    class _WebDriverWait:
        def __init__(self, driver, timeout): pass
        def until(self, cond): return True

    by_mod.By = _By
    keys_mod.Keys = _Keys
    chrome_options.Options = _Options
    webdriver_mod.Chrome = _Chrome
    webdriver_mod.chrome = chrome_mod
    chrome_mod.options = chrome_options
    ui_mod.WebDriverWait = _WebDriverWait
    ec_mod.presence_of_element_located = lambda *a: None
    support.expected_conditions = ec_mod
    support.ui = ui_mod
    selenium.webdriver = webdriver_mod
    webdriver_mod.common = common
    common.by = by_mod
    common.keys = keys_mod

    sys.modules.update({
        "selenium": selenium,
        "selenium.webdriver": webdriver_mod,
        "selenium.webdriver.chrome": chrome_mod,
        "selenium.webdriver.chrome.options": chrome_options,
        "selenium.webdriver.common": common,
        "selenium.webdriver.common.by": by_mod,
        "selenium.webdriver.common.keys": keys_mod,
        "selenium.webdriver.support": support,
        "selenium.webdriver.support.expected_conditions": ec_mod,
        "selenium.webdriver.support.ui": ui_mod,
    })


_stub_selenium()

from connectors.blackarrow_connector import BlackArrowConnector  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal stub used for platform-routing tests (avoids full tkinter app)
# ---------------------------------------------------------------------------
class _PlatformRouter:
    """Extracts only _platform_for_firm + _FIRM_MAP from TraderApp."""

    _FIRM_MAP = {
        "My Funded Futures": "MFFU_Flex",
        "MFFU": "MFFU",
        "Funding Ticks": "FundingTicks",
        "Funded Next": "Funded Next",
        "FundedNext": "Funded Next",
        "TopStep": "TopStep",
        "TopStep RTP": "TopStep RTP",
        "TopStep_RTP": "TopStep RTP",
        "TradeDay": "TradeDay",
        "Tradeify": "Tradeify",
        "Alpha Futures": "AlphaFutures",
        "Apex": "Apex",
        "Top One Futures": "Top One Futures",
        "Funded Futures Family": "Funded Futures Family",
        "FFF": "Funded Futures Family",
        "Lucid": "Lucid",
        "LucidMaxx": "LucidMaxx",
    }

    def __init__(self, default_platform="Tradovate"):
        self._default = default_platform
        self.prop_firm_mgr = None

    def _platform_for_firm(self, firm_name, default=None):
        """Copied verbatim from TraderApp._platform_for_firm."""
        if default is None:
            default = self._default
        name = (firm_name or "").strip()
        if not name:
            return default

        if "topstep" in name.lower():
            return "TopStepX"
        _name_stripped = name.lower().replace("%", "").replace(" ", "")
        if "blackarrow" in name.lower() or "the5ers" in _name_stripped or "5ers" in _name_stripped:
            return "BlackArrow"
        if "alphafutures" in name.lower() or "alpha futures" in name.lower():
            return "AlphaTrader"

        norm = name.lower().replace("_", " ").replace("-", " ").strip()
        fc = self._FIRM_MAP.get(name)
        if not fc:
            for k, v in self._FIRM_MAP.items():
                if k.lower().replace("_", " ").replace("-", " ").strip() == norm:
                    fc = v
                    break

        bp = None
        blueprints = getattr(self.prop_firm_mgr, "firm_blueprints", {}) if self.prop_firm_mgr else {}
        if fc and fc in blueprints:
            bp = blueprints[fc]
        elif name in blueprints:
            fc, bp = name, blueprints[name]
        else:
            for bk, bv in blueprints.items():
                bkn = bk.lower().replace("_", " ").replace("-", " ").strip()
                if bkn == norm or (len(norm) >= 3 and (norm in bkn or bkn in norm)):
                    fc, bp = bk, bv
                    break

        if fc and fc.lower().startswith("topstep"):
            return "TopStepX"

        if bp:
            for stage in bp.get("strategy_configs", {}).values():
                for size_cfg in stage.values():
                    keys = list(size_cfg.keys())
                    if any(k.startswith("topstepx_") for k in keys):
                        return "TopStepX"
                    if any(k.startswith("tradovate_") for k in keys):
                        return "Tradovate"

        return default


# ===========================================================================
# 1. Platform routing tests
# ===========================================================================
class TestThe5ersPlatformRouting(unittest.TestCase):
    """Verify every expected "5ers" name variant routes to BlackArrow."""

    def setUp(self):
        self.router = _PlatformRouter(default_platform="Tradovate")

    def _assert_blackarrow(self, name):
        result = self.router._platform_for_firm(name)
        self.assertEqual(
            result, "BlackArrow",
            f"Expected 'BlackArrow' for firm name {name!r}, got {result!r}"
        )

    def test_the5ers_exact(self):
        self._assert_blackarrow("The5ers")

    def test_the5ers_lowercase(self):
        self._assert_blackarrow("the5ers")

    def test_the5ers_uppercase(self):
        self._assert_blackarrow("THE5ERS")

    def test_5ers_short(self):
        self._assert_blackarrow("5ers")

    def test_the_5ers_with_space(self):
        self._assert_blackarrow("The 5ers")

    def test_the5ers_percent_variant(self):
        # Name with a % character (stripped before check)
        self._assert_blackarrow("The5ers%")

    def test_blackarrow_literal(self):
        self._assert_blackarrow("BlackArrow")

    def test_blackarrow_lowercase(self):
        self._assert_blackarrow("blackarrow")

    def test_empty_name_returns_default(self):
        result = self.router._platform_for_firm("")
        self.assertEqual(result, "Tradovate")

    def test_none_name_returns_default(self):
        result = self.router._platform_for_firm(None)
        self.assertEqual(result, "Tradovate")

    def test_topstep_not_blackarrow(self):
        result = self.router._platform_for_firm("TopStep")
        self.assertEqual(result, "TopStepX")

    def test_tradovate_firm_not_blackarrow(self):
        result = self.router._platform_for_firm("MFFU")
        self.assertNotEqual(result, "BlackArrow")


# ===========================================================================
# 2. API surface tests
# ===========================================================================
class TestBlackArrowConnectorAPISurface(unittest.TestCase):
    """BlackArrowConnector must expose the standard broker interface."""

    EXPECTED_METHODS = [
        "connect",
        "disconnect",
        "place_order",
        "buy_market",
        "sell_market",
        "close_all",
        "get_account_balance",
        "get_account_stats",
        "is_connected",
    ]

    def setUp(self):
        self.conn = BlackArrowConnector(email="test@example.com", password="secret")

    def test_all_required_methods_present(self):
        for method in self.EXPECTED_METHODS:
            self.assertTrue(
                hasattr(self.conn, method),
                f"BlackArrowConnector missing method: {method}"
            )
            self.assertTrue(
                callable(getattr(self.conn, method)),
                f"BlackArrowConnector.{method} is not callable"
            )

    def test_initial_state_disconnected(self):
        self.assertFalse(self.conn.is_connected())

    def test_initial_driver_is_none(self):
        self.assertIsNone(self.conn._driver)


# ===========================================================================
# 3. Delegation tests — buy_market / sell_market → place_order
# ===========================================================================
class TestBlackArrowMarketOrderDelegation(unittest.TestCase):
    """buy_market / sell_market must delegate to place_order with correct args."""

    def setUp(self):
        self.conn = BlackArrowConnector(email="test@example.com", password="secret")
        self.conn._connected = True
        self.conn._driver = MagicMock()
        # Patch place_order so we can assert calls without touching the browser
        self.conn.place_order = MagicMock(return_value=True)

    def test_buy_market_calls_place_order_buy_side(self):
        result = self.conn.buy_market("NQFUT", qty=2, tp=50, sl=100)
        self.conn.place_order.assert_called_once_with(
            "NQFUT", side="buy", qty=2, tp_ticks=50, sl_ticks=100
        )
        self.assertTrue(result)

    def test_sell_market_calls_place_order_sell_side(self):
        result = self.conn.sell_market("NQFUT", qty=3, tp=40, sl=80)
        self.conn.place_order.assert_called_once_with(
            "NQFUT", side="sell", qty=3, tp_ticks=40, sl_ticks=80
        )
        self.assertTrue(result)

    def test_buy_market_no_tp_sl(self):
        self.conn.buy_market("NQFUT")
        self.conn.place_order.assert_called_once_with(
            "NQFUT", side="buy", qty=1, tp_ticks=None, sl_ticks=None
        )

    def test_sell_market_no_tp_sl(self):
        self.conn.sell_market("NQFUT")
        self.conn.place_order.assert_called_once_with(
            "NQFUT", side="sell", qty=1, tp_ticks=None, sl_ticks=None
        )

    def test_expected_account_param_accepted_and_ignored(self):
        """expected_account must be accepted without error (ignored by BlackArrow)."""
        self.conn.buy_market("NQFUT", qty=1, tp=20, sl=40, expected_account="12345678")
        self.conn.place_order.assert_called_once_with(
            "NQFUT", side="buy", qty=1, tp_ticks=20, sl_ticks=40
        )

    def test_sell_market_expected_account_accepted(self):
        self.conn.sell_market("NQFUT", qty=2, tp=None, sl=None, expected_account="99887766")
        self.conn.place_order.assert_called_once_with(
            "NQFUT", side="sell", qty=2, tp_ticks=None, sl_ticks=None
        )


# ===========================================================================
# 4. place_order mock execution
# ===========================================================================
class TestBlackArrowPlaceOrderMock(unittest.TestCase):
    """Simulate a full place_order execution with a fake Selenium driver."""

    def _make_connected_connector(self):
        conn = BlackArrowConnector(email="test@example.com", password="secret")
        conn._connected = True
        mock_driver = MagicMock()
        # execute_script returns truthy so _click_ionic_button succeeds
        mock_driver.execute_script.return_value = True
        conn._driver = mock_driver
        return conn, mock_driver

    def test_place_buy_order_clicks_buy_at_mkt(self):
        """place_order(side='buy') must click 'Buy at Mkt'."""
        conn, mock_driver = self._make_connected_connector()
        with patch("time.sleep"):
            with patch.object(conn, "_confirm_order_dialog"):
                with patch.object(conn, "_click_ionic_button", return_value=True) as mock_btn:
                    result = conn.place_order("NQFUT", side="buy", qty=1)
        mock_btn.assert_any_call("Buy at Mkt")
        self.assertTrue(result)

    def test_place_sell_order_clicks_sell_at_mkt(self):
        """place_order(side='sell') must click 'Sell at Mkt'."""
        conn, mock_driver = self._make_connected_connector()
        with patch("time.sleep"):
            with patch.object(conn, "_confirm_order_dialog"):
                with patch.object(conn, "_click_ionic_button", return_value=True) as mock_btn:
                    result = conn.place_order("NQFUT", side="sell", qty=2)
        mock_btn.assert_any_call("Sell at Mkt")
        self.assertTrue(result)

    def test_place_order_tp_sl_places_separate_orders(self):
        """With tp_ticks/sl_ticks, place_order must place 3 ionic button clicks:
        entry + TP order + SL order (all via _click_ionic_button)."""
        conn, mock_driver = self._make_connected_connector()
        with patch("time.sleep"):
            with patch.object(conn, "_confirm_order_dialog"):
                with patch.object(conn, "_get_avg_price", return_value=20000.0):
                    with patch.object(conn, "_click_ionic_button", return_value=True) as mock_btn:
                        result = conn.place_order(
                            "NQFUT", side="buy", qty=1, tp_ticks=100, sl_ticks=200
                        )
        calls = [c.args[0] for c in mock_btn.call_args_list]
        self.assertIn("Buy at Mkt", calls)   # entry
        self.assertEqual(calls.count("Sell"), 2)  # TP + SL exit orders for long
        self.assertTrue(result)


# ===========================================================================
# 5. Failure guard
# ===========================================================================
class TestBlackArrowFailureGuards(unittest.TestCase):
    """place_order must raise RuntimeError if not connected."""

    def test_place_order_raises_when_not_connected(self):
        conn = BlackArrowConnector(email="test@example.com", password="secret")
        # _connected = False, _driver = None (default)
        with self.assertRaises(RuntimeError) as ctx:
            conn.place_order("NQFUT", side="buy", qty=1)
        self.assertIn("not connected", str(ctx.exception).lower())

    def test_buy_market_raises_when_not_connected(self):
        conn = BlackArrowConnector(email="test@example.com", password="secret")
        with self.assertRaises(RuntimeError):
            conn.buy_market("NQFUT", qty=1)

    def test_sell_market_raises_when_not_connected(self):
        conn = BlackArrowConnector(email="test@example.com", password="secret")
        with self.assertRaises(RuntimeError):
            conn.sell_market("NQFUT", qty=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
