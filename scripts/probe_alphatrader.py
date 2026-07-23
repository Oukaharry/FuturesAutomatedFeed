"""
scripts/probe_alphatrader.py

Opens a fresh Chrome using the saved joehickenfpf@gmail.com profile
(already logged in to futures.alphatrader.com), then steps through the
order panel UI to diagnose button states and optionally place a test trade.

Usage
-----
# diagnostics only — no order placed
python scripts/probe_alphatrader.py

# place a BUY 1 NQ, no bracket
python scripts/probe_alphatrader.py --side buy --qty 1

# place a SELL 1 NQ with TP=205 ticks, SL=175 ticks
python scripts/probe_alphatrader.py --side sell --qty 1 --tp 205 --sl 175 --auto
"""

import argparse
import logging
import os
import re
import sys
import time
import tempfile

ROOT = os.path.join(os.path.dirname(__file__), "..")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("at_probe")

PLATFORM_URL  = "https://futures.alphatrader.com/"
EMAIL         = "joehickenfpf@gmail.com"

# Saved Chrome profile path (same logic as AlphaTraderConnector._init_driver)
_safe = re.sub(r"[^A-Za-z0-9_-]", "_", EMAIL)
PROFILE_DIR = os.path.join(tempfile.gettempdir(), "alphatrader_profiles", _safe)

# ── DOM inspection JS snippets ─────────────────────────────────────────────

DEEP_DIVE_JS = r"""
return (function() {
  var out = {
    allButtons: [], allInputs: [], allText: [],
    layoutComponents: [], iframes: [],
    bodySnippet: document.body ? document.body.innerHTML.slice(0, 4000) : ''
  };
  document.querySelectorAll('button').forEach(function(b) {
    var r = b.getBoundingClientRect();
    out.allButtons.push({ text:(b.innerText||'').trim().slice(0,80),
      enabled:!b.disabled, visible:b.offsetParent!==null,
      cls:b.className.slice(0,80), x:Math.round(r.x), y:Math.round(r.y) });
  });
  document.querySelectorAll('input,select').forEach(function(i) {
    var r = i.getBoundingClientRect();
    out.allInputs.push({ tag:i.tagName, type:i.type, ph:i.placeholder,
      label:(i.getAttribute('aria-label')||'').slice(0,40),
      value:i.value, visible:i.offsetParent!==null,
      x:Math.round(r.x), y:Math.round(r.y) });
  });
  var seen = new Set();
  document.querySelectorAll('*').forEach(function(el) {
    if (el.offsetParent===null || el.children.length>4) return;
    var txt=(el.innerText||'').trim();
    if (!txt || txt.length>150 || seen.has(txt)) return;
    seen.add(txt);
    var r=el.getBoundingClientRect();
    out.allText.push({ t:txt.slice(0,80), x:Math.round(r.x), y:Math.round(r.y),
      tag:el.tagName, cls:el.className.slice(0,60) });
  });
  ['.lm_item','.lm_component','.lm_header','.lm_tab','.lm_title',
   '[class*="component"]','[class*="panel"]','[class*="widget"]'].forEach(function(sel) {
    document.querySelectorAll(sel).forEach(function(el) {
      var txt=(el.innerText||'').trim().slice(0,60); if(!txt) return;
      var r=el.getBoundingClientRect();
      out.layoutComponents.push({ sel:sel, txt:txt, cls:el.className.slice(0,60),
        x:Math.round(r.x), y:Math.round(r.y) });
    });
  });
  document.querySelectorAll('iframe').forEach(function(f) {
    out.iframes.push({ src:f.src, cls:f.className, id:f.id });
  });
  return out;
})();
"""

CLICK_LAYOUTS_JS = r"""
var btn = Array.from(document.querySelectorAll('button')).find(b => (b.innerText||'').trim()==='Layouts');
if (!btn) return 'no_layouts_btn';
btn.click(); return 'clicked';
"""

AFTER_CLICK_JS = r"""
return (function() {
  var out = { menus:[], buttons:[] };
  ['[role="menu"]','[role="listbox"]','.dropdown-menu','.context-menu',
   '[class*="menu"]','[class*="dropdown"]','[class*="modal"]','[class*="overlay"]',
   '[class*="popover"]','[class*="popup"]'].forEach(function(sel) {
    document.querySelectorAll(sel).forEach(function(el) {
      if (el.offsetParent===null) return;
      var r=el.getBoundingClientRect();
      out.menus.push({ sel:sel, cls:el.className.slice(0,80),
        text:(el.innerText||'').trim().slice(0,600),
        html:el.innerHTML.slice(0,1200), x:Math.round(r.x), y:Math.round(r.y) });
    });
  });
  document.querySelectorAll('button').forEach(function(b) {
    if (b.offsetParent===null) return;
    var txt=(b.innerText||'').trim(); if(!txt) return;
    var r=b.getBoundingClientRect();
    out.buttons.push({ text:txt.slice(0,80), cls:b.className.slice(0,60),
      x:Math.round(r.x), y:Math.round(r.y) });
  });
  return out;
})();
"""


# ── helpers ────────────────────────────────────────────────────────────────

def _ok(msg):   print(f"  ✅  {msg}")
def _fail(msg): print(f"  ❌  {msg}")
def _info(msg): print(f"  ℹ   {msg}")
def _sep(title=""):
    print(f"\n{'='*60}")
    if title:
        print(f"  {title}")
    print(f"{'='*60}")


def _open_chrome() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument(f"--user-data-dir={PROFILE_DIR}")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-logging")
    opts.add_argument("--log-level=3")
    opts.add_argument("--remote-allow-origins=*")
    # Anti-detection: hide "Chrome is controlled by automation" banner
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=opts)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"}
    )
    _ok(f"Chrome opened  (profile: {PROFILE_DIR})")
    return driver


def _wait_platform(driver: webdriver.Chrome, timeout: int = 30) -> bool:
    """Return True when the platform dashboard is visible."""
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script(
                "return !!document.querySelector('[class*=\"account\"], [class*=\"balance\"], "
                "[class*=\"equity\"], [class*=\"toolbar\"]')"
            )
        )
        return True
    except Exception:
        return False


# ── diagnostic steps ───────────────────────────────────────────────────────

def step_page_info(driver: webdriver.Chrome) -> bool:
    _sep("1 — Page info")
    _info(f"URL  : {driver.current_url}")
    _info(f"Title: {driver.title}")
    if "/signin" in driver.current_url or "login" in driver.current_url.lower():
        _fail("Still on login page — profile session may have expired")
        return False
    if "alphatrader.com" not in driver.current_url:
        _fail("Not on futures.alphatrader.com")
        return False
    _ok("On Alpha Trader platform")
    return True


def step_dom_snapshot(driver: webdriver.Chrome):
    _sep("2 — Deep DOM snapshot")
    result = driver.execute_script(DEEP_DIVE_JS)

    print("\n  ALL BUTTONS (visible + hidden):")
    for b in result.get("allButtons", []):
        vis = "VIS" if b["visible"] else "hid"
        ena = "ON " if b["enabled"] else "OFF"
        print(f"    [{vis}][{ena}] ({b['x']:4},{b['y']:4})  {b['text']!r}  cls={b['cls'][:40]}")

    print("\n  ALL INPUTS:")
    for i in result.get("allInputs", []):
        vis = "VIS" if i["visible"] else "hid"
        print(f"    [{vis}] {i['tag']} type={i['type']}  ph={i['ph']!r}  label={i['label']!r}  val={i['value']!r}  ({i['x']},{i['y']})")

    print("\n  VISIBLE TEXT NODES (near-leaf):")
    for t in result.get("allText", []):
        print(f"    ({t['x']:4},{t['y']:4})  {t['tag']}  {t['t']!r}")

    print("\n  GOLDEN-LAYOUT / PANEL COMPONENTS:")
    for c in result.get("layoutComponents", []):
        print(f"    sel={c['sel']}  ({c['x']},{c['y']})  {c['txt']!r}  cls={c['cls'][:50]}")

    print("\n  IFRAMES:")
    for f in result.get("iframes", []):
        print(f"    id={f['id']}  cls={f['cls']}  src={f['src'][:80]}")

    print("\n  BODY HTML (first 4000 chars):")
    print(result.get("bodySnippet", "")[:4000])
    return result


