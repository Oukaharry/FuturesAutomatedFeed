"""Live check: log into Tradovate with dashboard creds, stream NQ M1 bars.

Usage: python scripts/test_tradovate_md.py [prop_firm] [email]
Defaults: Tradeify, harryodhiambo16@gmail.com. Prints bar summary; never prints
credentials or tokens.
"""

import json
import sys
import time

import requests

sys.path.insert(0, ".")

from trader_companion.tradovate_md_feed import front_quarter_symbol, parse_chart_bars  # noqa: E402

FIRM = sys.argv[1] if len(sys.argv) > 1 else "Tradeify"
EMAIL = sys.argv[2] if len(sys.argv) > 2 else "harryodhiambo16@gmail.com"


def fetch_creds():
    for attempt in range(3):
        try:
            d = requests.post(
                "https://www.tradeopss.com/api/client/data",
                json={"email": EMAIL},
                headers={"X-Companion-Version": "1.12.5"}, timeout=40).json()
            break
        except Exception as exc:
            print(f"dashboard retry {attempt + 1}: {exc.__class__.__name__}")
            time.sleep(5)
    else:
        raise SystemExit("dashboard unreachable")
    for p in d.get("prop_accounts", []):
        if p.get("prop_firm", "").strip().lower() == FIRM.strip().lower():
            u, pw = p.get("tradovate_username"), p.get("tradovate_password")
            if u and pw:
                return u, pw
    raise SystemExit(f"no Tradovate creds for {FIRM}")


def browser_token(username, password):
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    opts = webdriver.ChromeOptions()
    opts.add_argument("--window-size=1280,900")
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    driver = webdriver.Chrome(options=opts)
    try:
        driver.get("https://trader.tradovate.com/welcome")
        user_el = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.ID, "name-input")))
        pass_el = driver.find_element(By.ID, "password-input")
        user_el.click(); user_el.clear(); user_el.send_keys(username)
        time.sleep(0.3)
        pass_el.click(); pass_el.clear(); pass_el.send_keys(password)
        time.sleep(0.5)
        btn = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, "//button[.//span[text()='Login']]")))
        driver.execute_script("arguments[0].click();", btn)
        print("login submitted — waiting for session token…")

        deadline = time.time() + 90
        while time.time() < deadline:
            res = driver.execute_script(
                "try { var a = JSON.parse(sessionStorage.getItem("
                "'api_authenticator_state')||'{}');"
                " return [a.token||'', a.environment||'demo',"
                " Object.keys(a).join(',')]; }"
                " catch(e) { return ['', 'demo', '']; }")
            if res and res[0]:
                print(f"✅ token acquired (len={len(res[0])}, env={res[1]})")
                return driver, str(res[0]), str(res[1] or "demo")
            errs = driver.find_elements(By.CSS_SELECTOR, "[class*='error'], .alert")
            for e in errs:
                if e.text.strip():
                    print("page message:", e.text.strip()[:200])
            time.sleep(2)
        raise SystemExit("no token after 90s — login may need manual help (captcha/2FA?)")
    except BaseException:
        driver.quit()
        raise


def launch_sim_and_spy(driver, seconds=40):
    """Enter Simulation and report which WebSockets the real app opens."""
    from selenium.webdriver.common.by import By

    clicked = False
    for _ in range(20):
        for xp in ("//button[.//span[contains(text(),'Launch')]]",
                   "//button[contains(.,'Launch')]",
                   "//*[contains(@class,'simulation')]//button"):
            els = driver.find_elements(By.XPATH, xp)
            if els:
                driver.execute_script("arguments[0].click();", els[0])
                clicked = True
                break
        if clicked:
            break
        time.sleep(1.5)
    print(f"simulation launch clicked: {clicked} — watching network {seconds}s…")

    sockets, frames = {}, []
    end = time.time() + seconds
    while time.time() < end:
        for entry in driver.get_log("performance"):
            try:
                m = json.loads(entry["message"])["message"]
            except Exception:
                continue
            method, params = m.get("method"), m.get("params", {})
            if method == "Network.webSocketCreated":
                sockets[params.get("requestId")] = params.get("url")
                print("WS opened:", params.get("url"))
            elif method == "Network.webSocketFrameSent":
                payload = (params.get("response") or {}).get("payloadData", "")
                head = payload.split("\n")[0][:60]
                if head and head not in ("[]",) and len(frames) < 40:
                    frames.append((sockets.get(params.get("requestId"), "?"), head))
        time.sleep(2)
    print("\nsent frame heads by socket:")
    seen = set()
    for url, head in frames:
        key = (url, head)
        if key in seen:
            continue
        seen.add(key)
        print(f"  {url} ← {head!r}")
    return sockets


