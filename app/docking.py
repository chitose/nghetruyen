"""Keeps the reader window docked above the Controls strip.

The strip is the App's primary window (window_group.py makes the reader a
tool window, so the strip is the one with the taskbar entry) and now a normal
one -- fully resizable, freely moved by the user, with its own native title
bar. The reader docks above it instead, matching its width, whenever the
strip moves, resizes, or is maximized, or whenever the reader itself is shown
or resized.

Only the reader's x, y and width are the dock's business: its height is its
own, whatever it was last resized to (natively, or restored from
session.json). When docking it above the strip would push it off the top of
`screen`, it pins to the screen's top edge instead and overlaps the strip --
the mirror image of the old "pins to the screen's bottom edge" case, and for
the same reason: nothing pushes a window off a screen it is already on.

`page_visible`, if given, is asked before every reposition and skipped on a
`False`: pywebview's Windows backend moves and resizes a window with
`SetWindowPos(..., SWP_SHOWWINDOW)`, which un-hides it as a side effect --
so moving the strip while Hide page has the reader tucked away would show it
again. Nothing is lost by skipping: the reader is already wherever it needs
to be by the time Show page calls `reposition()` itself.
"""


def page_bounds(strip, screen, height) -> tuple:
    """Where the docked reader window belongs.

    `strip` and `screen` are (x, y, width, height) rectangles; `height` is
    the reader's own. The reader keeps the strip's x and width and sits
    directly above it, unless that would push it off the top of `screen` --
    then it pins to the screen's top edge and overlaps the strip.
    """
    strip_x, strip_y, strip_width, _strip_height = strip
    screen_x, screen_y, screen_width, screen_height = screen
    y = max(screen_y, min(strip_y - height, screen_y + screen_height - height))
    return strip_x, y, strip_width, height


class Dock:
    """Positions the reader window above the strip and keeps it there."""

    def __init__(self, strip_window, page_window, find_screen, page_visible=lambda: True):
        self._strip = strip_window
        self._page = page_window
        self._find_screen = find_screen
        self._page_visible = page_visible

        # The strip drives the dock; the reader re-syncs once it is up, and
        # again on its own resize (which otherwise could leave it a different
        # width than the strip).
        strip_window.events.shown += self.reposition
        strip_window.events.moved += self.reposition
        strip_window.events.resized += self.reposition
        strip_window.events.maximized += self.reposition
        page_window.events.shown += self.reposition
        page_window.events.resized += self.reposition

    def reposition(self, *_args) -> None:
        """Attach the reader above the strip. Either window's own move/resize
        events call this, which also re-attaches a reader moved by hand."""
        if not self._page_visible():
            return
        strip = (self._strip.x, self._strip.y, self._strip.width, self._strip.height)
        screen = self._find_screen(strip[0], strip[1])
        if screen is None:
            # No screen info (headless/CI): still dock directly above.
            screen = (strip[0], 0, strip[2], strip[1] + strip[3])
        x, y, width, height = page_bounds(strip, screen, self._page.height)
        self._page.move(x, y)
        self._page.resize(width, height)


def dock(strip_window, page_window, find_screen, page_visible=lambda: True) -> Dock:
    """Dock page above strip and keep it there."""
    return Dock(strip_window, page_window, find_screen, page_visible)