def step_click_layouts(driver: webdriver.Chrome):
    _sep("3 — Open Trade Panel sidebar icon")

    # Click the Trade Panel icon (alt="Trade Panel" in left sidebar)
    clicked = driver.execute_script(r"""
        var imgs = document.querySelectorAll('img[alt="Trade Panel"]');
        if (imgs.length) {
            var el = imgs[0];
            for (var i = 0; i < 6; i++) {
                if (!el.parentElement) break;
                el = el.parentElement;
                if (el.tagName==='LI'||el.tagName==='BUTTON'||el.tagName==='A') {
                    el.click(); return 'clicked_' + el.tagName + ' (Trade Panel img found)';
                }
            }
            imgs[0].click(); return 'clicked_img';
        }
        // Fallback: second sidebar-menu-item
        var items = document.querySelectorAll('.sidebar-menu-item');
        if (items.length > 1) { items[1].click(); return 'clicked_sidebar_item_1 (fallback)'; }
        return 'not_found';
    """)
    _info(f"Trade Panel click: {clicked}")
    time.sleep(1.5)

    # Check account selector state
    acct_state = driver.execute_script(r"""
        var w = document.querySelector('.accountSelectorWrapper');
        if (!w) return 'accountSelectorWrapper NOT FOUND';
        return 'accountSelectorWrapper children=' + w.children.length + '  innerHTML=' + w.innerHTML.slice(0,300);
    """)
    _info(f"Account selector: {acct_state}")

    # Dump all visible buttons
    after = driver.execute_script(AFTER_CLICK_JS)
    print("\n  All visible buttons after Trade Panel click:")
    for b in after.get("buttons", []):
        print(f"    ({b['x']:4},{b['y']:4})  {b['text']!r}  cls={b['cls'][:60]}")

    # Dump any new menus/panels
    print("\n  Menus/panels:")
    for m in after.get("menus", []):
        if m.get("text", "").strip():
            print(f"    [{m['sel']}] TEXT: {m['text'][:300]}")

    # Full DOM text snapshot after panel load
    print("\n  All visible text (after Trade Panel click):")
    texts = driver.execute_script(r"""
        var seen = new Set(), out = [];
        document.querySelectorAll('*').forEach(function(el) {
            if (el.offsetParent===null || el.children.length>4) return;
            var t=(el.innerText||'').trim();
            if (!t || t.length>120 || seen.has(t)) return;
            seen.add(t);
            var r=el.getBoundingClientRect();
            out.push({t:t.slice(0,80), x:Math.round(r.x), y:Math.round(r.y), tag:el.tagName});
        });
        return out;
    """)
    for t in texts:
        print(f"    ({t['x']:4},{t['y']:4})  {t['tag']}  {t['t']!r}")
    return after


def step_ensure_order_panel(driver: webdriver.Chrome) -> bool:
    _sep("4 — Ensure Order panel is open")
    # Look for an "Order" tab/button and click it if not already active
    try:
        order_tabs = driver.find_elements(
            By.XPATH, '//button[normalize-space()="Order"] | //a[normalize-space()="Order"] '
                      '| //*[contains(@class,"tab") and normalize-space()="Order"]'
        )
        if order_tabs:
            order_tabs[0].click()
            time.sleep(0.8)
            _ok("Clicked 'Order' tab")
        else:
            _info("No 'Order' tab found — may already be open or different layout")
    except Exception as e:
        _fail(f"Opening order panel: {e}")

    # Check for BUY/SELL buttons as confirmation
    buy_btns = driver.find_elements(
        By.XPATH,
        '//button[contains(translate(normalize-space(),'
        '"abcdefghijklmnopqrstuvwxyz","ABCDEFGHIJKLMNOPQRSTUVWXYZ"),"BUY")]'
    )
    sell_btns = driver.find_elements(
        By.XPATH,
        '//button[contains(translate(normalize-space(),'
        '"abcdefghijklmnopqrstuvwxyz","ABCDEFGHIJKLMNOPQRSTUVWXYZ"),"SELL")]'
    )
    if buy_btns or sell_btns:
        _ok(f"Order panel active — BUY buttons: {len(buy_btns)}, SELL buttons: {len(sell_btns)}")
        for b in (buy_btns + sell_btns):
            txt = b.text.strip()
            ena = b.is_enabled()
            print(f"    [{'ON' if ena else 'OFF'}]  {txt!r}")
        return True
    else:
        _fail("No BUY/SELL buttons found — order panel may not be open")
        return False


def step_probe_contracts_dropdown(driver: webdriver.Chrome):
    """Click the CONTRACTS field and dump what appears (to identify the dropdown structure)."""
    _sep("4b — Probe CONTRACTS dropdown")
    # Click the value div next to the CONTRACTS label
    result = driver.execute_script("""
        var lbl = Array.from(document.querySelectorAll('label'))
            .find(l => (l.innerText||l.textContent).trim().toUpperCase() === 'CONTRACTS');
        if (!lbl) return {error: 'CONTRACTS label not found'};
        var container = lbl.parentElement;
        if (!container) return {error: 'no parent'};
        // Click the first non-label child (value div)
        var els = Array.from(container.querySelectorAll('*'));
        for (var el of els) {
            if (el.tagName !== 'LABEL' && el.offsetParent !== null) {
                el.click();
                return {clicked: el.tagName + '.' + el.className.slice(0,40), text: (el.innerText||el.textContent).trim().slice(0,30)};
            }
        }
        container.click();
        return {clicked: 'container'};
    """)
    _info(f"Clicked CONTRACTS trigger: {result}")
    time.sleep(1.2)

    # Dump ALL elements that appeared — look for instrument names
    findings = driver.execute_script("""
        var interesting = [];
        // Ant Design Select options
        ['.ant-select-item', '.ant-select-item-option', '.ant-select-item-option-content',
         '[class*="select-item"]', '[class*="SelectItem"]',
         '.ant-select-dropdown', '[class*="ant-select-drop"]',
         '[class*="dropdown"]', '[class*="menu"]', '[class*="popup"]',
         '[class*="options"]', '[class*="listbox"]', '[role="listbox"]',
         '[role="option"]', '[role="list"]', '[role="listitem"]'
        ].forEach(function(sel) {
            var found = Array.from(document.querySelectorAll(sel)).filter(function(e) {
                return e.offsetParent !== null || getComputedStyle(e).display !== 'none';
            });
            if (found.length) {
                interesting.push({
                    selector: sel,
                    count: found.length,
                    samples: found.slice(0,5).map(function(e) {
                        return {tag: e.tagName, cls: e.className.slice(0,50),
                                text: (e.innerText||e.textContent||'').trim().slice(0,60)};
                    })
                });
            }
        });
        return interesting;
    """)
    if findings:
        for f in findings:
            print(f"  [{f['selector']}]  count={f['count']}")
            for s in f['samples']:
                print(f"    {s['tag']} cls={s['cls']!r}  text={s['text']!r}")
    else:
        _info("No matching dropdown elements found")

    # Also dump any new text containing instrument keywords
    keywords_found = driver.execute_script("""
        var kw = ['NASDAQ', 'nasdaq', 'S&P', 's&p', 'Micro', 'Gold', 'Crude', 'Dow',
                  'Russell', 'mini', 'NQ', 'ES', 'MES', 'MGC', 'MNQ'];
        var seen = {};
        var results = [];
        document.querySelectorAll('*').forEach(function(el) {
            var t = (el.innerText||el.textContent||'').trim();
            if (!t || t.length > 100 || el.children.length > 2) return;
            for (var k of kw) {
                if (t.includes(k) && !seen[t]) {
                    seen[t] = true;
                    var r = el.getBoundingClientRect();
                    if (r.width > 0 || r.height > 0) {
                        results.push({text: t, tag: el.tagName, cls: el.className.slice(0,40),
                                      x: Math.round(r.x), y: Math.round(r.y)});
                    }
                    break;
                }
            }
        });
        return results;
    """)
    _info(f"Instrument keywords found ({len(keywords_found)} elements):")
    for k in keywords_found[:30]:
        print(f"  ({k['x']:4d},{k['y']:4d}) {k['tag']}  cls={k['cls']!r}  {k['text']!r}")

    # Press ESC to close
    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    time.sleep(0.3)


