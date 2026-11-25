"""MasterMail entry point.

    python main.py              open the desktop app (native window)
    python main.py --browser    open the UI in the default browser instead
    python main.py --serve      only run the local server (prints its URL)
    python main.py --version
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import traceback
import webbrowser


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="MasterMail")
    p.add_argument("--browser", action="store_true", help="open in the default browser")
    p.add_argument("--serve", action="store_true", help="run the server only")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--token", default=None)
    p.add_argument("--version", "-V", action="store_true")
    return p.parse_args()


def _app_mode_browser(url: str) -> subprocess.Popen | None:
    """Edge / Chrome in --app mode: a chrome-less window that looks native."""
    candidates = []
    if sys.platform == "win32":
        pf = [os.environ.get(k, "") for k in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
        for base in filter(None, pf):
            candidates += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                           os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    else:
        candidates += [shutil.which(n) or "" for n in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser")]
        candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    for exe in candidates:
        if exe and os.path.isfile(exe):
            try:
                return subprocess.Popen([exe, f"--app={url}", "--window-size=1320,880"])
            except OSError:
                continue
    return None


def main() -> int:
    args = _parse()
    from mastermail import APP_NAME, APP_NAME_FA, POWERED_BY, __version__

    if args.version:
        print(f"{APP_NAME} {__version__} — {POWERED_BY}")
        return 0

    from mastermail.server import AppServer
    from mastermail.service import Service

    svc = Service()
    server = AppServer(svc, port=args.port, token=args.token).start()

    if args.serve:
        print(server.url, flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    if not args.browser:
        try:
            import webview  # type: ignore

            window = webview.create_window(
                f"{APP_NAME_FA} — {APP_NAME}", server.url, width=1320, height=880,
                min_size=(1080, 720), background_color="#F5F5F7", text_select=True,
            )

            def dialogs(kind: str, opts: dict):
                dialog = webview.FOLDER_DIALOG if kind == "folder" else webview.OPEN_DIALOG
                result = window.create_file_dialog(dialog)
                return result[0] if result else ""

            svc.native_dialogs = dialogs
            webview.start(gui="edgechromium" if sys.platform == "win32" else None, debug=False)
            return 0
        except Exception:  # noqa: BLE001 - fall back to an app-mode browser window
            traceback.print_exc()

    proc = _app_mode_browser(server.url)
    if proc is None:
        webbrowser.open(server.url)
        print(f"{APP_NAME} is running at {server.url}  (Ctrl+C to quit)")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0
    # Keep serving while the app window is open.
    opened = time.monotonic()
    while proc.poll() is None:
        time.sleep(1)
    # A browser that was already running takes the window over and the launcher
    # exits at once; then we cannot tell when the window closes, so keep serving.
    if time.monotonic() - opened < 8:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        try:
            import ctypes

            if sys.platform == "win32":
                ctypes.windll.user32.MessageBoxW(0, traceback.format_exc()[-1500:], "MasterMail", 0x10)
        except Exception:  # noqa: BLE001
            pass
        raise SystemExit(1)
