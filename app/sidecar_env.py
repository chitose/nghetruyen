# app/sidecar_env.py
"""Where the Sidecar lives, and how its virtualenv gets to exist.

Stdlib only, and imported by `main.py` / `sidecar_manager.py` -- never by the
Sidecar itself, which has its own venv and its own requirements (ADR-0001,
ADR-0008).

Provisioning here is what removes the last manual setup step: the App creates
`sidecar/venv` and pip-installs `sidecar/requirements.txt` the first time it
needs it, so a fresh checkout needs no venv/pip dance by hand. See
docs/adr/0016-app-provisions-the-sidecar-environment.md.
"""
import hashlib
import shutil
import subprocess
import sys
import threading
from pathlib import Path

VENV_DIRNAME = "venv"
VENV_PYTHON_PARTS = ("Scripts", "python.exe")  # the App is Windows-only
REQUIREMENTS_NAME = "requirements.txt"
MARKER_NAME = "requirements.sha256"

# vieneu's own Requires-Python. Checked before anything is created, so a too-old
# or non-existent interpreter is one clear message instead of a pip traceback.
MIN_PYTHON = (3, 10)
MIN_PYTHON_NOTE = "Python 3.10 or newer was not found on PATH"

# Where huggingface_hub keeps the voice model by default. Only used to decide how
# long a first wait may last (the model is ~1.3 GB), never for correctness: a
# custom HF_HOME only means we give up sooner and say so.
MODEL_CACHE_DIR = Path.home() / ".cache" / "huggingface" / "hub"

# One install at a time: the launch path and Retry (or two Retries) could
# otherwise run pip against the same venv at once.
_INSTALL_LOCK = threading.Lock()


def _hidden_window_kwargs() -> dict:
    """Windows only: venv and pip must not flash a console from a windowed App,
    the same reason SidecarManager spawns uvicorn with CREATE_NO_WINDOW."""
    if sys.platform != "win32":
        return {}
    return {"creationflags": subprocess.CREATE_NO_WINDOW}


def find_sidecar_dir(app_dir: Path) -> Path:
    """The Sidecar's directory, which the standalone exe deliberately omits.

    Looked for beside the App and one level up, so both a checkout (app/ next
    to sidecar/) and an exe dropped into the repo or shipped with sidecar/ next
    to it work. ADR-0001/0008 keep the Sidecar a separate process with its own
    heavy dependencies -- vieneu, ONNX Runtime, and a model downloaded from
    Hugging Face -- so it is the one thing the exe does not carry.
    """
    for root in (app_dir, app_dir.parent):
        candidate = root / "sidecar"
        if (candidate / "server.py").is_file():
            return candidate
    return app_dir.parent / "sidecar"


def venv_python(sidecar_dir: Path) -> Path:
    """The interpreter the App spawns uvicorn with."""
    return sidecar_dir / VENV_DIRNAME / Path(*VENV_PYTHON_PARTS)


def find_system_python() -> str | None:
    """An interpreter that can create the Sidecar's venv.

    Running from source, this process is one -- and one is certainly present.
    The frozen exe is not: there `sys.executable` is the exe itself, so it has
    to be a Python on PATH."""
    if not getattr(sys, "frozen", False) and sys.executable:
        return sys.executable
    return shutil.which("python") or shutil.which("python3")


