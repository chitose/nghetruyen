"""Keeps the Controls window docked under the reader window.

The App is two OS windows (ADR-0010); this is what makes them read as one.
The Controls window is frameless, the same width as the reader, and flush
against its bottom edge, following every move and resize. When the reader is
maximized it pins to the bottom of the screen instead of being pushed off it.

Minimizing the reader no longer hides the Controls window: the strip is the
window with the taskbar entry (window_group.py makes the reader the tool
window instead), so it has to stay up for the App to still be reachable.

A frameless window has no native resize border, so the strip's height is
whatever the reader last dragged its grip to (`Dock.set_height`, driven by the
grip in `ui.py`); every later reposition keeps that height.
"""

CONTROLS_HEIGHT = 176
MIN_CONTROLS_HEIGHT = 96
MAX_CONTROLS_HEIGHT = 640


def _clamp_height(height) -> int:
    return max(MIN_CONTROLS_HEIGHT, min(int(height), MAX_CONTROLS_HEIGHT))


def controls_bounds(content, screen, height=CONTROLS_HEIGHT):
    """Where the docked Controls window belongs.

    `content` and `screen` are (x, y, width, height) rectangles. The Controls
    window keeps the reader's x and width and sits directly below it, unless
    that would push it past the bottom of `screen` -- then it pins to the
    screen's bottom edge and overlaps the reader (the maximized case).
    """
    content_x, content_y, content_width, content_height = content
    screen_x, screen_y, screen_width, screen_height = screen
    y = max(screen_y, min(content_y + content_height, screen_y + screen_height - height))
    return content_x, y, content_width, height


class Dock:
    """Positions the Controls window under the reader and keeps it there."""

    def __init__(self, content_window, controls_window, find_screen, height=CONTROLS_HEIGHT):
        self._content = content_window
        self._controls = controls_window
        self._find_screen = find_screen
        self.height = _clamp_height(height)
        self._move_origin = None
        self._floating = False  # True once the reader moves the strip by hand

        # The reader drives the dock; the Controls window re-syncs once it is up.
        content_window.events.shown += self.reposition
        content_window.events.moved += self.reposition
        content_window.events.resized += self.reposition
        content_window.events.maximized += self.reposition
        controls_window.events.shown += self.reposition

    def reposition(self, *_args) -> None:
        """Attach the strip under the reader. The reader's own move/resize
        events call this, which also re-attaches a strip moved by hand."""
        self._floating = False
        content = (
            self._content.x, self._content.y,
            self._content.width, self._content.height,
        )
        screen = self._find_screen(content[0], content[1])
        if screen is None:
            # No screen info (headless/CI): still dock directly below.
            screen = (content[0], 0, content[2], content[1] + content[3] + self.height)
        x, y, width, height = controls_bounds(content, screen, self.height)
        self._controls.move(x, y)
        self._controls.resize(width, height)

    def set_height(self, height) -> None:
        """The reader dragged the grip here; remember it and apply it.

        While the strip is floating (moved by hand) this resizes it in place.
        Re-docking here is what used to yank the strip back down to the reader
        the moment its grip was touched."""
        try:
            height = int(height)
        except (TypeError, ValueError):
            return
        self.height = _clamp_height(height)
        if self._floating:
            self._controls.resize(self._controls.width, self.height)
        else:
            self.reposition()

    def begin_move(self) -> None:
        """The reader grabbed the title bar; remember where the strip started."""
        self._move_origin = (self._controls.x, self._controls.y)

    def move_by(self, dx, dy) -> None:
        if self._move_origin is None:
            return
        try:
            dx, dy = int(dx), int(dy)
        except (TypeError, ValueError):
            return
        x, y = self._move_origin
        self._controls.move(x + dx, y + dy)
        self._floating = True

    def end_move(self) -> None:
        self._move_origin = None


def dock(content_window, controls_window, find_screen, height=CONTROLS_HEIGHT) -> Dock:
    """Dock controls under content and keep it there."""
    return Dock(content_window, controls_window, find_screen, height)
