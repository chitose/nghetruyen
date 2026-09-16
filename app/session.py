"""What the App was doing last time, so it can pick up where it left off.

Settings live in config.json (see config.py); this is the transient part: the
Page the reader was on, where its window sat, and how tall the dock was.
Written once on shutdown, read once on launch. See ADR-0011.
"""
import json
from pathlib import Path

DEFAULTS = {
    "lastUrl": "",        # the Page the reader was showing
    "readerBounds": None,  # [x, y, width, height]
    "dockHeight": None,    # the Controls strip's height in pixels
}


def restore_bounds(stored, screens, min_width=640, min_height=400):
    """The stored [x, y, width, height] if it is still somewhere on a screen.

    `screens` is a list of (x, y, width, height) rects. Returns None when the
    geometry is missing, too small, or entirely off-screen -- e.g. a monitor
    that has been unplugged since -- so the caller falls back to a fresh layout.
    """
    if not isinstance(stored, (list, tuple)) or len(stored) != 4:
        return None
    try:
        x, y, width, height = (int(value) for value in stored)
    except (TypeError, ValueError):
        return None
    if width < min_width or height < min_height:
        return None
    for screen_x, screen_y, screen_width, screen_height in screens:
        if (x < screen_x + screen_width and x + width > screen_x
                and y < screen_y + screen_height and y + height > screen_y):
            return x, y, width, height
    return None


def restore_dock_height(stored, default):
    """The stored dock height, or `default` when it is missing or not a number."""
    if isinstance(stored, (int, float)) and not isinstance(stored, bool):
        return int(stored)
    return default


class Session:
    def __init__(self, path: Path):
        self.path = path
        self._data = self._load()

    def _load(self) -> dict:
        data = dict(DEFAULTS)
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return data
        if isinstance(stored, dict):
            data.update({key: stored[key] for key in DEFAULTS if key in stored})
        return data

    def get(self, key, default=None):
        return self._data.get(key, default)

    def update(self, **values) -> None:
        self._data.update(values)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
