# App

The standalone Windows app (Nghe Truyện -- "listen to stories"): shows Pages in
a Web View, runs the NiceGUI chrome (address bar + Player Bar + Options) in its
own window, spawns the Sidecar, and owns all playback state. Replaces the
Chrome extension -- see
[docs/adr/0009-standalone-app-replaces-extension.md](../docs/adr/0009-standalone-app-replaces-extension.md)
and [docs/adr/0010-nicegui-chrome.md](../docs/adr/0010-nicegui-chrome.md).

## Setup

Nothing to do by hand -- `run.bat` creates `app/venv` and installs
`requirements.txt` itself, via `bootstrap.py`. It re-runs the install whenever
`requirements.txt` changes, so a newly added dependency never leaves an
existing venv silently stale. Just make sure `sidecar/venv` is already set up
per [sidecar/README.md](../sidecar/README.md) -- the App spawns that venv's
Python directly.

`NgheTruyen.exe` (see below) is the other way to run it: a standalone build
that needs none of the above, but still uses `sidecar/`.

## Run

```bash
run.bat
```

First run takes a minute (setting up `venv`); every run after that is
instant. It starts the Sidecar automatically and opens two windows:

- **Nghe Truyện** -- the Page, in a native Web View. `web/content.js` is
  injected on every load to pull the Chapter out of the DOM; it draws no UI.
- **Nghe Truyện -- Controls** -- the NiceGUI chrome: address bar, Player Bar
  (play/pause, prev/next, speed, voice, auto-next, current-Paragraph toggle).
  It is frameless and docked flush under the reader window, following its
  moves and resizes (and hiding with it when minimized) via `docking.py`.
  Drag its title bar to move it, the strip along its bottom edge to resize it,
  and use Hide page / Show page to tuck the reader away while you keep
  listening. Its ✕ quits the app (so does closing either window). A small
  audio visualizer next to the Player Bar shows the Chapter being read; the
  ‹ › arrows cycle its style (bars, mirrored, wave, blocks), and the chosen
  one is remembered in `config.json`.
  Holding or spamming next/prev moves several Paragraphs at once -- a burst of
  clicks is applied as a single jump, rather than firing one synthesis request
  per click as it did before.

Playback only does anything on a Page where extraction found prose; the
Controls window says so when a Page has nothing to read. Closing the reader
window stops the Sidecar and closes the Controls window.

The Sidecar runs without a console window; its output is appended to
`sidecar/sidecar.log`, which is the first place to look if the App warns that
it never became healthy.

On shutdown the App saves the Page it was on, the reader window's bounds, and
the dock height to `%APPDATA%\reading-web\session.json`, and restores them
next launch (see [ADR-0011](../docs/adr/0011-restore-session-on-launch.md)).
Turn "Reopen the last page on launch" off in Options to always start at Start
URL instead.

## How it fits together

`controller.py` is the single source of truth both surfaces talk to: the
Player Bar and Options call it directly, and content.js reaches it through
`api.py`. `ui.py` is only the NiceGUI view, and `main.py` starts the NiceGUI
server thread, opens both windows, and wires the pieces together.

### Standalone `NgheTruyen.exe`

A single file that *is* the App: its modules, the injected Web View assets, and
the runtime dependencies (NiceGUI, pywebview, sounddevice, soundfile, numpy)
are all bundled, so it needs no Python install, no `app/venv`, and none of the
files in this directory. Copy it anywhere and double-click. Build it from the
app venv, because those dependencies are what get bundled (PyInstaller itself
is a build-time tool):

```bat
cd app
venv\Scripts\python.exe -m pip install pyinstaller
venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed ^
    --name NgheTruyen --add-data "web;web" main.py
copy dist\NgheTruyen.exe .
```

It is `--windowed`, so there is no console. Warnings that would have gone
there -- the Sidecar failing to start, the chrome not coming up -- are appended
to `%APPDATA%\reading-web\nghetruyen.log`.

The one thing it does not carry is the **Sidecar**
([ADR-0001](../docs/adr/0001-local-sidecar-for-tts.md),
[ADR-0008](../docs/adr/0008-switch-to-vieneu-tts.md)): it still needs
`sidecar/` with its own venv and TTS model, looked for beside the exe and one
level up. [ADR-0012](../docs/adr/0012-standalone-app-exe.md) records what is
bundled and why the Sidecar is not.

## Options

The Controls window's "⚙" button opens the Options page in the reader window
(the docked strip is far too small for it): Start URL (what the reader opens on
launch), a "reopen the last page" toggle, "read short paragraphs together" and
its word threshold, Sidecar URL, default voice, default rate, backend model,
and the Adapter list as JSON. "← Back" returns to the Chapter you were reading;
because it is the same Page, playback and position are left alone rather than
restarting.

"Read short paragraphs together" merges Paragraphs under the threshold with
the ones after them (`chunker.join_short_paragraphs`) before chunking, so a
one-line piece of dialogue is not its own reading stop and one next/prev moves
past the whole exchange. It is off by default.
