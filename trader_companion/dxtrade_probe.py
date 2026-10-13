"""Probe the live DXtrade workspace DOM: find prices, watchlist, order widgets.

Logs in via Chrome (DXTradeBrowserSession), waits for the workspace, then
dumps what's visible so a price-reading strategy can be written without the
(broker-disabled) market-data API. Saves page_source and a text report to
/tmp/dx_probe/ and leaves Chrome open for --hold seconds.
"""

import argparse
import json
import logging
import os
import re
import time

from dotenv import load_dotenv
from selenium.webdriver.common.by import By

from trader_companion.dxtrade_browser import DXTradeBrowserSession

OUT = "/tmp/dx_probe"


def _txt(el):
    try:
        return (el.text or "").strip().replace("\n", " | ")
    except Exception:
        return ""


def probe(sess, symbol="BTC/USD"):
    d = sess.driver
    os.makedirs(OUT, exist_ok=True)
    report = []

    def say(*a):
        line = " ".join(str(x) for x in a)
        print(line)
        report.append(line)

    say(f"URL: {d.current_url}")
    say(f"TITLE: {d.title}")

    # Live GWT DOM re-renders constantly, so scrape everything in ONE JS pass
    # (no stale Selenium element handles).
    snapshot = d.execute_script(r"""
      const out = {testIds: [], btc: [], tables: [], buttons: [], inputs: [], body: ''};
      const txt = e => (e.innerText || e.textContent || '').trim().replace(/\s*\n\s*/g, ' | ');
      document.querySelectorAll('[data-test-id]').forEach(e => {
        const t = txt(e); if (t && t.length < 200)
          out.testIds.push([e.getAttribute('data-test-id'), t]);
      });
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let n; const seen = new Set();
      while ((n = walker.nextNode())) {
        if (/BTC/.test(n.nodeValue || '')) {
          const el = n.parentElement; if (!el || seen.has(el)) continue; seen.add(el);
          const p = el.parentElement, gp = p && p.parentElement;
          out.btc.push({tag: el.tagName, cls: (el.className||'').toString().slice(0,80),
            text: txt(el).slice(0,100), parent: p ? txt(p).slice(0,200) : '',
            gp: gp ? txt(gp).slice(0,300) : '',
            gpTid: gp ? (gp.getAttribute('data-test-id')||'') : ''});
        }
      }
      document.querySelectorAll("[data-test-id='table_row']").forEach(r => out.tables.push(txt(r).slice(0,250)));
      document.querySelectorAll('button').forEach(b => {
        const t = txt(b), tid = b.getAttribute('data-test-id')||'';
        if (t || tid) out.buttons.push([tid, t.slice(0,80)]);
      });
      document.querySelectorAll('input').forEach(i => out.inputs.push({
        id: i.id, name: i.name, type: i.type, ph: i.placeholder, val: i.value,
        tid: i.getAttribute('data-test-id')||''}));
      out.body = document.body.innerText || '';
      return out;
    """)

    say("\n=== data-test-id elements (with text) ===")
    grouped = {}
    for tid, t in snapshot["testIds"]:
        grouped.setdefault(tid, [])
        if t not in grouped[tid] and len(grouped[tid]) < 3:
            grouped[tid].append(t)
    for tid, texts in sorted(grouped.items()):
        for t in texts:
            say(f"  [{tid}] {t}")

    say(f"\n=== text nodes containing 'BTC' ===")
    for b in snapshot["btc"][:40]:
        say(f"  <{b['tag']} .{b['cls'][:50]}> {b['text']}  || parent: {b['parent'][:150]} "
            f"|| gp[{b['gpTid']}]: {b['gp'][:220]}")

    body = snapshot["body"]
    say("\n=== price-like numbers on page (>=10000.00) ===")
    prices = re.findall(r"(?<![\d.])(\d{2,3}[,]?\d{3}\.\d{1,2})(?![\d])", body)
    say("  ", sorted(set(prices))[:40])

    say("\n=== table rows ===")
    for r in snapshot["tables"][:30]:
        say("  ", r)

    say("\n=== buttons ===")
    for tid, t in snapshot["buttons"][:80]:
        say(f"  [{tid}] {t}")
    say("\n=== inputs ===")
    for i in snapshot["inputs"][:60]:
        say(f"  {i}")

    with open(f"{OUT}/body.txt", "w") as f:
        f.write(body)
    with open(f"{OUT}/page.html", "w") as f:
        f.write(d.page_source)
    with open(f"{OUT}/report.txt", "w") as f:
        f.write("\n".join(report))
    say(f"\nSaved {OUT}/report.txt, body.txt, page.html")


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTC/USD")
    p.add_argument("--hold", type=int, default=0, help="keep Chrome open N seconds after probe")
    p.add_argument("--settle", type=int, default=8, help="seconds to let widgets render")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    sess = DXTradeBrowserSession.from_env()
    sess.login(api_login=False)
    time.sleep(a.settle)
    probe(sess, a.symbol)
    if a.hold:
        print(f"Holding Chrome open for {a.hold}s …")
        time.sleep(a.hold)
    sess.close()


if __name__ == "__main__":
    main()
