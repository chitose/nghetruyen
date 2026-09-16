# A Linux launcher, and the one module that knows the platform

The App was written as a Windows program, and the ADRs say so: ADR-0009 calls it
"a single Windows program", ADR-0012 ships one `NgheTruyen.exe`, ADR-0016's
provisioning assumes `venv/Scripts/python.exe`, and ADR-0010's whole tool-window
section is Win32 window styles. None of that was a considered decision about
platform support -- it was the shape a program takes when only one platform was
ever run. This ADR adds the second one, and records what that cost.

## Why the port is small

Almost all of the App turned out to be platform-neutral already, which is the
main finding here:

- The **Sidecar** was already running on Linux: `sidecar/Dockerfile` is
  `python:3.12-slim` + `pip install -r requirements.txt` + `server.py`, and
  `sidecar/` contains no platform check at all.
- **VieNeu-TTS** is cross-platform. `vieneu`'s base dependencies --
  `onnxruntime`, `numpy`, `soundfile`, `soxr`, `kaldi-native-fbank`,
  `tokenizers`, `huggingface_hub`, `librosa`, `gradio` -- all have Linux
  wheels, its phonemizer `sea-g2p` ships `manylinux_2_17_x86_64`/`aarch64` Rust
  wheels, and the CPU/ONNX path it uses by default needs no PyTorch and no
  `espeak-ng`.
- **pywebview 6.2.1** has a real Linux backend. `guilib.py` picks GTK (or Qt,
  and Qt first under a KDE session); `platforms/gtk.py` provides every call the
  App makes -- `frameless`, `hidden`, `move`/`resize`/`hide`/`show`/`destroy`,
  the `moved`/`resized`/`minimized`/`restored`/`maximized`/`shown`/`closed`
  events `docking.py` binds, `evaluate_js`, and `get_screens()` behind
  `webview.screens`. Worth knowing when reading the code: `import webview` does
  *not* select a backend -- that happens when a window is created -- so a
  missing GTK typelib does not surface until the first `create_window`.
- **NiceGUI** runs in pure server mode here (`reload=False, show=False`), so
  the chrome never had a platform in it.
- `docking.py`, `controller.py`, `playback.py`, `chunker.py` and
  `visualizer.py` have no platform code in them and were not touched.

What was actually Windows-specific was small and scattered: the venv's
interpreter path (`Scripts/python.exe`) in two modules, `%APPDATA%` in
`main.py`, the `.ico` handed to two APIs, a Win32 startup window, a Win32
tool-window style, and the two `CREATE_NO_WINDOW` spawns.

## The decision: one module knows, and the launcher is source

`app/platform_paths.py` is now the only place that asks what the platform is.
It answers four questions -- where a venv puts its interpreter, where the App's
data lives, which interpreters are worth looking for on PATH, and whether this
is Windows -- and `bootstrap.py`, `sidecar_env.py`, `sidecar_manager.py`,
`splash.py`, `window_group.py`, `icon.py` and `main.py` all ask it instead of
deciding for themselves. That is the whole reason the port is reviewable: every
Windows assumption is now a line in one file with a test.

The launch path is a second, smaller decision. **`run.sh` plus
`dist/linux/install.sh`**, not a Linux bundle:

- The App does not need bundling to be runnable, because `bootstrap.py`
  already provisions `app/venv` from `requirements.txt` and the App already
  provisions `sidecar/venv` (ADR-0016). A Linux launcher therefore needs to do
  exactly what `run.bat` does: find an interpreter, then hand off.
- A self-contained Linux build is much harder than the Windows one, not
  easier. `NgheTruyen.exe` bundles WebView2 DLLs because they are files
  PyInstaller can carry; pywebview's Linux backend is GTK/WebKit2GTK or Qt,
  which are *system* libraries reached through GObject introspection. Shipping
  those means shipping a GTK stack, and then a display stack under it.
- The user-visible goal -- "it is in my application list" -- is met by
  `install.sh`, which copies the source tree to
  `$XDG_DATA_HOME/nghetruyen`, writes a `.desktop` file whose `Exec=` points at
  the copy's `run.sh`, and installs the PNG into the hicolor theme. It never
  touches the venvs, so re-running it after a pull does not throw away a
  ~700 MB environment or the voice model.

`app/NgheTruyen.spec` and `.github/workflows/release.yml` are untouched: the
exe is still the Windows release, and a Linux release is not built.

## What degrades off Windows, and what does not

Nothing in the App is allowed to fail because of the platform; the two genuine
Win32 features fall back to "fewer desktop refinements" and one line in
`nghetruyen.log`:

- **The Controls strip gets its own taskbar entry**, and both windows are
  listed separately. `window_group.py` tries the EWMH
  `_NET_WM_STATE_SKIP_TASKBAR`/`_SKIP_PAGER` hints through `libX11` on X11. On
  a Wayland session there is no X11 window ID to set them on, so it says so and
  stops. That is a limitation of the platform, not an oversight.
- **The startup window is tkinter instead of Win32**, via `splash.make_splash`.
  It earns its keep more on Linux than it did on Windows: a first launch builds
  a ~700 MB venv and downloads a ~1.3 GB model before anything else can report
  progress, so without it a launcher looks dead for minutes. No tkinter and no
  display ends in one warning, as the Win32 one already did.
- **Audio** goes through `sounddevice`'s PortAudio, which needs
  `libportaudio2`. The App gets speed changes by scaling the sample rate
  (`audio_player.py`), and whether a given rate is accepted is a backend
  question on both platforms. A refused stream now surfaces as a status-line
  error instead of a traceback on the playback thread -- it used to escape it.

Untouched because they are Windows-only tooling and out of scope:
`make_icon.py`/`refresh_icon.ps1`/`check_exe_icon.py` (the `.ico` and Explorer's
icon cache), `app/run.bat`, and the exe build.

## Consequences

- `platform_paths.data_dir()` keeps `%APPDATA%\reading-web` on Windows, so an
  existing install's `config.json` and `session.json` are not stranded. On
  Linux it follows XDG: `$XDG_DATA_HOME/reading-web`, or
  `~/.local/share/reading-web`.
- `main.py` hands pywebview and NiceGUI `nghetruyen-256.png` on Linux rather
  than the `.ico`, because GTK can be built without an ICO loader and that
  fails at window creation rather than falling back. Both assets already
  existed and both were already bundled.
- `requirements.txt` stays unpinned on both platforms, per ADR-0014. The Linux
  path is developed against pywebview 6.2.1 and NiceGUI 3.16.0; a resolver
  change that moves pywebview to a different backend is a known risk, not a
  handled one.
- `.github/workflows/linux.yml` runs the test suite on `ubuntu-latest` with
  `libportaudio2`, `python3-gi` and `gir1.2-webkit2-4.1` installed, so the
  Linux branches are actually exercised by CI rather than only on a developer's
  machine.
- Because the launch path is source-plus-venv, an installed copy still needs
  `python3` and `python3-venv`, and the Web View and PortAudio packages, on the
  machine. `run.sh` says which package is missing rather than failing inside
  pip.