def step_probe_dom_panel(driver: webdriver.Chrome):
    """
    Find the Order DOM / DOM Ladder panel and explore whether it has its own
    contract-selector widget we can drive instead of the Trade Panel dropdown.
    """
    _sep("6 — Probe Order DOM panel contract selector")

    # ── Step A: look for DOM panel triggers in the sidebar / layout tabs ──
    dom_triggers = driver.execute_script(r"""
        var hits = [];
        // Sidebar icons
        document.querySelectorAll('img').forEach(function(img) {
            var alt = (img.alt||'').toLowerCase();
            if (alt.includes('dom') || alt.includes('depth') || alt.includes('ladder') || alt.includes('order')) {
                var r = img.getBoundingClientRect();
                hits.push({type:'img', alt:img.alt, cls:img.className, x:Math.round(r.x), y:Math.round(r.y)});
            }
        });
        // Tab labels
        document.querySelectorAll('[role="tab"], .lm_tab, [class*="tab"]').forEach(function(el) {
            var t = (el.innerText||el.textContent||'').trim().toLowerCase();
            if (t.includes('dom') || t.includes('depth') || t.includes('ladder') || t === 'order') {
                var r = el.getBoundingClientRect();
                hits.push({type:'tab', text:(el.innerText||'').trim().slice(0,40), cls:el.className.slice(0,40),
                    x:Math.round(r.x), y:Math.round(r.y)});
            }
        });
        // Any clickable element with DOM/Depth text
        document.querySelectorAll('button, a, li, [role="menuitem"]').forEach(function(el) {
            var t = (el.innerText||el.textContent||'').trim().toLowerCase();
            if (t === 'dom' || t === 'depth' || t === 'order dom' || t === 'dom ladder') {
                var r = el.getBoundingClientRect();
                hits.push({type:el.tagName, text:(el.innerText||'').trim().slice(0,40), cls:el.className.slice(0,40),
                    x:Math.round(r.x), y:Math.round(r.y)});
            }
        });
        return hits;
    """)
    if dom_triggers:
        _ok(f"Found {len(dom_triggers)} DOM panel trigger(s):")
        for h in dom_triggers:
            print(f"    type={h['type']}  text={h.get('text',h.get('alt',''))!r}  cls={h['cls']!r}  ({h['x']},{h['y']})")
    else:
        _info("No explicit DOM panel triggers found in sidebar/tabs")

    # ── Step B: look for DOM-like panels already on screen ──
    _info("Scanning for DOM ladder / price ladder panels already rendered...")
    dom_panels = driver.execute_script(r"""
        var hits = [];
        var domKeywords = ['dom', 'depth', 'ladder', 'price-ladder', 'priceLadder', 'orderDom'];
        document.querySelectorAll('[class*="dom"], [class*="Dom"], [class*="DOM"], [class*="depth"], '
            + '[class*="ladder"], [class*="Ladder"], [class*="price-ladder"]').forEach(function(el) {
            if (el.offsetParent===null) return;
            var r = el.getBoundingClientRect();
            hits.push({cls:el.className.slice(0,80), tag:el.tagName,
                text:(el.innerText||'').trim().slice(0,100),
                x:Math.round(r.x), y:Math.round(r.y)});
        });
        return hits;
    """)
    if dom_panels:
        _ok(f"Found {len(dom_panels)} DOM panel element(s):")
        for p in dom_panels[:15]:
            print(f"    {p['tag']}  cls={p['cls']!r}  ({p['x']},{p['y']})  {p['text']!r}")
    else:
        _info("No DOM ladder panel elements found on screen")

    # ── Step C: if a DOM trigger found, click the first visible one and inspect ──
    if dom_triggers:
        visible = [h for h in dom_triggers if h.get('x', 0) > 0 or h.get('y', 0) > 0]
        if visible:
            t = visible[0]
            _info(f"Clicking DOM trigger: {t}")
            clicked = driver.execute_script(f"""
                var x = {t['x']}, y = {t['y']};
                var el = document.elementFromPoint(x, y);
                if (el) {{ el.click(); return el.tagName + '.' + el.className.slice(0,40); }}
                return null;
            """)
            _info(f"Clicked: {clicked}")
            time.sleep(1.5)

    # ── Step D: dump ALL visible dropdowns / selects that might be the DOM contract picker ──
    _info("Looking for any contract/symbol selectors on screen after DOM panel open...")
    selectors = driver.execute_script(r"""
        var hits = [];
        // react-select containers
        document.querySelectorAll('[class*="-container"], [class*="-control"]').forEach(function(el) {
            if (el.offsetParent===null) return;
            var r = el.getBoundingClientRect();
            var parent = el.parentElement;
            var label = '';
            // look for nearby label
            if (parent) {
                var lbl = parent.querySelector('label');
                if (lbl) label = (lbl.innerText||lbl.textContent).trim().slice(0,30);
            }
            hits.push({cls:el.className.slice(0,80), label:label,
                value:(el.innerText||el.textContent||'').trim().slice(0,40),
                x:Math.round(r.x), y:Math.round(r.y)});
        });
        // Ant Design selects
        document.querySelectorAll('.ant-select, .ant-select-selector').forEach(function(el) {
            if (el.offsetParent===null) return;
            var r = el.getBoundingClientRect();
            hits.push({cls:el.className.slice(0,80), label:'(ant-select)',
                value:(el.innerText||el.textContent||'').trim().slice(0,40),
                x:Math.round(r.x), y:Math.round(r.y)});
        });
        return hits;
    """)
    _info(f"Contract/symbol selector candidates ({len(selectors)}):")
    for s in selectors:
        print(f"    label={s['label']!r}  val={s['value']!r}  cls={s['cls']!r}  ({s['x']},{s['y']})")

    # ── Step E: dump all visible BUY/SELL buttons (confirm which panel they belong to) ──
    _info("BUY/SELL buttons visible after DOM panel interaction:")
    btns = driver.execute_script(r"""
        return Array.from(document.querySelectorAll('button')).filter(function(b) {
            if (b.offsetParent===null) return false;
            var t = (b.innerText||'').toUpperCase();
            return t.includes('BUY') || t.includes('SELL');
        }).map(function(b) {
            var r = b.getBoundingClientRect();
            return {text:(b.innerText||'').trim().slice(0,60), cls:b.className.slice(0,50),
                x:Math.round(r.x), y:Math.round(r.y)};
        });
    """)
    for b in btns:
        print(f"    ({b['x']:4},{b['y']:4})  {b['text']!r}  cls={b['cls'][:40]}")


