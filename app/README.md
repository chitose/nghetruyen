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
existing venv silently stale. `sidecar/venv` is built the same way by the App
on first launch, which is what makes a fresh checkout a single command
([ADR-0016](../docs/adr/0016-app-provisions-the-sidecar-environment.md));
delete `sidecar/venv` to force a clean rebuild.

`NgheTruyen.exe` (see below) is the other way to run it: a standalone build
that needs none of the above, but still uses `sidecar/`.

## Run

```bash
run.bat
```

First run takes a minute (setting up `venv`), and the Sidecar's own
environment is set up on the first launch that needs it; every run after that is
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

The Sidecar starts with the App and its startup is reported on the Controls
strip's status line: "Starting the Sidecar…" until `/speakers` answers, then
the usual Chapter position. The slow first-run parts say so in that line while
they happen -- setting up `sidecar/venv`, then downloading the voice model --
and a first run is allowed 15 minutes rather than the usual 60 seconds. If it
never becomes healthy the line says so, names `sidecar/sidecar.log` -- the
Sidecar's output, and the place a startup error actually is, since it runs
without a console window -- and a **Retry** button appears next to it. Retry
waits again on a Sidecar that is still loading (or downloading) its voice model
rather than restarting it, so a first run's download is not thrown away; it
spawns a fresh process only when the last one never started or has since
exited. Nothing about a failing Sidecar blocks the App: reading works, and a
Sidecar you start yourself is picked up too. See
[ADR-0013](../docs/adr/0013-sidecar-startup-status.md) and
[ADR-0016](../docs/adr/0016-app-provisions-the-sidecar-environment.md).

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

A single file that *is* the App: its modules, the injected Web View assets, the
icon, and the runtime dependencies (NiceGUI, pywebview, sounddevice, soundfile,
numpy) are all bundled, so it needs no Python install, no `app/venv`, and none
of the files in this directory. Copy it anywhere and double-click. Build it
from the app venv, because those dependencies are what get bundled (PyInstaller
itself is a build-time tool):

```bat
cd app
venv\Scripts\python.exe -m pip install pyinstaller
venv\Scripts\python.exe -m PyInstaller --noconfirm NgheTruyen.spec
copy dist\NgheTruyen.exe .
```

`NgheTruyen.spec` is the build: `--onefile --windowed`, `web/` and `assets/`
added as data, and `icon=assets/nghetruyen.ico` for the exe's own resources.
That last one is what the taskbar and Explorer show; the two windows' icons and
the chrome's favicon come from the same file at runtime
([ADR-0015](../docs/adr/0015-app-icon.md)). `check_exe_icon.py` reads the built
exe back and reports whether its icon resources match the asset:

```bat
venv\Scripts\python.exe check_exe_icon.py
```

A rebuild writes a new exe over the old one, and Explorer caches icons by path,
so it can keep showing the previous icon even though the new one is in the file.
`refresh_icon.ps1` clears that cache -- it stops and restarts Explorer, so it
needs elevation:

```bat
powershell -ExecutionPolicy Bypass -File refresh_icon.ps1
```

It is `--windowed`, so there is no console. Warnings that would have gone
there -- the Sidecar failing to start, the chrome not coming up -- are appended
to `%APPDATA%\reading-web\nghetruyen.log`.

Releases are built the same way, on a `windows-latest` runner: pushing a `v*`
tag runs `.github/workflows/release.yml`, which tests, builds, and attaches the
exe to a GitHub Release ([ADR-0014](../docs/adr/0014-release-by-tag.md)). Run
that workflow by hand to build the exe without publishing a release.

The one thing it does not carry is the **Sidecar**
([ADR-0001](../docs/adr/0001-local-sidecar-for-tts.md),
[ADR-0008](../docs/adr/0008-switch-to-vieneu-tts.md)): it still needs
`sidecar/` (`server.py` and `requirements.txt`) beside it, looked for beside
the exe and one level up. `sidecar/venv` is built on first launch if it is
missing, which needs a Python 3.10+ on PATH -- a frozen exe has no interpreter
of its own, so a machine with no Python still needs the venv copied over, and
the status line says so rather than failing quietly.
[ADR-0012](../docs/adr/0012-standalone-app-exe.md) records what is bundled and
why the Sidecar is not;
[ADR-0016](../docs/adr/0016-app-provisions-the-sidecar-environment.md) records
how its environment gets built.

## Icon

`assets/nghetruyen.ico` is the App's mark -- white headphones and a cyan play
triangle on a navy tile -- used by both windows, by the chrome's pages, and by
the exe. It is baked, not hand-drawn: `assets/nghetruyen-source.png` is the
artwork (any square PNG, 1024x1024 by preference), and `make_icon.py` crops its
white margin, makes the tile's corners transparent, and writes every size
Windows asks for. To change the mark, replace the source and re-bake
([ADR-0015](../docs/adr/0015-app-icon.md)):

```bat
sidecar\venv\Scripts\python.exe app\make_icon.py
```

That rewrites the `.ico` and `assets/nghetruyen-256.png`, the preview to look at
before trusting the small sizes. It needs Pillow, which the Sidecar's venv has
but the App's deliberately does not -- so run `test_icon.py` from the Sidecar's
venv too. It holds the `.ico` to its sizes and colours, and fails if the source
was changed without re-baking.

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
