"""
Auto-reload launcher for mt5_recovery_gui.py.

Watches scripts/mt5_recovery_gui.py and scripts/debug_mt5_positions.py for
changes. When either file is saved, the GUI process is killed and restarted
automatically so you never have to close and reopen it manually.

Usage:
    python scripts/run_gui.py
"""

import sys
import os
import subprocess
import time
import signal

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

WATCH_FILES = {
    os.path.abspath(os.path.join(os.path.dirname(__file__), 'mt5_recovery_gui.py')),
    os.path.abspath(os.path.join(os.path.dirname(__file__), 'debug_mt5_positions.py')),
}
GUI_SCRIPT = os.path.abspath(os.path.join(os.path.dirname(__file__), 'mt5_recovery_gui.py'))


class ChangeHandler(FileSystemEventHandler):
    def __init__(self, restart_cb):
        self._restart_cb = restart_cb
        self._last_trigger = 0

    def on_modified(self, event):
        if os.path.abspath(event.src_path) in WATCH_FILES:
            now = time.time()
            if now - self._last_trigger > 1.0:   # debounce 1 s
                self._last_trigger = now
                print(f"[run_gui] Change detected in {os.path.basename(event.src_path)} — restarting...")
                self._restart_cb()


def start_gui():
    return subprocess.Popen([sys.executable, GUI_SCRIPT])


def main():
    proc = start_gui()
    print(f"[run_gui] Started GUI (pid {proc.pid})")

    def restart():
        nonlocal proc
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        time.sleep(0.3)
        proc = start_gui()
        print(f"[run_gui] Restarted GUI (pid {proc.pid})")

    watch_dir = os.path.dirname(GUI_SCRIPT)
    handler = ChangeHandler(restart)
    observer = Observer()
    observer.schedule(handler, watch_dir, recursive=False)
    observer.start()
    print(f"[run_gui] Watching {watch_dir} for changes. Press Ctrl+C to quit.")

    try:
        while True:
            time.sleep(1)
            if proc.poll() is not None:
                # GUI was closed by the user — exit the launcher too
                print("[run_gui] GUI closed. Exiting.")
                break
    except KeyboardInterrupt:
        print("\n[run_gui] Interrupted.")
    finally:
        observer.stop()
        observer.join()
        if proc.poll() is None:
            proc.terminate()


if __name__ == '__main__':
    main()