def step_probe_account_switcher(driver: webdriver.Chrome):
    """
    Fully dissect the account-selector widget so we can build a reliable
    switch_account() method that works after connect().
    """
    _sep("7 — Probe Account Switcher")

    # ── Step A: dump the account selector wrapper ──
    wrapper_info = driver.execute_script(r"""
        var w = document.querySelector('.accountSelectorWrapper');
        if (!w) return {error:'accountSelectorWrapper NOT FOUND'};
        var r = w.getBoundingClientRect();
        return {
            found: true,
            childCount: w.children.length,
            innerHTML: w.innerHTML.slice(0,800),
            cls: w.className,
            x: Math.round(r.x), y: Math.round(r.y)
        };
    """)
    if wrapper_info.get('error'):
        _fail(wrapper_info['error'])
    else:
        _ok(f"accountSelectorWrapper: children={wrapper_info['childCount']}  cls={wrapper_info['cls']!r}")
        _info(f"  innerHTML: {wrapper_info['innerHTML'][:400]}")

    # ── Step B: enumerate ALL account-selector-like elements ──
    all_acct_els = driver.execute_script(r"""
        var hits = [];
        ['[class*="account"]', '[class*="Account"]', '[class*="selector"]',
         '[class*="Selector"]', '.ant-select', '[role="combobox"]'].forEach(function(sel) {
            document.querySelectorAll(sel).forEach(function(el) {
                if (el.offsetParent===null) return;
                var r = el.getBoundingClientRect();
                hits.push({sel:sel, tag:el.tagName, cls:el.className.slice(0,80),
                    text:(el.innerText||el.textContent||'').trim().slice(0,60),
                    role:el.getAttribute('role')||'', ariaLabel:el.getAttribute('aria-label')||'',
                    x:Math.round(r.x), y:Math.round(r.y)});
            });
        });
        return hits;
    """)
    _info(f"Account/selector elements on screen ({len(all_acct_els)}):")
    for el in all_acct_els:
        print(f"    sel={el['sel']}  {el['tag']}  cls={el['cls']!r}  text={el['text']!r}  role={el['role']!r}  ({el['x']},{el['y']})")

    # ── Step C: click the account selector and dump the options list ──
    _info("Opening account selector dropdown...")
    click_result = driver.execute_script(r"""
        // Try accountSelectorWrapper triggers
        var w = document.querySelector('.accountSelectorWrapper');
        if (w) {
            var trigger = w.querySelector('button, [role="combobox"], [role="button"], .ant-select-selector, [class*="-control"]');
            if (trigger) { trigger.click(); return 'clicked trigger: ' + trigger.tagName + '.' + trigger.className.slice(0,40); }
            w.click(); return 'clicked wrapper';
        }
        return 'no accountSelectorWrapper';
    """)
    _info(f"Click result: {click_result}")
    time.sleep(0.8)

    # Dump options that appeared
    options = driver.execute_script(r"""
        var opts = [];
        ['[role="option"]', '.ant-select-item', '[class*="option"]', 'li.ant-select-item',
         '.ant-dropdown-menu-item', '[class*="Option"]'].forEach(function(sel) {
            document.querySelectorAll(sel).forEach(function(el) {
                if (el.offsetParent===null && getComputedStyle(el).visibility==='hidden') return;
                var r = el.getBoundingClientRect();
                opts.push({sel:sel, tag:el.tagName, cls:el.className.slice(0,60),
                    text:(el.innerText||el.textContent||'').trim().slice(0,80),
                    x:Math.round(r.x), y:Math.round(r.y)});
            });
        });
        return opts;
    """)
    if options:
        _ok(f"Account options found ({len(options)}):")
        for o in options:
            print(f"    sel={o['sel']}  text={o['text']!r}  cls={o['cls'][:40]!r}  ({o['x']},{o['y']})")
    else:
        _fail("No account options appeared after clicking selector")

    # Also dump any newly visible menus/dropdowns
    menus = driver.execute_script(r"""
        var out = [];
        ['[role="listbox"]','[role="menu"]','[class*="dropdown"]','[class*="menu"]',
         '.ant-select-dropdown','[class*="Dropdown"]'].forEach(function(sel) {
            document.querySelectorAll(sel).forEach(function(el) {
                if (el.offsetParent===null) return;
                var r = el.getBoundingClientRect();
                out.push({sel:sel, cls:el.className.slice(0,60),
                    text:(el.innerText||'').trim().slice(0,300),
                    x:Math.round(r.x), y:Math.round(r.y)});
            });
        });
        return out;
    """)
    if menus:
        _info(f"Dropdown menus visible after click ({len(menus)}):")
        for m in menus:
            print(f"    sel={m['sel']}  cls={m['cls']!r}  ({m['x']},{m['y']})")
            print(f"      text: {m['text'][:200]!r}")
    else:
        _info("No dropdown menus visible after click")

    # Press ESC to close
    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    time.sleep(0.3)

    # ── Step D: test actually switching to a second account if multiple found ──
    if options and len(options) > 1:
        _info(f"Multiple accounts found. Attempting to switch to: {options[1]['text']!r}")
        # Reopen and click the second option
        driver.execute_script(r"""
            var w = document.querySelector('.accountSelectorWrapper');
            if (w) {
                var trigger = w.querySelector('button, [role="combobox"], .ant-select-selector, [class*="-control"]');
                if (trigger) { trigger.click(); return; }
                w.click();
            }
        """)
        time.sleep(0.8)
        # Click second option
        switched = driver.execute_script("""
            var opts = Array.from(document.querySelectorAll('[role="option"], .ant-select-item'));
            if (opts.length > 1 && opts[1].offsetParent !== null) {
                opts[1].click();
                return (opts[1].innerText||opts[1].textContent||'').trim().slice(0,60);
            }
            return null;
        """)
        if switched:
            _ok(f"Switched to: {switched!r}")
            time.sleep(1.0)
            # Read what account is now shown
            current = driver.execute_script(r"""
                var w = document.querySelector('.accountSelectorWrapper');
                return w ? (w.innerText||w.textContent||'').trim().slice(0,80) : 'N/A';
            """)
            _info(f"Account selector now shows: {current!r}")
        else:
            _fail("Could not click second account option")
    else:
        _info("Only one account found (or none) — skipping switch test")


def step_probe_account_switch(driver: webdriver.Chrome, email: str, password: str):
    """
    List all accounts from REST, then cycle through each non-disabled account
    using switch_account(), verifying the UI selector and balance updates.
    """
    _sep("7b — Live Account Switching Test")

    from connectors.alphatrader_connector import AlphaTraderConnector

    # Spin up a connector attached to the already-open browser
    conn = AlphaTraderConnector.__new__(AlphaTraderConnector)
    conn._driver        = driver
    conn._connected     = True
    conn._id_token      = None
    conn._refresh_token = None
    conn._token_exp     = 0
    conn._account_uuid  = None
    conn._account_name  = None
    conn.email          = email
    conn.password       = password

    # Get a fresh token via re-auth so REST calls work
    try:
        conn._rest_login()
        _ok(f"REST auth OK, token expires in {int(conn._token_exp - time.time())}s")
    except Exception as e:
        _fail(f"REST auth failed: {e} — REST account list unavailable")

    # ── Step A: list all accounts ──
    accounts = conn._rest_get_accounts() or []
    if not accounts:
        _fail("No accounts returned from REST API")
        return

    print(f"\n  {'ACCOUNT':<25} {'TYPE':<12} {'STATUS':<10} {'ACTIVE':<8} {'BALANCE':>12}")
    print(f"  {'-'*25} {'-'*12} {'-'*10} {'-'*8} {'-'*12}")
    candidates = []
    for a in accounts:
        name    = a.get("account_name", "?")
        atype   = a.get("account_type", "?")
        status  = a.get("status", "?")
        active  = str(a.get("is_active", False))
        balance = float(a.get("available_balance") or a.get("balance") or 0)
        print(f"  {name:<25} {atype:<12} {status:<10} {active:<8} ${balance:>11,.2f}")
        if status != "disabled":
            candidates.append((name, balance))

    _info(f"\n  {len(candidates)} non-disabled account(s) to test: {[c[0] for c in candidates]}")

    if len(candidates) < 2:
        _info("  Only 1 non-disabled account — single-account switch test only")

    # ── Step B: cycle through candidates ──
    results = []
    prev_balance = None
    for acct_name, expected_balance in candidates:
        _info(f"\n  Switching → {acct_name}  (REST balance: ${expected_balance:,.2f})")

        bal_before = conn.get_account_balance()
        _info(f"  Balance BEFORE switch: ${bal_before:,.2f}" if bal_before else "  Balance BEFORE: N/A")

        ok = conn.switch_account(acct_name)
        _ok(f"  switch_account() returned: {ok}") if ok else _fail(f"  switch_account() returned False")

        # Read current selector text
        selector_text = driver.execute_script(
            "var w=document.querySelector('.accountSelectorWrapper');"
            " return w ? (w.innerText||w.textContent||'').trim().slice(0,80) : '';"
        ) or ""
        _info(f"  Selector now: {selector_text!r}")

        # Read current balance from DOM — switch_account() already waited for it to update
        dom_balance = conn.get_account_balance()
        if dom_balance is not None:
            changed = prev_balance is None or abs(dom_balance - prev_balance) > 0.01
            tag = "(CHANGED)" if changed else "(UNCHANGED)"
            _info(f"  Balance AFTER switch: ${dom_balance:,.2f}  {tag}")
        else:
            _info("  DOM balance: N/A")

        name_ok    = acct_name.upper() in selector_text.upper()
        balance_ok = dom_balance is not None and abs(dom_balance - expected_balance) < 10_000
        status = ("✅" if (name_ok and balance_ok) else
                  f"{'✅' if name_ok else '❌'}name  {'✅' if balance_ok else '❌'}bal")
        results.append({"account": acct_name, "selector": selector_text[:40],
                        "before": bal_before, "after": dom_balance, "status": status})
        prev_balance = dom_balance

    # ── Summary ──
    _sep("Account switch summary")
    print(f"\n  {'ACCOUNT':<25} {'BEFORE':>12} {'AFTER':>12} {'CHANGED':<10} STATUS")
    print(f"  {'-'*25} {'-'*12} {'-'*12} {'-'*10} {'-'*6}")
    for r in results:
        b4  = f"${r['before']:,.2f}" if r['before'] else "N/A"
        af  = f"${r['after']:,.2f}"  if r['after']  else "N/A"
        chg = "YES" if r['before'] and r['after'] and abs(r['after'] - r['before']) > 0.01 else "no"
        print(f"  {r['account']:<25} {b4:>12} {af:>12} {chg:<10} {r['status']}")

    # ── Restore default account ──
    if candidates:
        default = candidates[0][0]
        _info(f"\n  Restoring default: {default}")
        conn.switch_account(default)


