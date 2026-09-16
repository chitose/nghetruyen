"""Self-bootstrapping launcher: creates app/venv and installs
requirements.txt on first run, then hands off to main.py -- so a compiled
.exe wrapper (built with PyInstaller, see app/README.md) or run.bat is a
single double-click/command instead of a manual venv/pip dance.

Runs under a real system Python (found via PATH), not the app's own venv --
that venv doesn't exist yet on first run, which is the whole point.
"""
import shutil
import subprocess
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # Running as a PyInstaller-compiled .exe -- sys.executable is the exe itself.
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent

VENV_DIR = APP_DIR / "venv"
VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"


def bootstrap() -> None:
    if not VENV_PYTHON.exists():
        system_python = shutil.which("python")
        if not system_python:
            print(
                "Python was not found on PATH. Install Python 3.11+ from "
                "https://python.org and try again.",
                file=sys.stderr,
            )
            input("Press Enter to close...")
            sys.exit(1)
        print("First run -- setting up app/venv, this takes a minute...")
        subprocess.run([system_python, "-m", "venv", str(VENV_DIR)], check=True, cwd=APP_DIR)
        subprocess.run(
            [str(VENV_PYTHON), "-m", "pip", "install", "-r", "requirements.txt"],
            check=True, cwd=APP_DIR,
        )
    subprocess.run([str(VENV_PYTHON), "main.py"], cwd=APP_DIR)


if __name__ == "__main__":
    bootstrap()
