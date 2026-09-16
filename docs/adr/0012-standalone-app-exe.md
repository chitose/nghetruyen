# The App ships as one standalone exe; the Sidecar stays a separate process

`NgheTruyen.exe` used to be `bootstrap.py` compiled: a launcher that created
`app/venv`, pip-installed `requirements.txt`, and ran `main.py` from the
checkout. It is now the App itself. PyInstaller bundles the App's own modules,
the Web View assets (`web/readerable.js`, `web/content.js`), and the runtime
dependencies -- NiceGUI, pywebview (with pythonnet and the WebView2 DLLs),
sounddevice and its PortAudio DLL, soundfile and its libsndfile DLL, and numpy
-- so the exe needs no Python install, no `app/venv`, and no files beside it.
`main.py` is the entry point now rather than `bootstrap.py`, which stays only
for `run.bat`'s source-checkout path.

That moves two things in `main.py` behind a frozen check. The Web View assets
come from `sys._MEIPASS` (where PyInstaller unpacks bundled data), not from
`__file__`'s directory. And the Sidecar's location is searched for rather than
assumed: `find_sidecar_dir()` looks beside the App and one level up, so both a
checkout (app/ next to sidecar/) and an exe dropped into the repo work.

The build is `--windowed`, so there is no console to lose messages to.
Warnings that used to go to stderr -- the Sidecar failing to start, the chrome
not coming up, a session write failing -- now go through `main.warn()`, which
also appends them to `%APPDATA%\reading-web\nghetruyen.log`. `SidecarManager`
takes an `on_warning` callback for the same reason.

The Sidecar is deliberately not bundled. Its venv is 724 MB (vieneu, ONNX
Runtime, transformers) before the ~1.3 GB model that Hugging Face downloads on
first use, and ADR-0001/0008 keep it a separate process behind an HTTP contract
so the engine can be swapped without touching the App. Folding it in would make
the exe enormous and fragile for no gain: `sidecar/` still has to exist, and the
model still has to be fetched once.

`SidecarManager.start()` probes `/speakers` before spawning anything. If a
Sidecar already answers -- started by hand, or the Docker image -- the App uses
it and leaves it running on exit, instead of starting a second process that
could only fail to bind the port. That also removes the duplicate-bind error
(`[Errno 10048] ... bind on ('127.0.0.1', 8934)`) the old unconditional spawn
left in `sidecar.log`.

So "standalone" means the App: one file that runs on a machine with no Python
and no checkout. The Sidecar remains the one external piece, found beside the
exe or one level up (or anywhere, if you point `sidecarUrl` at one already
running -- e.g. the Docker image).