def step_probe_switch_and_trade(driver: webdriver.Chrome, email: str,
                                password: str, auto: bool = False,
                                firm: str = "AlphaFutures"):
    """
    For every non-disabled account:
      1. Switch to it and confirm (selector + balance update)
      2. Auto-detect account size → look up challenge_trade1 blueprint
      3. Switch contract, set qty, configure AutoOCO bracket
      4. Click SELL @ MARKET
      5. Report result
    Restores the default (first) account at the end.
    """
    _sep("10 — Switch accounts + place trades")

    from connectors.alphatrader_connector import AlphaTraderConnector, _map_symbol, TICK_SIZE

    conn = AlphaTraderConnector.__new__(AlphaTraderConnector)
    conn._driver        = driver
    conn._connected     = True
    conn._id_token      = None
    conn._refresh_token = None
    conn._token_exp     = 0
    conn._account_uuid  = None
    conn._account_name  = None
    conn.email          = email
    conn.password       = password

    try:
        conn._rest_login()
        _ok(f"REST auth OK")
    except Exception as e:
        _fail(f"REST auth failed: {e}")

    # ── Load blueprint once ──
    try:
        from trader_companion.prop_firm_manager import PropFirmManager
    except ImportError:
        from prop_firm_manager import PropFirmManager
    mgr = PropFirmManager()
    mgr.set_prop_firm(firm)
    blueprints = mgr.firm_blueprints.get(firm, {}).get("strategy_configs", {})

    # ── List all accounts ──
    accounts = conn._rest_get_accounts() or []
    print(f"\n  {'#':<3} {'ACCOUNT':<25} {'STATUS':<10} {'ACTIVE':<7} {'BALANCE':>12}")
    print(f"  {'-'*3} {'-'*25} {'-'*10} {'-'*7} {'-'*12}")
    candidates = []
    for i, a in enumerate(accounts, 1):
        name    = a.get("account_name", "?")
        status  = a.get("status", "?")
        active  = str(a.get("is_active", False))
        balance = float(a.get("available_balance") or a.get("balance") or 0)
        flag    = "← test" if status != "disabled" else "(disabled - still try)"
        print(f"  {i:<3} {name:<25} {status:<10} {active:<7} ${balance:>11,.2f}  {flag}")
        candidates.append((name, balance, status))   # include ALL accounts

    _info(f"\n  {len(candidates)} total account(s) to test: {[c[0] for c in candidates]}")

    if not auto:
        ans = input("\n  ⚠  Switch to each account and place a trade? (y/n): ").strip().lower()
        if ans != "y":
            _info("Skipped.")
            return

    results = []
    for acct_name, rest_balance, acct_status in candidates:
        _sep(f"  Account: {acct_name}  [{acct_status}]")

        # ── 1. Switch ──
        bal_before = conn.get_account_balance()
        switched   = conn.switch_account(acct_name)
        bal_after  = conn.get_account_balance()
        bal_changed = bal_before is not None and bal_after is not None and abs(bal_after - bal_before) > 0.01

        selector_text = driver.execute_script(
            "var w=document.querySelector('.accountSelectorWrapper');"
            " return w ? (w.innerText||w.textContent||'').trim().slice(0,80) : '';"
        ) or ""
        name_in_selector = acct_name.upper() in selector_text.upper()

        if switched and name_in_selector:
            _ok(f"  Switched ✅  selector={selector_text[:60]!r}")
            _ok(f"  Balance: ${bal_before:,.2f} → ${bal_after:,.2f}  {'(changed)' if bal_changed else '(same)'}")
        else:
            _fail(f"  Switch FAILED — not in selector: {selector_text[:60]!r}")
            results.append({
                "account": acct_name, "status": acct_status,
                "balance": f"${bal_before:,.2f} → N/A",
                "switch": "❌", "bracket": "skipped", "order": "skipped",
            })
            continue   # don't attempt trade on accounts we can't switch to

        # ── 2. Auto-detect size & blueprint ──
        size  = conn.get_account_size_label(firm) or "50k"
        cfg   = (blueprints.get("challenge_trade1") or {})
        phase_cfg = cfg.get(size) or cfg.get("50k", {})
        sym   = (phase_cfg.get("tradovate_symbol") or "NQU6").upper()
        qty   = int(phase_cfg.get("tradovate_qty") or 1)
        tp_t  = int(phase_cfg.get("tradovate_tp_ticks") or 202)
        sl_t  = int(phase_cfg.get("tradovate_sl_ticks") or 175)
        contract = _map_symbol(sym)
        tick_sz  = TICK_SIZE.get(contract, 0.25)
        _info(f"  Blueprint: size={size}  {contract} qty={qty}  TP={tp_t}t  SL={sl_t}t")

        # ── 3. Switch contract ──
        try:
            conn._switch_contract(contract)
            _ok(f"  Contract → {contract}")
        except Exception as e:
            _fail(f"  Contract switch failed: {e}")

        # ── 4. Set qty ──
        try:
            conn._set_qty(qty)
            _ok(f"  Qty={qty}")
        except Exception as e:
            _fail(f"  Set qty failed: {e}")

        # ── 5. Bracket ──
        entry = conn._get_current_price("sell") or 0.0
        if entry == 0.0:
            entry = 20000.0
            _info(f"  Market closed — dummy entry {entry}")
        tp_abs = round(round((entry - tp_t * tick_sz) / tick_sz) * tick_sz, 4)
        sl_abs = round(round((entry + sl_t * tick_sz) / tick_sz) * tick_sz, 4)
        _info(f"  Bracket: TP={tp_abs}  SL={sl_abs}")
        try:
            conn._configure_bracket(tp_abs, sl_abs)
            _ok("  Bracket set")
        except Exception as e:
            _fail(f"  Bracket failed: {e}")

        # Verify bracket inputs
        actual = driver.execute_script("""
            return Array.from(document.querySelectorAll(
                'input[type="number"][placeholder="0.00"]'
            )).filter(function(i) { return i.offsetParent !== null; })
              .map(function(i) { return parseFloat(i.value) || 0; });
        """) or []
        got_tp = actual[0] if len(actual) > 0 else None
        got_sl = actual[1] if len(actual) > 1 else None
        tp_ok  = got_tp is not None and abs(got_tp - tp_abs) < 0.01
        sl_ok  = got_sl is not None and abs(got_sl - sl_abs) < 0.01
        bracket_status = f"TP{'✅' if tp_ok else '❌'} SL{'✅' if sl_ok else '❌'}"
        _info(f"  Bracket readback: {actual}  {bracket_status}")

        # ── 6. Place order ──
        clicked = driver.execute_script("""
            var b = Array.from(document.querySelectorAll('button')).find(function(b) {
                var t = (b.innerText||'').toUpperCase();
                return t.includes('SELL') && t.includes('@ MARKET') && b.offsetParent !== null;
            });
            if (b) { b.click(); return (b.innerText||'').trim(); }
            return null;
        """)
        if clicked:
            _ok(f"  Order clicked: {clicked!r}")
        else:
            _fail("  SELL @ MARKET button not found")

        time.sleep(2.5)

        results.append({
            "account":  acct_name,
            "status":   acct_status,
            "balance":  f"${bal_before:,.2f} → ${bal_after:,.2f}",
            "switch":   "✅" if (switched and name_in_selector) else "❌",
            "bracket":  bracket_status,
            "order":    clicked or "NOT CLICKED",
        })

    # ── Summary ──
    _sep("Switch + Trade summary")
    print(f"\n  {'ACCOUNT':<25} {'S':<10} {'BALANCE CHANGE':<28} {'SW':<4} {'BRACKET':<14} ORDER")
    print(f"  {'-'*25} {'-'*10} {'-'*28} {'-'*4} {'-'*14} {'-'*20}")
    for r in results:
        print(f"  {r['account']:<25} {r.get('status',''):<10} {r['balance']:<28} "
              f"{r['switch']:<4} {r.get('bracket','skipped'):<14} {r.get('order','skipped')}")

    # ── Restore default ──
    if candidates:
        _info(f"\n  Restoring: {candidates[0][0]}")
        conn.switch_account(candidates[0][0])


