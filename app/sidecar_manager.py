"""Spawns and supervises the Sidecar (sidecar/server.py) as a child process.

See docs/adr/0009-standalone-app-replaces-extension.md: the App starts the
Sidecar automatically instead of the reader running it manually in a
terminal (ADR-0001's "started manually" cost moves up one level).

The Sidecar is a console program, but it is never meant to show a window: a
console-less App (pythonw, or a PyInstaller --noconsole build) would otherwise
make Windows allocate a visible console for it. It runs with CREATE_NO_WINDOW
on Windows -- and with nothing extra elsewhere, where that problem does not
exist (ADR-0017) -- while its output goes to sidecar.log instead, so startup
errors stay readable.

`SidecarStartup` sits on top of `SidecarManager`: it drives the launch and
reports how it went, so the chrome can show the reader what is happening
instead of the Sidecar failing silently into that log. See
docs/adr/0013-sidecar-startup-status.md. It also provisions the Sidecar's
environment before spawning, so `sidecar/venv` no longer has to be set up by
hand -- see docs/adr/0016-app-provisions-the-sidecar-environment.md.
"""
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import platform_paths
import sidecar_env

LOG_NAME = "sidecar.log"

# How long the Sidecar gets to answer /speakers before the App calls it failed.
# A timeout is not proof that it is dead: a first run downloads the voice model
# from Hugging Face, which takes minutes. SidecarStartup says so, and its Retry
# waits again rather than respawning.
DEFAULT_HEALTH_TIMEOUT = 60.0

# A first run is slower than that: the venv may have just been built, and the
# ~1.3 GB voice model still has to come down before /speakers answers at all.
FIRST_RUN_TIMEOUT = 900.0

# Sidecar startup states, reported through SidecarStartup's on_status and
# rendered by the chrome (see controller.report_sidecar).
STARTING = "starting"
PREPARING = "preparing"
READY = "ready"
FAILED = "failed"

# The two things that happen before the Sidecar can say anything itself; both
# reach the reader through ui.status_text.
SETUP_MESSAGE = "Setting up the Sidecar's environment (first run only)…"
MODEL_MESSAGE = "Downloading the Sidecar's voice model (first run only, about 1.3 GB)…"


def _hidden_window_kwargs() -> dict:
    """Windows only: keep the Sidecar from getting its own console window.

    Off Windows this returns nothing and the spawn is unchanged -- there is no
    console to suppress, and the Sidecar's output already goes to sidecar.log
    through the log file handle rather than through a terminal.
    """
    if not platform_paths.is_windows():
        return {}
    return {"creationflags": subprocess.CREATE_NO_WINDOW}


