# App

The standalone Windows app (Nghe Truyện -- "listen to stories"): shows Pages in
a Web View, runs the NiceGUI chrome (address bar + Player Bar + Options) in its
own window, spawns the Sidecar, and owns all playback state. Replaces the
Chrome extension -- see
[docs/adr/0009-standalone-app-replaces-extension.md](../docs/adr/0009-standalone-app-replaces-extension.md)
and [docs/adr/0010-nicegui-chrome.md](../docs/adr/0010-nicegui-chrome.md).

## Setup

Nothing to do by hand -- `run.bat` (Windows) or `../run.sh` (Linux) creates
`app/venv` and installs
`requirements.txt` itself, via `bootstrap.py`. It re-runs the install whenever
`requirements.txt` changes, so a newly added dependency never leaves an
existing venv silently stale. `sidecar/venv` is built the same way by the App
on first launch, which is what makes a fresh checkout a single command
([ADR-0016](../docs/adr/0016-app-provisions-the-sidecar-environment.md));
delete `sidecar/venv` to force a clean rebuild.

`NgheTruyen.exe` (see below) is the other way to run it on Windows: a
standalone build that needs none of the above, but still uses `sidecar/`. There
is no Linux equivalent -- see [ADR-0017](../docs/adr/0017-linux-launcher.md)
for why, and `../dist/linux/install.sh` for the desktop entry instead.

## Run

```bash
run.bat          # Windows
./run.sh         # Linux, from the repo root
```

First run takes a minute (setting up `venv`), and the Sidecar's own
environment is set up on the first launch that needs it; every run after that is
instant. It starts the Sidecar automatically and opens two windows:

- **Nghe Truyện** -- the Page, in a native Web View. `web/content.js` is
  injected on every load to pull the Chapter out of the DOM; it draws no UI.
- **Nghe Truyện -- Controls** -- the NiceGUI chrome: address bar, Player Bar
  (play/pause, prev/next, speed, voice, auto-next, current-Paragraph toggle).
  It is frameless and docked flush under the reader window, following its
  moves and resizes (and hiding with it when minimized) via `docking.py`, and
  it is a tool window (`window_group.py`), so Windows gives it no taskbar
  button and no Alt-Tab entry of its own -- the App looks like one window.
  `check_windows.py` reads those styles back.
  Drag its title bar to move it, the strip along its bottom edge to resize it,
  and use Hide page / Show page to tuck the reader away while you keep
  listening -- which of the two it was survives a restart, and the ⚙ Options
  button brings the reader back rather than opening into a window you cannot
  see. Its ✕ quits the app (so does closing either window). A small
  audio visualizer next to the Player Bar shows the Chapter being read; the
  ‹ › arrows cycle its style (bars, mirrored, wave, blocks), and the chosen
  one is remembered in `config.json`.
  Holding or spamming next/prev moves several Paragraphs at once -- a burst of
  clicks is applied as a single jump, rather than firing one synthesis request
  per click as it did before.

Playback only does anything on a Page where extraction found prose; the
Controls window says so when a Page has nothing to read. Closing the reader
window stops the Sidecar and closes the Controls window.

A launch starts with a small always-on-top startup window -- the App's icon, its
name, and one line of status. It covers the stretch where there is nothing else
to show (the onefile exe unpacking, the chrome server coming up) and carries the
Sidecar's status while it does, then closes as soon as the reader window is on
screen: from there the Controls strip is the status line. On Windows that window
is the Win32 one in `splash.py`; on Linux it is the tkinter one beside it,
picked by `splash.make_splash` -- and it earns its keep more there, because a
first Linux run builds a ~700 MB `sidecar/venv` and downloads a ~1.3 GB model
before anything else can report progress.

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

On shutdown the App saves the Page it was on, the reader window's bounds, the
dock height, and whether the reader was hidden, to `session.json` beside
`config.json` -- `%APPDATA%\reading-web` on Windows, and
`$XDG_DATA_HOME/reading-web` (falling back to `~/.local/share/reading-web`) on
Linux, both from `platform_paths.data_dir()` -- and restores them next launch
(see [ADR-0011](../docs/adr/0011-restore-session-on-launch.md)). Turn "Reopen the
last page on launch" off in Options to always start at Start URL instead.

## How it fits together

`controller.py` is the single source of truth both surfaces talk to: the
Player Bar and Options call it directly, and content.js reaches it through
`api.py`. `ui.py` is only the NiceGUI view, and `main.py` starts the NiceGUI
server thread, opens both windows, and wires the pieces together.

`platform_paths.py` is the one module that knows which platform the App is on:
where a venv puts its interpreter (`bin/python` or `Scripts/python.exe`), which
names count as a system Python on PATH, and where the settings folder is
(`data_dir()`, above). `bootstrap.py`, `sidecar_env.py`, `sidecar_manager.py`,
`splash.py`, `window_group.py`, `icon.py` and `main.py` all ask it rather than
deciding for themselves, which is what keeps the Windows assumptions in one
file with one test file ([`test_platform_paths.py`](test_platform_paths.py)).
`icon.py` is the smaller version of the same idea -- it picks the `.ico` or the
`nghetruyen-256.png` -- and `splash.make_splash` picks the startup window. See
[ADR-0017](../docs/adr/0017-linux-launcher.md).

What genuinely stays Windows-only: `window_group.py`'s Win32 ex-styles (Linux
uses the X11 EWMH hints instead, and gets nothing on Wayland),
`check_windows.py`, `make_icon.py`/`check_exe_icon.py`/`refresh_icon.ps1`, and
`NgheTruyen.spec`.

### Linux

The App runs on Linux from the same source tree, launched by `../run.sh` (or
`../dist/linux/install.sh` for a desktop entry). The differences worth knowing:

- pywebview uses its GTK backend rather than WebView2. `sudo apt install
  python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1` (or the distro's equivalent).
  Note that `import webview` succeeds without any of that -- pywebview picks
  its backend when a window is created, so a missing typelib shows up as the
  reader and Controls windows failing to open, not as an import error.
- `sounddevice` links against PortAudio: `sudo apt install libportaudio2`.
  A missing or refusing audio backend now surfaces as a message on the Controls
  strip instead of a traceback on the playback thread. Because the App gets
  speed changes by scaling the sample rate ([ADR-0003](../docs/adr/0003-sentence-chunk-contract.md)),
  a rate the backend rejects is the failure to watch for on a PipeWire box.
- The two windows are listed separately by the shell on Wayland: the EWMH
  "skip taskbar" hints need an X11 window ID, which a Wayland session does not
  have. On X11 they collapse into one entry as they do on Windows.
- The icon is `assets/nghetruyen-256.png` rather than the `.ico`, and the
  startup window is tkinter rather than Win32.

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
(the docked strip is far too small for it), showing that window first if Hide
page had tucked it away: Start URL (what the reader opens on launch), a "reopen
the last page" toggle, "read short paragraphs together" and its word threshold,
Sidecar URL, default voice, default rate, backend model, and the Adapter list as
JSON. "← Back" returns to the Chapter you were reading; because it is the same
Page, playback and position are left alone rather than restarting.

"Read short paragraphs together" merges Paragraphs under the threshold with
the ones after them (`chunker.join_short_paragraphs`) before chunking, so a
one-line piece of dialogue is not its own reading stop and one next/prev moves
past the whole exchange. It is off by default.