def step_probe_switch_to_account(driver: webdriver.Chrome, email: str,
                                 password: str, target_account: str,
                                 firm: str = "AlphaFutures"):
    """
    Switch to a SPECIFIC account by name fragment and confirm the switch.
    Prints a full account list first, then switches to `target_account`,
    verifies the selector + balance update, and shows account stats.

    Usage: --probe switch-to --account ADVEV2026060800394
    """
    _sep(f"11 — Switch to specific account: {target_account!r}")

    from connectors.alphatrader_connector import AlphaTraderConnector

    conn = AlphaTraderConnector.__new__(AlphaTraderConnector)
    conn._driver        = driver
    conn._connected     = True
    conn._id_token      = None
    conn._refresh_token = None
    conn._token_exp     = 0
    conn._account_uuid  = None
    conn._account_name  = None
    conn.email          = email
    conn.password       = password

    try:
        conn._rest_login()
        _ok("REST auth OK")
    except Exception as e:
        _fail(f"REST auth failed: {e}")

    # ── List ALL accounts (context) ──
    accounts = conn._rest_get_accounts() or []
    print(f"\n  {'#':<3} {'ACCOUNT':<25} {'TYPE':<14} {'STATUS':<10} {'ACTIVE':<7} {'BALANCE':>12}")
    print(f"  {'-'*3} {'-'*25} {'-'*14} {'-'*10} {'-'*7} {'-'*12}")
    match = None
    for i, a in enumerate(accounts, 1):
        name    = a.get("account_name", "?")
        atype   = a.get("account_type", "?")
        status  = a.get("status", "?")
        active  = str(a.get("is_active", False))
        balance = float(a.get("available_balance") or a.get("balance") or 0)
        is_target = target_account.upper() in name.upper()
        marker  = " ◄ TARGET" if is_target else ""
        print(f"  {i:<3} {name:<25} {atype:<14} {status:<10} {active:<7} ${balance:>11,.2f}{marker}")
        if is_target and match is None:
            match = (name, balance, status)

    if not match:
        _fail(f"Account '{target_account}' not found in REST account list")
        return

    acct_name, rest_balance, acct_status = match
    _info(f"\n  Target resolved: {acct_name}  status={acct_status}  REST balance=${rest_balance:,.2f}")

    # ── Current state before switch ──
    bal_before = conn.get_account_balance()
    current_selector = driver.execute_script(
        "var w=document.querySelector('.accountSelectorWrapper');"
        " return w ? (w.innerText||w.textContent||'').trim().slice(0,80) : '';"
    ) or ""
    _info(f"  Current selector : {current_selector[:60]!r}")
    _info(f"  Current balance  : ${bal_before:,.2f}" if bal_before else "  Current balance : N/A")

    # ── Switch ──
    _info(f"\n  Switching → {acct_name} ...")
    switched = conn.switch_account(acct_name)
    bal_after = conn.get_account_balance()

    new_selector = driver.execute_script(
        "var w=document.querySelector('.accountSelectorWrapper');"
        " return w ? (w.innerText||w.textContent||'').trim().slice(0,80) : '';"
    ) or ""

    name_ok    = acct_name.upper() in new_selector.upper()
    balance_ok = bal_after is not None and abs((bal_after or 0) - rest_balance) < 10_000
    bal_changed = bal_before is not None and bal_after is not None and abs(bal_after - bal_before) > 0.01

    print(f"\n  {'Result':<18} {'Value'}")
    print(f"  {'-'*18} {'-'*50}")
    print(f"  {'switch_account()':<18} {'True ✅' if switched else 'False ❌'}")
    print(f"  {'Name in selector':<18} {'YES ✅' if name_ok else 'NO ❌'}  {new_selector[:60]!r}")
    print(f"  {'Balance before':<18} ${bal_before:,.2f}" if bal_before else f"  {'Balance before':<18} N/A")
    print(f"  {'Balance after':<18} ${bal_after:,.2f}  {'(changed ✅)' if bal_changed else '(same)'}"
          if bal_after else f"  {'Balance after':<18} N/A")
    print(f"  {'Balance vs REST':<18} {'matches ✅' if balance_ok else 'MISMATCH ❌'}")

    # ── Account stats ──
    stats = conn.get_account_stats()
    if stats:
        _info("\n  Account stats:")
        for k, v in stats.items():
            print(f"    {k:<20} {v}")

    overall = "✅ CONFIRMED" if (switched and name_ok and balance_ok) else "❌ NEEDS REVIEW"
    print(f"\n  Overall: {overall}")

    if not (switched and name_ok):
        # Try to restore original
        if current_selector:
            _info("  Restoring previous account...")
            conn._account_name = current_selector.split("\n")[0].strip()
            conn._select_ui_account()


def step_blueprint_trades(driver: webdriver.Chrome, firm: str = "AlphaFutures",
                          size: str = "auto", auto: bool = False):
    """
    Pull every phase config from PropFirmManager for `firm`, place a test order for
    each, then verify the AutoOCO bracket TP/SL inputs match the computed prices.

    size="auto" (default) reads the active account balance via REST and maps it
    to the nearest tier ("50k"/"100k"/"150k") automatically.
    """
    from connectors.alphatrader_connector import (
        AlphaTraderConnector, _map_symbol, TICK_SIZE
    )

    # ------------------------------------------------------------------
    # Auto-detect account size from live balance (DOM-based, no credentials)
    # ------------------------------------------------------------------
    conn = AlphaTraderConnector.__new__(AlphaTraderConnector)
    conn._driver        = driver
    conn._connected     = True
    conn._id_token      = None
    conn._refresh_token = None
    conn._token_exp     = 0
    conn._account_uuid  = None
    conn._account_name  = None
    conn.email          = ""

    detected_size = size
    if size == "auto":
        detected_size = conn.get_account_size_label(firm) or "50k"
        _info(f"  Auto-detected account size: {detected_size}")

    _sep(f"9 — Blueprint trade tests  ({firm} / {detected_size})")

    try:
        from trader_companion.prop_firm_manager import PropFirmManager
    except ImportError:
        from prop_firm_manager import PropFirmManager

    mgr = PropFirmManager()
    mgr.set_prop_firm(firm)
    blueprints = mgr.firm_blueprints.get(firm, {}).get("strategy_configs", {})

    if not blueprints:
        _fail(f"No blueprints found for '{firm}'")
        return

    # Show full table first
    print(f"\n  {'PHASE':<30} {'SYM':<8} {'QTY':>4} {'TP':>6} {'SL':>6}")
    print(f"  {'-'*30} {'-'*8} {'-'*4} {'-'*6} {'-'*6}")
    rows = []
    for phase_key, sizes_map in sorted(blueprints.items()):
        cfg = sizes_map.get(detected_size) or sizes_map.get("50k", {})
        sym = (cfg.get("tradovate_symbol") or cfg.get("topstepx_symbol", "")).upper()
        qty = int(cfg.get("tradovate_qty") or cfg.get("topstepx_qty", 1))
        tp  = int(cfg.get("tradovate_tp_ticks") or cfg.get("topstepx_tp_ticks", 0))
        sl  = int(cfg.get("tradovate_sl_ticks") or cfg.get("topstepx_sl_ticks", 0))
        print(f"  {phase_key:<30} {sym:<8} {qty:>4} {tp:>6} {sl:>6}")
        rows.append((phase_key, sym, qty, tp, sl))

    if not auto:
        ans = input("\n  ⚠  Run all blueprint trades on sim account? (y/n): ").strip().lower()
        if ans != "y":
            _info("Skipped.")
            return

    results = []
    for phase_key, sym, qty, tp_ticks, sl_ticks in rows:
        contract = _map_symbol(sym)
        tick_size = TICK_SIZE.get(contract, 0.25)
        side = "sell"  # always sell for sim test

        _sep(f"  {phase_key}")
        _info(f"  Symbol={contract}  qty={qty}  TP={tp_ticks}t  SL={sl_ticks}t  side={side}")

        try:
            # 1. Switch contract
            conn._switch_contract(contract)
            _ok(f"  Switched to {contract}")

            # 2. Set qty
            conn._set_qty(qty)
            _ok(f"  Qty={qty}")

            # 3. Get entry price (sim = $0.00, so use realistic dummy to verify maths)
            entry = conn._get_current_price(side) or 0.0
            if entry == 0.0:
                entry = 20000.0  # dummy for bracket verification
                _info(f"  Market closed — using dummy entry {entry} for TP/SL calc")

            tp_abs = round(round((entry - tp_ticks * tick_size) / tick_size) * tick_size, 4)
            sl_abs = round(round((entry + sl_ticks * tick_size) / tick_size) * tick_size, 4)
            _info(f"  Expected bracket: TP={tp_abs}  SL={sl_abs}")

            # 4. Configure bracket
            conn._configure_bracket(tp_abs, sl_abs)
            _ok(f"  Bracket configured")

            # 5. Read back actual bracket input values
            actual = driver.execute_script("""
                var inputs = Array.from(document.querySelectorAll(
                    'input[type="number"][placeholder="0.00"]'
                )).filter(function(i) {
                    return i.offsetParent !== null;
                });
                return inputs.map(function(i) {
                    return parseFloat(i.value) || 0;
                });
            """) or []
            got_tp = actual[0] if len(actual) > 0 else None
            got_sl = actual[1] if len(actual) > 1 else None
            _info(f"  Bracket inputs read back: {actual}")

            tp_ok = got_tp is not None and abs(got_tp - tp_abs) < 0.01
            sl_ok = got_sl is not None and abs(got_sl - sl_abs) < 0.01
            bracket_status = ("TP✅ SL✅" if (tp_ok and sl_ok)
                              else f"TP{'✅' if tp_ok else '❌'} SL{'✅' if sl_ok else '❌'}")
            if not (tp_ok and sl_ok):
                _fail(f"  Bracket mismatch — expected TP={tp_abs} SL={sl_abs} got {actual}")

            # 6. Click SELL @ MARKET
            clicked = driver.execute_script("""
                var b = Array.from(document.querySelectorAll('button')).find(function(b) {
                    var t = (b.innerText||'').toUpperCase();
                    return t.includes('SELL') && t.includes('@ MARKET') && b.offsetParent !== null;
                });
                if (b) { b.click(); return (b.innerText||'').trim(); }
                return null;
            """)
            if clicked:
                _ok(f"  Clicked: {clicked!r}")
            else:
                _fail(f"  SELL @ MARKET button not found")

            time.sleep(2.5)

            results.append({
                "phase": phase_key, "symbol": contract, "qty": qty,
                "tp_ticks": tp_ticks, "sl_ticks": sl_ticks,
                "expected_tp": tp_abs, "expected_sl": sl_abs,
                "got_tp": got_tp, "got_sl": got_sl,
                "bracket": bracket_status,
                "order": clicked or "NOT CLICKED",
            })

        except Exception as e:
            _fail(f"  {phase_key} FAILED: {e}")
            results.append({"phase": phase_key, "symbol": contract, "bracket": "ERROR", "order": str(e)})
            # ESC to close any open dropdown
            try:
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
            except Exception:
                pass
            time.sleep(0.5)

    # Summary table
    _sep("Blueprint trade summary")
    print(f"\n  {'PHASE':<30} {'SYM':<6} {'QTY':>4} {'BRACKET':<14} {'ORDER'}")
    print(f"  {'-'*30} {'-'*6} {'-'*4} {'-'*14} {'-'*25}")
    for r in results:
        print(f"  {r['phase']:<30} {r.get('symbol',''):<6} "
              f"{r.get('qty',0):>4} {r.get('bracket','?'):<14} {r.get('order','?')}")