class SidecarManager:
    def __init__(self, python_exe: str, cwd: str, port: int = 8934,
                 log_path: str | None = None, on_warning=None):
        self.python_exe = python_exe
        self.cwd = cwd
        self.port = port
        self.log_path = log_path or os.path.join(cwd, LOG_NAME)
        self._on_warning = on_warning
        self.using_existing = False
        self._proc = None
        self._log_file = None

    def start(self, backend_model: str = "default") -> None:
        if self._proc is not None:
            return
        if self.is_healthy():
            # Something already answers on this port -- a Sidecar started by
            # hand, or the Docker image (sidecar/README.md). Spawning another
            # would just fail to bind the port. Use the running one, and leave
            # it alone again on stop().
            self.using_existing = True
            self._warn(
                f"Sidecar already running on port {self.port}; "
                "using it instead of starting another."
            )
            return
        self.using_existing = False
        env = dict(os.environ)
        if backend_model and backend_model != "default":
            env["TTS_BACKEND_MODEL"] = backend_model
        self._log_file = self._open_log()
        try:
            self._proc = subprocess.Popen(
                [self.python_exe, "-m", "uvicorn", "server:app", "--port", str(self.port)],
                cwd=self.cwd,
                env=env,
                stdout=self._log_file or subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                **_hidden_window_kwargs(),
            )
        except (FileNotFoundError, OSError) as err:
            self._close_log()
            self._warn(
                f"Warning: failed to start the Sidecar ({err}). "
                "See sidecar/README.md for setting up sidecar/venv."
            )

    def ensure_running(self, backend_model: str = "default") -> None:
        """start(), but safe to call again later -- the Retry path.

        A Sidecar this manager already spawned is left alone, because "not
        healthy yet" usually means "still loading the voice model", and killing
        it would throw that work away. Only a Sidecar that never started, or
        one whose process has since exited, is spawned.
        """
        if self.using_existing or self.is_running:
            return
        if self._proc is not None:
            self.stop()  # the handle is dead; clear it so start() spawns again
        self.start(backend_model=backend_model)

    def prepare(self) -> tuple[bool, str, bool]:
        """Make sidecar/venv able to run the Sidecar, provisioning it if needed.

        Separate from start() because it can be slow -- a first run installs
        ~700 MB of packages -- and because it is pointless when something is
        already answering on the port. Output goes to this manager's log, next
        to the Sidecar's own; see
        docs/adr/0016-app-provisions-the-sidecar-environment.md.
        """
        return sidecar_env.ensure_env(self.cwd, log_path=self.log_path)

    def speakers_url(self) -> str:
        return f"http://localhost:{self.port}/speakers"

    def is_healthy(self) -> bool:
        """One quick probe: is a Sidecar already answering on this port?"""
        try:
            with urllib.request.urlopen(self.speakers_url(), timeout=2):
                return True
        except (urllib.error.URLError, ConnectionError, OSError):
            return False

    def wait_healthy(self, timeout: float = 60.0, interval: float = 0.5) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_healthy():
                return True
            time.sleep(interval)
        return False

    def stop(self) -> None:
        if self._proc is None:
            self._close_log()
            return
        self._proc.terminate()
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        self._proc = None
        self._close_log()

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _warn(self, message: str) -> None:
        """Let the App record this: a windowed exe throws stderr away."""
        if self._on_warning is not None:
            self._on_warning(message)
        else:
            print(message, file=sys.stderr)

    def _open_log(self):
        """Append this run's output to sidecar.log; None if the file can't be
        opened (the Sidecar then runs with its output discarded)."""
        try:
            handle = open(self.log_path, "a", encoding="utf-8", errors="replace")
        except OSError:
            return None
        try:
            handle.write(f"\n--- Sidecar started {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            handle.flush()
        except OSError:
            pass
        return handle

    def _close_log(self) -> None:
        if self._log_file is not None:
            try:
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None


class SidecarStartup:
    """Launches the Sidecar and reports how the launch went.

    main.py used to spawn the Sidecar and let a background thread write one
    line to sidecar.log if it never answered, so a Sidecar that could not start
    looked like an App where Play quietly did nothing. This reports
    'starting' -> 'ready' or 'failed' through `on_status`, which now goes to the
    Controls strip's status line (see docs/adr/0013-sidecar-startup-status.md).

    Calling `start()` again is that line's Retry button. `SidecarManager.
    ensure_running` is what makes it safe: a Sidecar that is merely slow is
    waited on rather than replaced. A watch already in flight swallows the
    repeat, so double-clicking Retry spawns nothing twice.

    A watch also provisions the Sidecar's environment when nothing answers on
    the port yet, and says so while it does -- which is what makes a fresh
    checkout play without a manual `pip install` first.
    """

    def __init__(self, manager, on_status, on_warning=None,
                 timeout: float = DEFAULT_HEALTH_TIMEOUT, spawn=None,
                 first_run_timeout: float = FIRST_RUN_TIMEOUT,
                 cache_present=None):
        self._manager = manager
        self._on_status = on_status
        self._on_warning = on_warning or (lambda message: None)
        self._timeout = timeout
        self._first_run_timeout = first_run_timeout
        # Injectable so tests do not have to race a real thread, read the real
        # Hugging Face cache, or install anything.
        self._spawn = spawn or _run_in_background
        self._cache_present = cache_present or sidecar_env.model_cache_present
        self._lock = threading.Lock()
        self._watching = False
        self._stopped = False

    def start(self, backend_model: str = "default") -> None:
        """Spawn the Sidecar (if needed) and watch for it, in the background."""
        with self._lock:
            if self._watching or self._stopped:
                return
            self._watching = True
        self._on_status(STARTING, "")
        self._spawn(lambda: self._watch(backend_model))

    def stop(self) -> None:
        """The App is quitting, so nothing more may be spawned.

        This takes the lock a watch spawns under: a Retry that raced the reader
        window closing would otherwise leave a Sidecar running that no one will
        stop, holding the port against the next launch."""
        with self._lock:
            self._stopped = True

    def _watch(self, backend_model: str) -> None:
        try:
            with self._lock:
                if self._stopped:
                    return
            # Provisioning is only worth its minutes when nothing answers yet:
            # a Sidecar started by hand, or the Docker image, already has an
            # environment and does not need one built beside it.
            if not self._manager.is_healthy():
                self._on_status(PREPARING, SETUP_MESSAGE)
                ok, reason, provisioned = self._manager.prepare()
                if not ok:
                    self._fail(reason, hint="See sidecar/README.md")
                    return
            else:
                provisioned = False

            with self._lock:
                if self._stopped:
                    return
                self._manager.ensure_running(backend_model=backend_model)

            if not self._alive():
                # The spawn itself failed (bad path, or a Python that cannot
                # import uvicorn); waiting a minute would only delay the same
                # verdict. The venv's own output is in the log this names.
                self._fail("The Sidecar did not start.")
                return
            first_run = provisioned or not self._cache_present()
            if first_run:
                self._on_status(PREPARING, MODEL_MESSAGE)
            if self._manager.wait_healthy(
                timeout=self._first_run_timeout if first_run else self._timeout
            ):
                self._on_status(READY, "")
            elif self._alive():
                self._fail(
                    "The Sidecar is still starting "
                    "(it may be downloading or loading its voice model)."
                )
            else:
                self._fail("The Sidecar stopped before it was ready.")
        finally:
            with self._lock:
                self._watching = False

    def _alive(self) -> bool:
        """True when a Sidecar is there to wait for. One the App did not spawn
        counts: something else owns it (started by hand, or the Docker image)."""
        return bool(self._manager.using_existing or self._manager.is_running)

    def _fail(self, note: str, hint: str | None = None) -> None:
        """Report a failure, pointing at whatever the reader has to look at:
        sidecar.log by default, but sidecar/README.md when the environment
        could not be built at all."""
        message = f"{note} {hint or f'See {self._manager.log_path}'}"
        self._on_status(FAILED, message)
        self._on_warning(f"Warning: {message}")


def _run_in_background(callback) -> None:
    threading.Thread(target=callback, daemon=True).start()
