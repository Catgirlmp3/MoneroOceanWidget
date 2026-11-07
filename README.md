# MoneroOcean hashrate tray widget

A Windows system-tray icon that shows your MoneroOcean hashrate at a glance.

- **Icon** — dark rounded badge with large white digits showing the hashrate
  rounded to the current unit (`20`, `125`, `1M`). The unit and exact value are
  in the tooltip and menu.
- **Colour** — the icon background follows the hashrate: red below 8 kH/s,
  blending through orange around 9, black at 10, light purple at 15, pink at 20+.
- **Tooltip** — exact value, e.g. `MoneroOcean: 20.15 kH/s`.
- **Left click** — refresh immediately.
- **Right click** — hashrate menu, refresh, dashboard, autostart, exit.
- Polls every 60 seconds; keeps showing the last value if the API is unreachable.

## Files

| File | Purpose |
| --- | --- |
| `dist\MoneroOceanTray.exe` | Prebuilt tray app (no Python needed) |
| `monero_tray.py` | Tray app source |
| `monero_hashrate.py` | Shared API/formatting code + CLI JSON output |
| `dist\monero_hashrate.exe` | CLI build used for testing/debugging |
| `requirements.txt` | Dependencies for running from source or rebuilding |

## Use it

1. Run `dist\MoneroOceanTray.exe` (double-click or add it to startup from the menu).
2. If Windows hides it in the tray overflow (`^`), open the overflow and drag the
   orange badge onto the taskbar. Windows remembers the position.
3. Hover for the exact hashrate, right-click for the menu.

The wallet is baked into the build. To use a different wallet, pass it as the
first argument or set the `MONERO_WALLET` environment variable.

The tray app avoids overlapping API refreshes and only updates the tray icon,
tooltip, or menu when the displayed value changes. Network polling runs on a
background worker so a slow API response does not hold up tray setup.

For optional refresh timing diagnostics, set the user environment variable
`MONERO_WIDGET_DIAGNOSTICS=1` and restart the app. Successful refresh durations
and skipped overlapping refreshes will then be written to the log.

The tray icon writes errors to:

```
%LOCALAPPDATA%\MoneroOceanWidget\tray.log
```

## Run from source

```bat
pip install -r requirements.txt
pythonw monero_tray.py
```

## CLI mode

`monero_hashrate.py` still prints a single JSON line, useful for scripts:

```bat
dist\monero_hashrate.exe
{"hashrate": "23.77 kH/s"}
```

> The request sends a custom `User-Agent`; MoneroOcean returns HTTP 403 to
> Python's default `Python-urllib/3.x` agent.

## Rebuild

```bat
pip install -r requirements.txt
python -m PyInstaller --onefile --noconsole --clean --name MoneroOceanTray ^
  --hidden-import pystray._win32 --collect-submodules pystray monero_tray.py
python -m PyInstaller --onefile --noconsole --clean --name monero_hashrate monero_hashrate.py
```

Pushing a `v*` tag runs `.github/workflows/build.yml` and attaches both exes to
the GitHub release.
