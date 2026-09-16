#!/usr/bin/env sh
# dist/linux/run.sh -- the launcher for an installed copy (install.sh).
#
# The same two jobs as the checkout's run.sh: find a Python new enough, and
# hand off to the App's own bootstrap.py, which creates app/venv, installs the
# App's dependencies, and starts main.py -- which in turn builds sidecar/venv
# and starts the Sidecar. Everything below the interpreter check lives in
# bootstrap.py so there is one implementation of it (ADR-0016, ADR-0017).
#
# Resolved through $0 rather than a hardcoded path: install.sh writes the real
# directory into Exec=, but a symlink on PATH still works this way.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$root/app"

# bootstrap.py is stdlib-only, but `python -m venv` needs 3.10 and the venv
# module -- a separate package (`python3-venv`) on Debian and Ubuntu, and
# absent altogether from a minimal install.
minimum="3.10"
ok() { [ "$(printf '%s\n' "$minimum" "$1" | sort -V | head -n1)" = "$minimum" ]; }

python=""
for candidate in python3 python; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    found=$("$candidate" -c 'import sys, venv; print(".".join(map(str, sys.version_info[:2])))' 2>/dev/null) || continue
    if ok "$found"; then
        python=$candidate
        break
    fi
done

if [ -z "$python" ]; then
    echo "Nghe Truyện needs Python $minimum or newer, with the venv module." >&2
    echo >&2
    echo "  Debian/Ubuntu:  sudo apt install python3 python3-venv" >&2
    echo "  Fedora:         sudo dnf install python3" >&2
    echo "  Arch:           sudo pacman -S python" >&2
    echo >&2
    echo "Then start Nghe Truyện again. See app/README.md in the source" >&2
    echo "checkout for the other system packages it needs (PortAudio, and a" >&2
    echo "Web View backend)." >&2
    exit 1
fi

exec "$python" bootstrap.py
