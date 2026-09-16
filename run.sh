#!/usr/bin/env sh
# run.sh -- the Linux launcher, and the counterpart of run.bat.
#
# It stays this thin on purpose: bootstrap.py already owns everything that
# makes a fresh checkout runnable -- creating app/venv, installing
# requirements.txt, re-installing when that file changes, and handing off to
# main.py. All this has to do is find a Python new enough to run bootstrap.py
# and report clearly when there is not one. See
# docs/adr/0017-linux-launcher.md.
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$here/app"

# bootstrap.py provisions for the App and then main.py provisions the Sidecar,
# so what has to be here is bootstrap.py's own floor: it is stdlib-only, and
# `python -m venv` needs 3.10 and the venv module (a separate package for
# `python3-venv` on Debian and Ubuntu, and absent on a minimal install).
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
    echo "Then run this script again. See app/README.md for the other system" >&2
    echo "packages the App needs (PortAudio, and a Web View backend)." >&2
    exit 1
fi

exec "$python" bootstrap.py