def step_probe_all_symbols(driver: webdriver.Chrome):
    """
    Open the CONTRACTS dropdown and list every available symbol.
    Then cycle through a selection of them, confirming each switch,
    without placing any orders.
    """
    _sep("8 — All available symbols + cycle test")

    from connectors.alphatrader_connector import AlphaTraderConnector, CONTRACT_DISPLAY
    conn = AlphaTraderConnector.__new__(AlphaTraderConnector)
    conn._driver    = driver
    conn._connected = True

    # ── Step A: open the dropdown and collect ALL options ──
    _info("Opening CONTRACTS dropdown to enumerate all symbols...")

    # Find the CONTRACTS react-select control via label proximity
    labels = driver.find_elements(
        By.XPATH,
        '//label[normalize-space(.)="CONTRACTS" or normalize-space(.)="Contracts"]'
    )
    ctrl_el = None
    for lbl in labels:
        try:
            parent = lbl.find_element(By.XPATH, "..")
            candidates = parent.find_elements(By.CSS_SELECTOR, '[class*="-control"]')
            visible = [c for c in candidates if c.is_displayed()]
            if visible:
                ctrl_el = visible[0]
                break
        except Exception:
            pass

    if not ctrl_el:
        _fail("CONTRACTS react-select control not found — is Trade Panel open?")
        return []

    ctrl_el.click()
    time.sleep(0.9)

    # Collect all options
    all_options = []
    for css in ('[role="option"]', '[class*="-option"]'):
        found = [e for e in driver.find_elements(By.CSS_SELECTOR, css) if e.is_displayed()]
        if found:
            all_options = found
            break

    if not all_options:
        _fail("No options appeared after opening CONTRACTS dropdown")
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        return []

    names = []
    for opt in all_options:
        txt = opt.text.strip()
        if txt:
            names.append(txt)

    _ok(f"Found {len(names)} contracts in dropdown:")
    for i, n in enumerate(names, 1):
        print(f"    {i:3d}.  {n}")

    # Close the dropdown
    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    time.sleep(0.3)

    # ── Step B: pick a diverse sample and switch to each ──
    # Prefer variety: pick ~6 evenly spread across the list
    n = len(names)
    if n == 0:
        return []
    sample_indices = sorted(set([
        0, n // 5, n * 2 // 5, n * 3 // 5, n * 4 // 5, n - 1
    ]))
    sample = [names[i] for i in sample_indices if i < n]

    _sep("8b — Cycle through sample symbols")
    _info(f"Testing {len(sample)} symbols: {sample}")

    results = []
    for display_name in sample:
        _info(f"  → Switching to: {display_name!r}")
        try:
            # Open dropdown via label proximity
            ctrl_el = None
            for lbl in driver.find_elements(
                By.XPATH,
                '//label[normalize-space(.)="CONTRACTS" or normalize-space(.)="Contracts"]'
            ):
                try:
                    parent = lbl.find_element(By.XPATH, "..")
                    candidates = parent.find_elements(By.CSS_SELECTOR, '[class*="-control"]')
                    visible_c = [c for c in candidates if c.is_displayed()]
                    if visible_c:
                        ctrl_el = visible_c[0]
                        break
                except Exception:
                    pass

            if not ctrl_el:
                _fail(f"    Control not found for {display_name!r}")
                results.append((display_name, "FAIL: no control"))
                continue

            ctrl_el.click()
            time.sleep(0.8)

            # Find and click matching option
            opted = False
            for css in ('[role="option"]', '[class*="-option"]'):
                opts = [e for e in driver.find_elements(By.CSS_SELECTOR, css) if e.is_displayed()]
                for opt in opts:
                    if opt.text.strip() == display_name:
                        opt.click()
                        opted = True
                        break
                if opted:
                    break

            if not opted:
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                results.append((display_name, "FAIL: option not found"))
                _fail(f"    Option not found: {display_name!r}")
                continue

            time.sleep(0.6)

            # Verify CONTRACTS field
            cur = driver.execute_script("""
                var lbl = Array.from(document.querySelectorAll('label'))
                    .find(l => (l.innerText||l.textContent).trim().toUpperCase()==='CONTRACTS');
                if (!lbl) return '';
                var p = lbl.parentElement;
                if (!p) return '';
                var els = Array.from(p.querySelectorAll('*'));
                for (var el of els) {
                    if (el.children.length===0 && el.offsetParent!==null) {
                        var t=(el.innerText||el.textContent).trim();
                        if (t && t.toUpperCase()!=='CONTRACTS') return t;
                    }
                }
                return '';
            """) or ""

            if display_name.upper() in cur.upper():
                _ok(f"    ✓ {display_name!r}  →  CONTRACTS shows: {cur!r}")
                results.append((display_name, "OK"))
            else:
                _fail(f"    ✗ expected {display_name!r}, got {cur!r}")
                results.append((display_name, f"MISMATCH: {cur!r}"))

        except Exception as e:
            _fail(f"    Exception: {e}")
            results.append((display_name, f"ERROR: {e}"))

    _sep("Symbol cycle summary")
    for name, status in results:
        mark = "✅" if status == "OK" else "❌"
        print(f"  {mark}  {name!r}  →  {status}")

    return names


