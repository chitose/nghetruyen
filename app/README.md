# App

The standalone Windows app: embeds a Web View, spawns the Sidecar, and owns
all playback state. Replaces the Chrome extension -- see
[docs/adr/0009-standalone-app-replaces-extension.md](../docs/adr/0009-standalone-app-replaces-extension.md).

## Setup (once)

```bash
cd app
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Also install VLC... no -- this app uses `sounddevice`, not `python-vlc`, so
there is nothing extra to install beyond `pip install -r requirements.txt`.
Make sure `sidecar/venv` is already set up per [sidecar/README.md](../sidecar/README.md)
-- this app spawns that venv's Python directly.

## Run

```bash
run.bat
```

Starts the Sidecar automatically (no separate terminal needed, unlike the
old extension setup) and opens the main window. Closing the window stops
the Sidecar too.

## Options

Right-click isn't available in a Web View -- for now, open Options by
calling `open_options_window()` from `main.py` (a menu/keyboard shortcut is
a follow-up, not blocking this plan).
