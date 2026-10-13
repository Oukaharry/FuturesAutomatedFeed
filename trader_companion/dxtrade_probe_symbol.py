"""Probe: switch the DXtrade Market Depth widget to a symbol and read its book."""

import logging
import sys
import time

from dotenv import load_dotenv
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from trader_companion.dxtrade_browser import DXTradeBrowserSession


def main():
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    symbol = sys.argv[1] if len(sys.argv) > 1 else "XYZ100/USD"
    sess = DXTradeBrowserSession.from_env()
    sess.login(api_login=False)
    d = sess.driver
    time.sleep(6)

    inp = d.find_element(By.CSS_SELECTOR, "[data-test-id='market_depth_suggest']")
    print("current widget symbol:", inp.get_attribute("value"))
    inp.click()
    time.sleep(0.4)
    inp.send_keys(Keys.COMMAND, "a")
    inp.send_keys(Keys.BACKSPACE)
    inp.send_keys(symbol)
    time.sleep(1.5)

    # dump any suggestion dropdown that appeared
    dump = d.execute_script(r"""
      const txt = e => (e.innerText || e.textContent || '').trim().replace(/\s*\n\s*/g,' | ');
      const out = [];
      document.querySelectorAll('[role="option"], [role="listbox"] *, [class*="suggest"], [class*="Suggest"], [class*="dropdown"], [class*="popup"]').forEach(e => {
        const t = txt(e); if (t && t.length < 200 && /XYZ|100|Nasdaq/i.test(t)) out.push([e.tagName, (e.className||'').toString().slice(0,80), t]);
      });
      return out.slice(0, 20);
    """)
    print("suggestions:", dump)

    inp.send_keys(Keys.ENTER)
    time.sleep(3)
    print("widget symbol after ENTER:", d.find_element(
        By.CSS_SELECTOR, "[data-test-id='market_depth_suggest']").get_attribute("value"))

    for attempt in range(3):
        try:
            q = sess.get_quote_from_terminal(symbol)
            print("QUOTE:", q)
            break
        except Exception as e:
            print("quote attempt failed:", e)
            time.sleep(2)

    rows = d.execute_script(r"""
      const txt = e => (e.innerText || e.textContent || '').trim().replace(/\s*\n\s*/g,' | ');
      return Array.from(document.querySelectorAll("[data-test-id='table_row']")).slice(0,6).map(txt);
    """)
    print("top rows:", rows)
    time.sleep(5)
    sess.close()


if __name__ == "__main__":
    main()