def md_token_for(token, env):
    """Exchange the web session token for a market-data token via renew."""
    host = "live" if env == "live" else "demo"
    r = requests.get(f"https://{host}.tradovateapi.com/v1/auth/renewaccesstoken",
                     headers={"Authorization": f"Bearer {token}"}, timeout=20)
    j = r.json()
    md = j.get("mdAccessToken")
    print(f"renewaccesstoken → {r.status_code}, hasMarketData={j.get('hasMarketData')}, "
          f"org={j.get('orgName')!r}, apiHosts={j.get('apiHosts')}, "
          f"mdAccessToken: {'yes (len=%d)' % len(md) if md else 'no'}")
    hosts = []
    for h in (j.get("apiHosts") or []):
        h = str(h).strip()
        if h and ("md" in h.split(".")[0] or "market" in h):
            hosts.append(h)
    return md or j.get("accessToken") or token, hosts


def stream_bars(token, env, host_candidates=()):
    import websocket

    symbol = front_quarter_symbol("NQ")
    defaults = ["md.tradovateapi.com"] if env == "live" else ["md-demo.tradovateapi.com"]
    for host in list(host_candidates) + defaults:
        bars = _stream_one(token, host, symbol)
        if bars:
            return bars
    return {}


def _stream_one(token, host, symbol):
    import websocket

    print(f"connecting wss://{host} for {symbol} …")
    try:
        ws = websocket.create_connection(f"wss://{host}/v1/websocket", timeout=30)
    except Exception as exc:
        print(f"  connect failed: {exc}")
        return {}
    rid = 0
    auth_id = chart_req = None
    bars = {}
    deadline = time.time() + 45

    def send(ep, body=None, query="", raw=None):
        nonlocal rid
        rid += 1
        frame = f"{ep}\n{rid}\n{query}\n"
        if raw is not None:
            frame += raw
        elif body is not None:
            frame += json.dumps(body)
        ws.send(frame)
        return rid

    try:
        while time.time() < deadline:
            raw = ws.recv()
            if isinstance(raw, bytes):
                raw = raw.decode()
            if not raw:
                continue
            kind, payload = raw[0], raw[1:]
            if kind == "o":
                auth_id = send("authorize", raw=token)
            elif kind == "h":
                ws.send("[]")
            elif kind == "c":
                print("server closed connection")
                break
            elif kind == "a":
                for msg in json.loads(payload):
                    if msg.get("i") == auth_id:
                        print("authorize →", msg.get("s"), msg.get("d") or "")
                        if msg.get("s") == 200:
                            chart_req = send("md/getchart", body={
                                "symbol": symbol,
                                "chartDescription": {
                                    "underlyingType": "MinuteBar", "elementSize": 1,
                                    "elementSizeUnit": "UnderlyingUnits",
                                    "withHistogram": False},
                                "timeRange": {"asMuchAsElements": 300}})
                        else:
                            return bars
                    elif msg.get("i") == chart_req:
                        print("md/getchart →", msg.get("s"), msg.get("d") or "")
                    elif msg.get("e") == "chart":
                        for b in parse_chart_bars(msg.get("d") or {}):
                            bars[b["time"]] = b
                        if len(bars) >= 250:
                            return bars
                    elif msg.get("e"):
                        print("event:", msg.get("e"), str(msg.get("d"))[:120])
    finally:
        try:
            ws.close()
        except Exception:
            pass
    return bars


def main():
    username, password = fetch_creds()
    print(f"using {FIRM} Tradovate login {username!r}")
    driver, token, env = browser_token(username, password)
    try:
        launch_sim_and_spy(driver)
        md_tok, md_hosts = md_token_for(token, env)
        bars = stream_bars(md_tok, env, md_hosts)
    finally:
        driver.quit()
    print(f"\n📊 bars received: {len(bars)}")
    if bars:
        from datetime import datetime, timezone
        ts = sorted(bars)
        fmt = lambda t: datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        print("first:", fmt(ts[0]), bars[ts[0]])
        print("last: ", fmt(ts[-1]), bars[ts[-1]])
        print("\n✅ Tradovate market data confirmed — the companion feed will work.")
    else:
        print("\n⚠ no bars — check authorize status above")


if __name__ == "__main__":
    main()
