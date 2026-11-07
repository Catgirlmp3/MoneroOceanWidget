"""MoneroOcean hashrate tray icon for the Windows notification area.

A system-tray icon that shows the wallet's current hashrate, with the exact
value in the tooltip and right-click menu. Polls every 60 seconds.
"""

import ctypes
import os
import sys
import threading
import time
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
DIAGNOSTICS = os.environ.get("MONERO_WIDGET_DIAGNOSTICS", "").strip().lower() in {
    "1", "true", "yes", "on"
}
DASHBOARD_URL = "https://moneroocean.stream/#/wallet/{wallet}/overview?window=all&mode=xmr&view=list&sort=name&dir=asc"
FONT_PATH = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "ARIALNB.TTF"
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
_refresh_lock = threading.Lock()
_stop_event = threading.Event()
_icon = None
_mutex = None
_last_icon_key = None
_last_tooltip = None
_last_menu_label = None


def log(message):
    try:
        folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MoneroOceanWidget"
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / "tray.log", "a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\\n")
    except OSError:
        pass


def hashrate_color(value):
    """Background colour for a hashrate in H/s, interpolated between anchors."""
    kh = value / 1000.0
    anchors = [
        (0.0, (255, 0, 0)),
        (8.0, (255, 0, 0)),
        (9.0, (255, 165, 0)),
        (10.0, (0, 0, 0)),
        (15.0, (201, 167, 255)),
        (20.0, (255, 158, 207)),
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


def _update_tray_ui(icon):
    """Touch the Windows tray shell only when the displayed value changed."""
    global _last_icon_key, _last_tooltip, _last_menu_label

    with _state_lock:
        compact = _state["compact"]
        ok = _state["ok"]
        value = _state["value"]

    icon_key = (compact, ok, hashrate_color(value) if ok and value is not None else None)
    tooltip = tooltip_text()
    menu_label = hashrate_label()

    if icon_key != _last_icon_key:
        icon.icon = render_icon()
        _last_icon_key = icon_key

    if tooltip != _last_tooltip:
        icon.title = tooltip
        _last_tooltip = tooltip

    if menu_label != _last_menu_label:
        try:
            icon.update_menu()
        except Exception as exc:
            if DIAGNOSTICS:
                log(f"MENU_UPDATE_ERROR {exc}")
        _last_menu_label = menu_label


def refresh_worker(icon=None):
    """Fetch one update. Concurrent refresh requests are discarded, not queued."""
    icon = icon or _icon
    if not _refresh_lock.acquire(blocking=False):
        if DIAGNOSTICS:
            log("REFRESH_SKIPPED already running")
        return

    started = time.perf_counter()
    try:
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
            if DIAGNOSTICS:
                log(f"REFRESH_OK {full} elapsed={time.perf_counter() - started:.3f}s")
        except Exception as exc:  # network error, bad JSON, etc.
            with _state_lock:
                _state.update(ok=False, error=str(exc))
            log(f"REFRESH_ERROR elapsed={time.perf_counter() - started:.3f}s {exc}")

        if icon is not None:
            try:
                _update_tray_ui(icon)
            except Exception as exc:
                if DIAGNOSTICS:
                    log(f"TRAY_UPDATE_ERROR {exc}")
    finally:
        _refresh_lock.release()


def refresh_now(icon, item=None):
    threading.Thread(
        target=refresh_worker,
        args=(icon,),
        name="MoneroOceanManualRefresh",
        daemon=True,
    ).start()


def poll_loop(icon):
    """Keep network work off pystray's setup/UI lifecycle thread."""
    refresh_worker(icon)
    while not _stop_event.wait(REFRESH_SECONDS):
        refresh_worker(icon)


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
    _stop_event.set()
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
        threading.Thread(
            target=poll_loop,
            args=(icon,),
            name="MoneroOceanPoller",
            daemon=True,
        ).start()

    _icon.run(setup=setup)


if __name__ == "__main__":
    main()
