"""Spawns and supervises the Sidecar (sidecar/server.py) as a child process.

See docs/adr/0009-standalone-app-replaces-extension.md: the App starts the
Sidecar automatically instead of the reader running it manually in a
terminal (ADR-0001's "started manually" cost moves up one level).
"""
import subprocess
import time
import urllib.error
import urllib.request


class SidecarManager:
    def __init__(self, python_exe: str, cwd: str, port: int = 8934):
        self.python_exe = python_exe
        self.cwd = cwd
        self.port = port
        self._proc = None

    def start(self) -> None:
        if self._proc is not None:
            return
        self._proc = subprocess.Popen(
            [self.python_exe, "-m", "uvicorn", "server:app", "--port", str(self.port)],
            cwd=self.cwd,
        )

    def wait_healthy(self, timeout: float = 60.0, interval: float = 0.5) -> bool:
        deadline = time.monotonic() + timeout
        url = f"http://localhost:{self.port}/speakers"
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2):
                    return True
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(interval)
        return False

    def stop(self) -> None:
        if self._proc is None:
            return
        self._proc.terminate()
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        self._proc = None

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None
