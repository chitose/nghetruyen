# app/icon.py
"""The App's mark, in whichever file format the platform actually reads.

Both assets are baked by `make_icon.py` from `assets/nghetruyen-source.png`
(ADR-0015), and both are bundled as data by `NgheTruyen.spec`, so this is a
choice between two files that already ship rather than anything generated at
runtime:

- `nghetruyen.ico` is what Windows wants: the exe's own resources, the two
  windows' title bars, and the taskbar.
- `nghetruyen-256.png` is the same mark as a plain PNG, which is what the
  desktop on Linux reads. GTK can be built without an ICO loader, and a
  missing loader there fails at window creation rather than falling back.

`platform_paths.is_windows()` is the one place that knows the platform, so
this is its only other caller for icon selection: `main.py` asks for a path
and passes it on to pywebview and NiceGUI, neither of which gets told which
platform it is running on.
"""
from pathlib import Path

import platform_paths

ICO_PARTS = ("assets", "nghetruyen.ico")
PNG_PARTS = ("assets", "nghetruyen-256.png")


def app_icon_path(bundle_dir) -> Path:
    """The icon file to hand pywebview and NiceGUI on this platform."""
    parts = ICO_PARTS if platform_paths.is_windows() else PNG_PARTS
    return Path(bundle_dir).joinpath(*parts)