def usable_python(interpreter: str) -> bool:
    """True when `interpreter` is a real Python >= MIN_PYTHON.

    Windows' Store alias for `python.exe` is not: it exits non-zero with a
    message about installing from the Store, which would otherwise surface as a
    confusing pip failure."""
    try:
        done = subprocess.run(
            [interpreter, "-c",
             f"import sys; raise SystemExit(sys.version_info < {MIN_PYTHON})"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            **_hidden_window_kwargs(),
        )
    except OSError:
        return False
    return done.returncode == 0


def model_cache_present() -> bool:
    """Whether the voice model may already be cached.

    A first synthesis downloads ~1.3 GB from Hugging Face, which takes minutes,
    so SidecarStartup waits longer when this says no."""
    try:
        return any(MODEL_CACHE_DIR.iterdir())
    except OSError:
        return False


def ensure_env(sidecar_dir: Path, python_exe: str | None = None,
               log_path: str | None = None) -> tuple[bool, str, bool]:
    """Make `sidecar_dir/venv` able to run the Sidecar, creating it if needed.

    Returns (ok, reason, provisioned): `reason` is what to show the reader when
    ok is False, and `provisioned` is True when this call actually installed
    anything -- which means the first synthesis still has to fetch the model.

    The venv's own `requirements.sha256` marker mirrors `app/bootstrap.py`'s: it
    is written only after a successful install, so an interrupted or failed one
    leaves the venv looking incomplete and the next call installs again. pip
    into an existing venv is idempotent, so a venv made by hand (see
    sidecar/README.md) self-heals the same way."""
    sidecar_dir = Path(sidecar_dir)
    requirements = sidecar_dir / REQUIREMENTS_NAME
    if not requirements.is_file():
        return (
            False,
            "sidecar/requirements.txt was not found: the App needs the sidecar/ "
            "folder (server.py and requirements.txt) beside it.",
            False,
        )

    with _INSTALL_LOCK:
        wanted = hashlib.sha256(requirements.read_bytes()).hexdigest()
        interpreter_path = venv_python(sidecar_dir)
        if interpreter_path.is_file() and _installed_hash(sidecar_dir) == wanted:
            return True, "", False

        interpreter = python_exe or find_system_python()
        if not interpreter or not usable_python(interpreter):
            return (
                False,
                f"{MIN_PYTHON_NOTE}, so the Sidecar's environment cannot be "
                "created.",
                False,
            )

        log = _open_log(log_path)
        try:
            if not interpreter_path.is_file():
                problem = _step(
                    [interpreter, "-m", "venv", str(sidecar_dir / VENV_DIRNAME)],
                    log, "Creating sidecar/venv",
                )
                if problem:
                    return False, problem, False
            problem = _step(
                [str(interpreter_path), "-m", "pip", "install", "-r", str(requirements)],
                log, "Installing the Sidecar's packages", cwd=str(sidecar_dir),
            )
            if problem:
                return False, problem, False
            _write_marker(sidecar_dir, wanted)
        finally:
            _close_log(log)
        return True, "", True


def _marker_path(sidecar_dir: Path) -> Path:
    return sidecar_dir / VENV_DIRNAME / MARKER_NAME


def _installed_hash(sidecar_dir: Path) -> str | None:
    try:
        return _marker_path(sidecar_dir).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _write_marker(sidecar_dir: Path, digest: str) -> None:
    """Best effort: an unwritable marker only means the next launch installs
    again, which is harmless."""
    try:
        _marker_path(sidecar_dir).write_text(digest, encoding="utf-8")
    except OSError:
        pass


def _open_log(log_path: str | None):
    """Append setup output to the App's sidecar.log; None if it cannot be
    opened, in which case the output is discarded rather than shown."""
    if not log_path:
        return None
    try:
        return open(log_path, "a", encoding="utf-8", errors="replace")
    except OSError:
        return None


def _close_log(handle) -> None:
    if handle is not None:
        try:
            handle.close()
        except OSError:
            pass


def _step(argv: list, log, what: str, cwd: str | None = None) -> str | None:
    """Run one setup command: None on success, else the reason to report.

    Exit codes are returned rather than raised because the only caller is a
    background startup watch, which has nothing to catch an exception."""
    try:
        done = subprocess.run(
            argv, cwd=cwd, check=False,
            stdout=log or subprocess.DEVNULL, stderr=subprocess.STDOUT,
            **_hidden_window_kwargs(),
        )
    except OSError as err:
        return f"{what} could not run ({err})."
    if done.returncode != 0:
        return f"{what} failed (exit code {done.returncode})."
    return None
