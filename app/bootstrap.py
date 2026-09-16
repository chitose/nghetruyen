"""Self-bootstrapping launcher: creates app/venv, installs requirements.txt,
then hands off to main.py -- so a compiled .exe wrapper (built with
PyInstaller, see app/README.md), run.bat, or run.sh is a single
double-click/command instead of a manual venv/pip dance.

The install also re-runs whenever requirements.txt changes (e.g. a new
dependency is added), not just on first run -- otherwise an existing venv
silently keeps missing the new package.

Runs under a real system Python (found via PATH), not the app's own venv --
that venv doesn't exist yet on first run, which is the whole point. Which
names count as "a system Python", and where the venv puts its interpreter,
differ per platform and live in `platform_paths.py` (ADR-0017).
"""
import hashlib
import subprocess
import sys
from pathlib import Path

import platform_paths

if getattr(sys, "frozen", False):
    # Running as a PyInstaller-compiled .exe -- sys.executable is the exe itself.
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent

VENV_DIR = APP_DIR / "venv"
VENV_PYTHON = platform_paths.venv_python(VENV_DIR)
REQUIREMENTS = APP_DIR / "requirements.txt"
# Written after a successful install. A mismatch means requirements.txt changed
# since, so the venv needs refreshing.
REQUIREMENTS_MARKER = VENV_DIR / "requirements.sha256"


def _requirements_hash() -> str:
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def _installed_requirements_hash():
    try:
        return REQUIREMENTS_MARKER.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _install_requirements() -> None:
    subprocess.run(
        [str(VENV_PYTHON), "-m", "pip", "install", "-r", str(REQUIREMENTS)],
        check=True, cwd=APP_DIR,
    )
    REQUIREMENTS_MARKER.write_text(_requirements_hash(), encoding="utf-8")


def bootstrap() -> None:
    created = False
    if not VENV_PYTHON.exists():
        system_python = platform_paths.python_on_path()
        if not system_python:
            print(
                f"Python was not found on PATH. {platform_paths.python_install_hint()}",
                file=sys.stderr,
            )
            # Only a double-clicked run.bat has a console to keep open; under
            # run.sh (or a pipe) this would just hang waiting on a TTY.
            if platform_paths.is_windows():
                input("Press Enter to close...")
            sys.exit(1)
        print("First run -- setting up app/venv, this takes a minute...")
        subprocess.run(
            platform_paths.create_venv_argv(system_python, VENV_DIR),
            check=True, cwd=APP_DIR,
        )
        created = True

    if created or _installed_requirements_hash() != _requirements_hash():
        if not created:
            print("requirements.txt changed -- updating app/venv...")
        _install_requirements()

    subprocess.run([str(VENV_PYTHON), "main.py"], cwd=APP_DIR)


if __name__ == "__main__":
    bootstrap()
