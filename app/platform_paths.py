# app/platform_paths.py
"""The App's platform differences, in one place.

Everything here used to be assumed: a virtualenv's interpreter was always
`venv/Scripts/python.exe`, settings always lived under `%APPDATA%`, and the
interpreter to build a venv from was always `python` (ADR-0017). Each of those
is a Windows fact, and each one had leaked into a different module -- so this
is the one module that is allowed to know which platform it is on.

Stdlib only, and imported by `main.py`, `bootstrap.py`, `sidecar_env.py`,
`sidecar_manager.py`, `splash.py`, `window_group.py` and `icon.py`, the same
way `sidecar_env.py` already was. Nothing here touches the Sidecar's own venv
layout *inside* the Sidecar: that process is stdlib-plus-requirements and knows
nothing about this App.
"""
import os
import shutil
import sys
from pathlib import Path

# The interpreter to build a venv from, in the order they are tried. On
# Windows `python` is the real name; on Linux and macOS `python3` is, and a bare
# `python` often does not exist at all.
PYTHON_CANDIDATES = ("python", "python3", "python3.13", "python3.12", "python3.11")

# Where a virtualenv puts its interpreter. POSIX uses bin/python (plus
# bin/python3), Windows uses Scripts/python.exe. Both are relative to the venv
# directory, which is why these are parts rather than absolute paths.
VENV_BIN_DIRECTORY = ("Scripts",) if os.name == "nt" else ("bin",)
VENV_PYTHON_NAME = "python.exe" if os.name == "nt" else "python"


def is_windows() -> bool:
    """Reads `os.name` rather than `sys.platform`, which means the same thing
    here -- `sys.platform` cannot be reassigned on the `sys` module, so the
    tests could not say "pretend this is Linux" if it read that instead."""
    return os.name == "nt"


def venv_bin_directory(venv_dir) -> Path:
    """The directory a virtualenv's executables live in."""
    return Path(venv_dir).joinpath(*VENV_BIN_DIRECTORY)


def venv_python(venv_dir) -> Path:
    """The interpreter inside `venv_dir` -- what the App spawns uvicorn with."""
    return venv_bin_directory(venv_dir) / VENV_PYTHON_NAME


def create_venv_argv(interpreter: str, venv_dir) -> list:
    """How to create a virtualenv with `interpreter`, on any platform.

    The command is the same everywhere; what differs is which interpreter is
    passed in, and that is what `python_on_path` is for.
    """
    return [interpreter, "-m", "venv", str(venv_dir)]


def python_on_path() -> str | None:
    """A system interpreter, found on PATH.

    Which names to look for is the difference being handled here: a Linux box
    with only `python3` is the normal case, not a broken install. The frozen
    case is what this exists for -- a PyInstaller exe has no interpreter of its
    own, so the Sidecar's venv has to be built by one off PATH.
    """
    for name in PYTHON_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


def data_dir(name: str = "reading-web") -> Path:
    """Where the App keeps settings, session, and its log.

    Windows keeps `%APPDATA%\\reading-web`: the folder name predates the App's
    name and is kept so an existing install's settings survive (see
    `config.py`). Linux and macOS follow the XDG base-directory rule, falling
    back to `~/.local/share` when XDG_DATA_HOME is unset -- so a Linux install
    sits where a desktop user looks for their app data rather than inside a
    fake AppData tree.
    """
    if is_windows():
        return Path.home() / "AppData" / "Roaming" / name
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / name


def python_install_hint() -> str:
    """What to tell the reader when no usable Python was found at all."""
    if is_windows():
        return "Install Python 3.11+ from https://python.org and try again."
    return (
        "Install Python 3.10+ with the venv module and try again "
        "(Debian/Ubuntu: sudo apt install python3 python3-venv; "
        "Fedora: sudo dnf install python3; Arch: sudo pacman -S python)."
    )


def frozen() -> bool:
    """True inside a PyInstaller build -- the standalone NgheTruyen.exe."""
    return bool(getattr(sys, "frozen", False))