def step_place_order(
    driver: webdriver.Chrome,
    side: str,
    qty: int,
    tp_ticks: int | None,
    sl_ticks: int | None,
    auto: bool = False,
    symbol: str = "NQ",
) -> bool:
    _sep(f"5 — Place order  ({side.upper()} {qty} {symbol}  TP={tp_ticks}t  SL={sl_ticks}t)")

    if not auto:
        ans = input("\n  ⚠  About to place a REAL order. Continue? (y/n): ").strip().lower()
        if ans != "y":
            _info("Skipped by user.")
            return False

    # Use the fixed connector methods directly
    from connectors.alphatrader_connector import AlphaTraderConnector, _map_symbol, TICK_SIZE
    import types

    # Create a minimal stub connector that points at our open driver
    conn = AlphaTraderConnector.__new__(AlphaTraderConnector)
    conn._driver    = driver
    conn._connected = True
    conn._account_name = None

    contract = _map_symbol(symbol)
    tick_size = TICK_SIZE.get(contract, 0.25)

    # --- switch contract ---
    _info(f"Switching contract to {symbol} ({contract})...")
    try:
        conn._switch_contract(contract)
        _ok("Contract switched")
    except Exception as e:
        _fail(f"Contract switch: {e}")

    time.sleep(0.5)

    # --- set qty ---
    _info(f"Setting qty={qty}...")
    conn._set_qty(qty)
    _ok(f"Qty set")

    # --- configure bracket ---
    if tp_ticks or sl_ticks:
        entry = conn._get_current_price(side.lower()) or 20000.0
        _info(f"Entry price: {entry}")
        tp_abs = None
        sl_abs = None
        if side.lower() == "buy":
            if tp_ticks: tp_abs = round((entry + tp_ticks * tick_size) / tick_size) * tick_size
            if sl_ticks: sl_abs = round((entry - sl_ticks * tick_size) / tick_size) * tick_size
        else:
            if tp_ticks: tp_abs = round((entry - tp_ticks * tick_size) / tick_size) * tick_size
            if sl_ticks: sl_abs = round((entry + sl_ticks * tick_size) / tick_size) * tick_size
        _info(f"TP={tp_abs}  SL={sl_abs}")
        conn._configure_bracket(tp_abs, sl_abs)
        _ok("Bracket configured")
    else:
        conn._disable_bracket()

    time.sleep(0.3)

    # --- click BUY/SELL @ MARKET ---
    kw = "BUY" if side.lower() == "buy" else "SELL"
    result = driver.execute_script(f"""
        var kw = '{kw}';
        var b = Array.from(document.querySelectorAll('button')).find(function(b) {{
            var t = (b.innerText||'').toUpperCase();
            return t.includes(kw) && t.includes('@ MARKET') && b.offsetParent !== null;
        }});
        if (b) {{ b.click(); return (b.innerText||'').trim(); }}
        return null;
    """)
    if result:
        _ok(f"Clicked: {result!r}")
        time.sleep(2.5)
        return True
    else:
        _fail(f"No '{kw} @ MARKET' button found")
        return False


# ── main ──────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email",    default=EMAIL, help="AlphaTrader account email")
    ap.add_argument("--password", default=None,  help="AlphaTrader password (for re-login if session expired)")
    ap.add_argument("--symbol",   default="NQ", help="Symbol to trade (e.g. NQ, MNQ, ES)")
    ap.add_argument("--side",     choices=["buy", "sell"], help="Order side")
    ap.add_argument("--qty",      type=int, default=1, help="Qty (contracts)")
    ap.add_argument("--tp",       type=int, default=None, help="TP in ticks")
    ap.add_argument("--sl",       type=int, default=None, help="SL in ticks")
    ap.add_argument("--auto",     action="store_true", help="Skip confirmation prompts")
    ap.add_argument("--keep-open", type=int, default=30, dest="keep_open",
                    help="Seconds to keep browser open after --auto order (default 30)")
    ap.add_argument("--probe",    choices=["dom", "accounts", "switch", "switch-to", "trade-accounts", "contracts", "symbols", "blueprint", "all"],
                    default=None, help="Probes: switch=all accounts, switch-to=specific account (requires --account), trade-accounts=switch+trade all")
    ap.add_argument("--account",  default=None,
                    help="Account name fragment for --probe switch-to (e.g. ADVEV2026060800394)")
    args = ap.parse_args()

    email = args.email
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", email)
    profile_dir = os.path.join(tempfile.gettempdir(), "alphatrader_profiles", safe)

    _sep("AlphaTrader probe")
    _info(f"Profile : {profile_dir}")
    _info(f"Profile exists: {os.path.isdir(profile_dir)}")

    # Temporarily point the module-level globals so _open_chrome() picks them up
    global PROFILE_DIR
    PROFILE_DIR = profile_dir

    driver = _open_chrome()
    try:
        _info(f"Navigating to {PLATFORM_URL} ...")
        driver.get(PLATFORM_URL)

        _info("Waiting for platform to load (30s)...")
        ready = _wait_platform(driver, timeout=30)

        # Auto-login if the session expired and a password was supplied
        if not ready or "/signin" in driver.current_url or "login" in driver.current_url.lower():
            if args.password:
                _info("Session expired — filling login form automatically...")
                try:
                    wait = WebDriverWait(driver, 20)
                    ef = wait.until(EC.presence_of_element_located(
                        (By.CSS_SELECTOR, 'input[placeholder="Email"], input[type="email"]')))
                    ef.clear()
                    ef.send_keys(email)
                    pf = driver.find_element(
                        By.CSS_SELECTOR, 'input[placeholder="Password"], input[type="password"]')
                    pf.clear()
                    pf.send_keys(args.password)
                    btn = driver.find_element(
                        By.XPATH, '//button[normalize-space()="Login" or normalize-space()="Sign In"]')
                    btn.click()
                    _info("Login submitted — waiting for platform...")
                    ready = _wait_platform(driver, timeout=30)
                    if ready:
                        _ok("Logged in successfully")
                    else:
                        _fail("Login may have failed — check the browser window")
                except Exception as e:
                    _fail(f"Auto-login failed: {e}")
            else:
                _fail("Session expired and no --password given")
                _info("Fill in credentials manually in the browser, then press Enter.")
                if not args.auto:
                    input("  Press Enter once logged in...")
                    ready = _wait_platform(driver, 10)
        
        if ready:
            _ok("Platform loaded")
        else:
            _fail("Platform did not fully load")

        if not step_page_info(driver):
            _info("Session may have expired.")
            if not args.auto:
                input("  Log in manually then press Enter...")
                step_page_info(driver)

        time.sleep(1)
        step_dom_snapshot(driver)
        step_click_layouts(driver)
        step_ensure_order_panel(driver)

        if not args.side:
            # Diagnostic: probe specific area or run contract dropdown probe
            if args.probe in ("dom", "all"):
                step_probe_dom_panel(driver)
            if args.probe in ("accounts", "all"):
                step_probe_account_switcher(driver)
            if args.probe in ("switch", "all"):
                step_probe_account_switch(driver, email=email, password=args.password or "")
            if args.probe in ("switch-to",):
                if not args.account:
                    _fail("--probe switch-to requires --account ACCOUNT_NAME")
                else:
                    step_probe_switch_to_account(driver, email=email, password=args.password or "",
                                                 target_account=args.account)
            if args.probe in ("trade-accounts",):
                step_probe_switch_and_trade(driver, email=email, password=args.password or "",
                                            auto=args.auto, firm="AlphaFutures")
            if args.probe in ("symbols", "all"):
                step_probe_all_symbols(driver)
            if args.probe in ("blueprint",):
                step_blueprint_trades(driver, firm="AlphaFutures", size="auto", auto=args.auto)
            if args.probe in ("contracts", "all", None):
                step_probe_contracts_dropdown(driver)
            _sep("No --side given — diagnostics complete, browser stays open")
            if not args.auto:
                input("\n  Press Enter to close browser...")
        else:
            step_place_order(driver, args.side, args.qty, args.tp, args.sl, args.auto, args.symbol)

    finally:
        if args.auto:
            time.sleep(args.keep_open)
        driver.quit()
        _ok("Browser closed.")


if __name__ == "__main__":
    main()
