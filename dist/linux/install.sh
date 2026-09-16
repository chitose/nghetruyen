#!/usr/bin/env sh
# dist/linux/install.sh -- install the App into the XDG user directories, so it
# appears in the desktop's application list instead of only being runnable from
# a checkout by hand.
#
# What it installs is the source tree, not a bundle: this copies app/ and
# sidecar/ to $XDG_DATA_HOME/nghetruyen, points the .desktop file's Exec= at
# the copy's run.sh, and puts the icon in the hicolor theme. app/venv and
# sidecar/venv are created on first launch, exactly as they are from a
# checkout, which is why no Python dependencies are installed here.
#
# Idempotent, and safe to re-run after a pull: the copy leaves the two venvs
# alone, so refreshing the source does not throw away a ~700 MB environment or
# the voice model it downloaded. `install.sh --uninstall` takes back everything
# this script created.
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo=$(CDPATH= cd -- "$here/../.." && pwd)
home_dir=${HOME:?install.sh needs HOME}

data_home=${XDG_DATA_HOME:-$home_dir/.local/share}
install_dir=$data_home/nghetruyen
applications=$data_home/applications
icon_dir=$data_home/icons/hicolor/256x256/apps
desktop_file=$applications/nghetruyen.desktop

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$desktop_file" "$icon_dir/nghetruyen.png"
    rm -rf "$install_dir"
    # The caches the install step refreshed. On a real system they belong to
    # every other application too, so they are only removed when they are
    # empty (or, for the two caches, only when this theme is the only entry
    # left in them), and every rmdir refuses a non-empty directory.
    rm -f "$data_home/icons/hicolor/icon-theme.cache"
    rm -f "$applications/mimeinfo.cache"
    # The path this install made, then each parent up to $data_home. Every one
    # of them is shared with other applications on a real system, so every
    # `rmdir` here refuses a non-empty directory -- which is the whole guard.
    rmdir "$icon_dir" 2>/dev/null || true
    rmdir "$data_home/icons/hicolor/256x256" 2>/dev/null || true
    rmdir "$data_home/icons/hicolor" 2>/dev/null || true
    rmdir "$data_home/icons" 2>/dev/null || true
    rmdir "$applications" 2>/dev/null || true
    rmdir "$data_home" 2>/dev/null || true
    echo "Removed:"
    echo "  $install_dir"
    echo "  $desktop_file"
    echo "  $icon_dir/nghetruyen.png"
    echo
    echo "Left alone on purpose: the voice model in ~/.cache/huggingface, and"
    echo "any config.json/session.json written while reading."
    exit 0
fi

for needed in app/main.py app/bootstrap.py app/requirements.txt sidecar/server.py; do
    if [ ! -f "$repo/$needed" ]; then
        echo "Run install.sh from the source checkout: $repo/$needed is missing." >&2
        exit 1
    fi
done

# Copied with tar rather than `cp -r` so the exclusions apply. Two kinds:
# things that are rebuilt rather than shipped (the venvs are made by the App on
# first launch, `__pycache__` is a cache, `dist`/`*.exe` is the Windows
# artifact), and the repository's own scaffolding that has no business in an
# installed copy (the test modules and the test helper, the Sidecar's log, and
# the Windows-only batch/PowerShell launchers). Replacing the tree in place --
# no `rm -rf` first -- is what keeps an existing venv across an upgrade.
copy_tree() {
    src=$1
    dest=$2
    mkdir -p "$dest"
    tar -cf - -C "$src" \
        --exclude=venv \
        --exclude=__pycache__ \
        --exclude='*.pyc' \
        --exclude=build \
        --exclude=dist \
        --exclude='*.exe' \
        --exclude='test_*.py' \
        --exclude=tempdirs.py \
        --exclude='*.log' \
        --exclude='*.bat' \
        --exclude='*.ps1' \
        . | tar -xf - -C "$dest"
}

echo "Installing to $install_dir"
mkdir -p "$install_dir"
copy_tree "$repo/app" "$install_dir/app"
copy_tree "$repo/sidecar" "$install_dir/sidecar"
cp "$here/run.sh" "$install_dir/run.sh"
chmod +x "$install_dir/run.sh"

mkdir -p "$applications" "$icon_dir"
cp "$repo/app/assets/nghetruyen-256.png" "$icon_dir/nghetruyen.png"

# The .desktop file ships with __EXEC__ where the path goes, so one copy of it
# is correct wherever it is installed. Quoted for the case of a home directory
# with a space in it, which the desktop entry spec allows inside double quotes.
sed "s|__EXEC__|\"$install_dir/run.sh\"|" "$here/nghetruyen.desktop" > "$desktop_file"

# Both are caches, and the entry works without them, so they are best effort.
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$applications" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$data_home/icons/hicolor" >/dev/null 2>&1 || true
fi

cat <<EOF
Installed:
  $install_dir          (the App, its Sidecar, and run.sh)
  $desktop_file         (Nghe Truyện in the application list)
  $icon_dir/nghetruyen.png

Start it from the application list, or run:
  $install_dir/run.sh

The first launch builds app/venv and sidecar/venv and downloads the voice
model (~1.3 GB), so give it a few minutes. The documentation stays in the
checkout at $repo/docs. To remove it again:
  $here/install.sh --uninstall
EOF
