"""Closing the companion must take the Breakout plain-Chrome window with it."""
import json
from unittest.mock import patch

from trader_companion import breakout_probe as probe
from trader_companion.breakout_connector import BreakoutSession


class _FakeWS:
    sent = []

    def send(self, payload):
        _FakeWS.sent.append(json.loads(payload))

    def close(self):
        pass


def test_quit_chrome_sends_browser_close_over_cdp(monkeypatch):
    _FakeWS.sent = []
    alive = iter([True, False])
    monkeypatch.setattr(probe, "_cdp_alive", lambda port=None: next(alive, False))

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"webSocketDebuggerUrl": "ws://localhost:9412/devtools/browser/x"}).encode()

    monkeypatch.setattr(probe.urllib.request, "urlopen", lambda *a, **k: _Resp())
    import websocket
    monkeypatch.setattr(websocket, "create_connection", lambda *a, **k: _FakeWS())
    pkills = []
    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **k: pkills.append(a))

    assert probe.quit_chrome(9412) is True
    assert _FakeWS.sent == [{"id": 1, "method": "Browser.close"}]
    assert pkills == []  # Chrome went away politely — no kill needed


def test_quit_chrome_falls_back_to_pkill_when_chrome_ignores_close(monkeypatch):
    alive = iter([True, True, False])  # initial, one loop probe, post-pkill
    monkeypatch.setattr(probe, "_cdp_alive", lambda port=None: next(alive, False))
    monkeypatch.setattr(probe.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    monkeypatch.setattr(probe.time, "sleep", lambda s: None)
    monkeypatch.setattr(probe.time, "time", iter([0, 0, 10, 10]).__next__)
    pkills = []
    monkeypatch.setattr(probe.subprocess, "run", lambda cmd, **k: pkills.append(cmd))

    assert probe.quit_chrome(9412) is True
    assert pkills == [["pkill", "-f", "--remote-debugging-port=9412"]]


def test_session_close_quits_its_chrome(monkeypatch):
    sess = BreakoutSession.__new__(BreakoutSession)
    sess.api = None
    sess.port = 9433
    quit_ports = []
    monkeypatch.setattr(probe, "quit_chrome", lambda port=None, **k: quit_ports.append(port) or True)

    sess.close()

    assert quit_ports == [9433]
