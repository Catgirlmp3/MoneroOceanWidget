"""MoneroOcean hashrate tray icon for the Windows notification area.

A system-tray icon that shows the wallet's current hashrate, with the exact
value in the tooltip and right-click menu. Polls every 60 seconds.
"""

import ctypes
import os
import sys
import threading
import webbrowser
import winreg
from datetime import datetime
from pathlib import Path

import pystray
from PIL import Image, ImageDraw, ImageFont
from pystray import Menu, MenuItem

import monero_hashrate as api

APP_NAME = "MoneroOceanHashrate"
MUTEX_NAME = "Local\\MoneroOceanHashrateTray"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REFRESH_SECONDS = 60
DASHBOARD_URL = "https://moneroocean.stream/#/wallet/{wallet}/overview?window=all&mode=xmr&view=list&sort=name&dir=asc"
FONT_PATH = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "ARIALNB.TTF"
FALLBACK_FONT_PATH = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeuib.ttf"

_state = {
    "full": "loading...",
    "compact": "...",
    "ok": False,
    "error": "",
    "value": None,
    "checked_at": None,
}
_state_lock = threading.Lock()
_icon = None
_mutex = None


def log(message):
    try:
        folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MoneroOceanWidget"
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / "tray.log", "a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
    except OSError:
        pass


def hashrate_color(value):
    """Background colour for a hashrate in H/s, interpolated between anchors."""
    kh = value / 1000.0
    anchors = [
        (0.0, (255, 0, 0)),      # red = weakest
        (8.0, (255, 0, 0)),      # red until 8 kH/s
        (9.0, (255, 165, 0)),    # gradient red -> orange
        (10.0, (0, 0, 0)),       # gradient orange -> black at 10 kH/s
        (15.0, (201, 167, 255)),  # gradient black -> light purple
        (20.0, (255, 158, 207)),  # gradient light purple -> pink
    ]

    if kh <= anchors[0][0]:
        return anchors[0][1]
    for (low, low_color), (high, high_color) in zip(anchors, anchors[1:]):
        if kh <= high:
            t = (kh - low) / (high - low)
            return tuple(
                round(a + (b - a) * t) for a, b in zip(low_color, high_color)
            )
    return anchors[-1][1]


def _is_dark(color):
    r, g, b = color[:3]
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0 < 0.5


def _rim_color(color):
    r, g, b = color[:3]
    if _is_dark(color):
        return (140, 145, 155, 255)
    return (max(0, round(r * 0.72)), max(0, round(g * 0.72)), max(0, round(b * 0.72)), 255)


def compact_hashrate(value):
    """Short label that fits inside a tray icon, e.g. '24' or '1M'."""
    if value >= 1_000_000:
        number, unit = value / 1_000_000, "M"
    elif value >= 1_000:
        number, unit = value / 1_000, ""
    else:
        number, unit = value, ""

    return f"{round(number)}{unit}"


def _font_path():
    return FONT_PATH if FONT_PATH.exists() else FALLBACK_FONT_PATH


def _fitted_font(draw, text, max_width, max_height):
    path = _font_path()
    for size in range(int(max_height) + 2, 7, -1):
        try:
            font = ImageFont.truetype(str(path), size)
        except OSError:
            font = ImageFont.load_default()
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width and box[3] - box[1] <= max_height:
            return font, box
    try:
        font = ImageFont.truetype(str(path), 8)
    except OSError:
        font = ImageFont.load_default()
    return font, draw.textbbox((0, 0), text, font=font)


def render_icon():
    with _state_lock:
        text = _state["compact"]
        ok = _state["ok"]
        value = _state["value"]

    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    if not ok or value is None:
        fill = (70, 72, 78, 255)
        rim = (105, 108, 116, 255)
    else:
        fill = hashrate_color(value) + (255,)
        rim = _rim_color(fill)

    draw.rounded_rectangle((1, 1, size - 2, size - 2), radius=12, fill=fill, outline=rim, width=2)

    font, box = _fitted_font(draw, text, size - 12, size - 14)
    width, height = box[2] - box[0], box[3] - box[1]
    x = (size - width) / 2 - box[0]
    y = (size - height) / 2 - box[1]
    text_fill = (255, 255, 255, 255) if _is_dark(fill) else (10, 10, 12, 255)
    draw.text((x, y), text, font=font, fill=text_fill)
    return image


def tooltip_text():
    with _state_lock:
        full = _state["full"]
        ok = _state["ok"]
        error = _state["error"]

    if ok:
        return f"MoneroOcean: {full}"
    if full == "loading...":
        return f"MoneroOcean: connecting... ({error})" if error else "MoneroOcean: connecting..."
    return f"MoneroOcean: {full} (last known)"


def hashrate_label(item=None):
    with _state_lock:
        full = _state["full"]
        ok = _state["ok"]
    return f"Hashrate: {full}" if ok else f"Hashrate: {full} (offline)"


def refresh_worker(icon=None):
    icon = icon or _icon
    try:
        value = api.fetch_hashrate(api.get_wallet())
        full = api.format_hashrate(value)
        with _state_lock:
            _state.update(
                full=full,
                compact=compact_hashrate(value),
                value=value,
                ok=True,
                error="",
                checked_at=datetime.now(),
            )
        log(f"OK {full}")
    except Exception as exc:  # network error, bad JSON, etc.
        with _state_lock:
            _state.update(ok=False, error=str(exc))
        log(f"ERROR {exc}")

    if icon is not None:
        icon.icon = render_icon()
        icon.title = tooltip_text()
        try:
            icon.update_menu()
        except Exception:
            pass


def refresh_now(icon, item=None):
    threading.Thread(target=refresh_worker, args=(icon,), daemon=True).start()


def open_dashboard(icon, item=None):
    webbrowser.open(DASHBOARD_URL.format(wallet=api.get_wallet()))


def startup_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{interpreter}" "{Path(__file__).resolve()}"'


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(value)
    except OSError:
        return False


def toggle_startup(icon, item=None):
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if startup_enabled():
                winreg.DeleteValue(key, APP_NAME)
                log("autostart disabled")
            else:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, startup_command())
                log("autostart enabled")
    except OSError as exc:
        log(f"autostart error: {exc}")
    if icon is not None:
        icon.update_menu()


def exit_app(icon, item=None):
    if icon is not None:
        icon.stop()


def single_instance():
    """Keep only one tray icon. Returns False if another copy is running."""
    global _mutex
    kernel32 = ctypes.windll.kernel32
    _mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def main():
    global _icon

    if not single_instance():
        log("another instance is already running")
        return

    menu = Menu(
        MenuItem(hashrate_label, None, enabled=False),
        MenuItem("Refresh now", refresh_now, default=True),
        MenuItem("Open MoneroOcean dashboard", open_dashboard),
        Menu.SEPARATOR,
        MenuItem("Start with Windows", toggle_startup, checked=lambda item: startup_enabled()),
        Menu.SEPARATOR,
        MenuItem("Exit", exit_app),
    )

    _icon = pystray.Icon(APP_NAME, render_icon(), tooltip_text(), menu)

    def setup(icon):
        icon.visible = True
        refresh_worker(icon)
        while True:
            threading.Event().wait(REFRESH_SECONDS)
            refresh_worker(icon)

    _icon.run(setup=setup)


if __name__ == "__main__":
    main()
