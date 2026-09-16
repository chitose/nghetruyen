"""Spawns and supervises the Sidecar (sidecar/server.py) as a child process.

See docs/adr/0009-standalone-app-replaces-extension.md: the App starts the
Sidecar automatically instead of the reader running it manually in a
terminal (ADR-0001's "started manually" cost moves up one level).

The Sidecar is a console program, but it is never meant to show a window: a
console-less App (pythonw, or a PyInstaller --noconsole build) would otherwise
make Windows allocate a visible console for it. It runs with CREATE_NO_WINDOW
and its output goes to sidecar.log instead, so startup errors stay readable.
"""
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

LOG_NAME = "sidecar.log"


def _hidden_window_kwargs() -> dict:
    """Windows only: keep the Sidecar from getting its own console window."""
    if sys.platform != "win32":
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
                "Is sidecar/venv set up? See sidecar/README.md."
            )

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
