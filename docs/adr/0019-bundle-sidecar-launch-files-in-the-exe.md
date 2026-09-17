# The exe carries the Sidecar's launch script, not its dependencies

[ADR-0016](0016-app-provisions-the-sidecar-environment.md) made the App
provision `sidecar/venv` on first use, but left one manual step standing:
`sidecar/` (`server.py` and `requirements.txt`) still has to sit beside the
exe, because that ADR rejected folding VieNeu's own dependencies into the
`--onefile` build. In practice that meant copying the exe anywhere on its own
-- to another folder, another machine -- failed at startup: `find_sidecar_dir`
had nothing to find, and `ensure_env` had nothing to build a venv from.

The fix bundles only the two small, dependency-free files `ensure_env` needs
to get started -- `server.py` and `requirements.txt`, a few KB -- as
PyInstaller `datas`, the same way `web/` and `assets/` already travel with the
exe. Nothing from ADR-0016's rejection is reopened: `vieneu`, `gradio`,
`onnxruntime` and the rest still install into `sidecar/venv` at runtime,
outside the exe, exactly as before.

At startup, if `find_sidecar_dir` comes up empty (no `sidecar/server.py`
beside the exe or one level up) and the App is frozen,
`sidecar_env.extract_bundled_sidecar` copies the bundled pair from the
PyInstaller temp dir (`sys._MEIPASS`) into a `sidecar/` folder created next to
the exe, and the App points `SidecarManager` there instead. A `sidecar/`
folder that is already present -- a checkout, or one a previous run already
created -- is left alone; this only fires the first time a location has
neither file.

Consequences worth knowing:

- The exe grows by a few KB, not the ~700 MB `sidecar/venv` would cost --
  measured in ADR-0016 and unchanged here.
- The extracted `sidecar/` still needs a Python 3.10+ on PATH to build its
  venv from, same as ADR-0016; nothing here changes what `ensure_env` requires,
  only where its input files come from.
- Two copies of the exe in two folders now each grow their own
  `sidecar/venv` (~700 MB) and voice-model cache the first time they run,
  rather than sharing one. Dropping a real `sidecar/` beside the exe (or one
  level up) still avoids that, exactly as it does today.
- Running from source is unaffected: `_frozen()` is false, so
  `extract_bundled_sidecar` is never called and `find_sidecar_dir` behaves as
  it always has.
