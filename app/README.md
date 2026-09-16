# App

The standalone Windows app: embeds a Web View, spawns the Sidecar, and owns
all playback state. Replaces the Chrome extension -- see
[docs/adr/0009-standalone-app-replaces-extension.md](../docs/adr/0009-standalone-app-replaces-extension.md).

## Setup

Nothing to do by hand -- `run.bat` (or `ReadingWeb.exe`, see below) creates
`app/venv` and installs `requirements.txt` itself on first run, via
`bootstrap.py`. Just make sure `sidecar/venv` is already set up per
[sidecar/README.md](../sidecar/README.md) -- this app spawns that venv's
Python directly.

## Run

```bash
run.bat
```

First run takes a minute (setting up `venv`); every run after that is
instant. Starts the Sidecar automatically (no separate terminal needed,
unlike the old extension setup) and opens the main window. Closing the
window stops the Sidecar too.

### Double-clickable .exe (optional)

For a single double-clickable launcher instead of `run.bat`, build one once
with [PyInstaller](https://pyinstaller.org) (a build-time tool, not a
runtime dependency -- install it anywhere, e.g. `pip install pyinstaller`):

```bash
cd app
pyinstaller --onefile --name ReadingWeb bootstrap.py
copy dist\ReadingWeb.exe .
```

`ReadingWeb.exe` is just a compiled copy of `bootstrap.py` -- it still needs
to live in `app/` alongside `main.py`/`requirements.txt`/etc. and needs a
real Python on PATH the first time it runs (to create `venv`), same as
`run.bat`. Nothing about the app itself gets bundled into the exe.

## Options

Right-click isn't available in a Web View -- for now, open Options by
calling `open_options_window()` from `main.py` (a menu/keyboard shortcut is
a follow-up, not blocking this plan).
