# The App provisions the Sidecar's environment

Folding VieNeu into the App was considered, and rejected, once the Sidecar's
only remaining cost was setup. [ADR-0001](0001-local-sidecar-for-tts.md),
[ADR-0003](0003-sentence-chunk-contract.md) and
[ADR-0008](0008-switch-to-vieneu-tts.md) keep synthesis in its own process;
[ADR-0012](0012-standalone-app-exe.md) keeps it out of the exe. What was left
was the manual step: `sidecar/README.md` asked for a venv and a `pip install`
before the App could synthesize anything.

The measurements say that step is worth removing -- but not by moving VieNeu in:

- `sidecar/venv` is 724 MB against `app/venv`'s 157 MB, and the difference is
  not the model. `vieneu` depends on `gradio` (for its own demo UI, which none
  of the code this App runs imports), and that drags in pandas, scikit-learn,
  numba and scipy alongside `librosa`, `onnxruntime`, tokenizers and friends.
  Installing it into the App would not shrink it, and a PyInstaller `--onefile`
  bundle carrying `onnxruntime` and a numba/librosa stack is exactly the
  fragility ADR-0012 walked away from.
- The voice model is a separate ~1.3 GB Hugging Face download on first
  synthesis either way, so it decides nothing about the process layout.
- A separate process also keeps a TTS crash, and the model's memory footprint,
  out of the UI's address space, and keeps ADR-0003's one-call engine seam.
- The exe stays small, and a Sidecar that is already answering -- started by
  hand, or the Docker image -- is still used exactly as it is.

So the process split stays and the setup step goes:
`sidecar_env.ensure_env()` creates `sidecar/venv` from
`sidecar/requirements.txt` with `python -m venv` and `python -m pip install`
whenever the venv is missing or its `requirements.sha256` marker does not match
the file. That mirrors `app/bootstrap.py`, whose marker and
"reinstall when requirements.txt changes" rule already exist for `app/venv`.
The marker is written only after a successful install, so an interrupted one
leaves the venv looking incomplete and the next call installs again; pip into
an existing venv is idempotent, so a venv made by hand per
`sidecar/README.md` self-heals the same way.

It runs inside `SidecarStartup`'s watch rather than on the launch path, for the
reasons ADR-0013 already gives for the spawn: the App opens and stays usable
while it happens, the Controls strip's status line says what is going on
("Setting up the Sidecar's environment…", then "Downloading the Sidecar's voice
model…"), and **Retry** runs the whole thing again. Provisioning is skipped
entirely when `/speakers` already answers, so a hand-started or Docker Sidecar
costs nothing. venv and pip output goes to `sidecar/sidecar.log`, next to the
Sidecar's own.

A first run is slower than `DEFAULT_HEALTH_TIMEOUT` (60 s), so a watch that just
installed anything, or that finds the Hugging Face cache empty, waits
`FIRST_RUN_TIMEOUT` (15 min) instead. That is a longer wait, not a weaker check:
the Sidecar answers as soon as its model is loaded, and `_alive()` still fails
fast when the process is gone.

`bootstrap.py` deliberately does not provision the Sidecar. It owns `app/venv`,
which has to exist before the App can run at all, in a console where pip's
output is visible; the Sidecar's venv can be built later, while the chrome is
already on screen and has a status line to say so. Doing it in both places would
only duplicate the work.

Consequences worth knowing:

- A first launch after a fresh checkout installs ~700 MB of packages, and a
  first synthesis still downloads the model. Both happen once.
- The exe still needs `sidecar/` (`server.py` and `requirements.txt`) beside it,
  and a Python 3.10+ on PATH to build the venv, because a frozen build has no
  interpreter of its own. Without one, the status line says so and names
  `sidecar/README.md` instead of failing somewhere inside pip. Carrying
  `sidecar/` inside the exe is a separate change and is not done here.
- Deleting `sidecar/venv` is now the supported repair for a broken environment,
  rather than the thing to avoid.
- A `sidecarUrl` pointing at another machine still provisions a local venv,
  exactly as it already spawned a local Sidecar for a remote URL. Only
  localhost is really supported, as before; `SidecarManager` is unchanged there.
- Quitting the App while pip runs leaves that pip to finish on its own, and the
  marker is written by the App, so the next launch installs again.

**Amended by [ADR-0017](0017-linux-launcher.md):** "a Python 3.10+ on PATH" is
now platform-specific -- `python` on Windows, `python3` on Linux -- and the
`venv` module has to be installed there (`python3-venv` on Debian and Ubuntu),
which `run.sh` checks for before it hands off. The venv's interpreter is
`venv/Scripts/python.exe` on Windows and `venv/bin/python` elsewhere; both come
from `platform_paths.venv_python()`. Nothing else here changes: the marker, the
idempotent pip, the 15-minute first-run wait, and the log file are all
platform-neutral, and the venv/pip output still goes to `sidecar/sidecar.log`.
