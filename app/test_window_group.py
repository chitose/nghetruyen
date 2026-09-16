"""Tests for `app/window_group.py`, which makes the Controls strip a tool window
so the App shows up once in the taskbar and in Alt-Tab.

The styles themselves only mean anything to the shell, so what is tested is the
bit arithmetic and the contract `main.py` relies on: it applies the style to the
strip's handle, it does *not* touch ownership, and every way it can fail ends in
`False` plus at most one warning instead of an exception on the startup path.

The Windows path is tested by pretending to be on Windows (`is_windows`) rather
than by being run there, so the same assertions hold on the Linux CI job too.
"""
import unittest
from unittest.mock import patch

from window_group import (
    WS_EX_APPWINDOW,
    WS_EX_TOOLWINDOW,
    XA_ATOM,
    as_tool_window,
    tool_window_style,
)

# A style as WinForms leaves it, plus two bits pywebview sets itself.
WINDOWY = WS_EX_APPWINDOW | 0x08000000 | 0x00000008  # NOACTIVATE | TOPMOST

STRIP = object()


def _on_windows() -> bool:
    return True


def _off_windows() -> bool:
    return False


# `new=` rather than `return_value=`: it replaces the function outright, so the
# test method is not handed a mock argument it does not want. Patching
# `platform_paths`, not `window_group`, keeps this true however window_group
# imports it.
on_windows = patch("platform_paths.is_windows", new=_on_windows)
off_windows = patch("platform_paths.is_windows", new=_off_windows)


class FakeApi:
    """Stands in for the Win32 calls; records what it was asked to do."""

    def __init__(self, hwnd=222, ex_style=WINDOWY, error=None):
        self.handle = hwnd
        self.ex_style_value = ex_style
        self.error = error
        self.calls = []

    def hwnd(self, window):
        self.calls.append(("hwnd", window))
        return self.handle

    def ex_style(self, hwnd):
        if self.error:
            raise self.error
        return self.ex_style_value

    def set_ex_style(self, hwnd, style):
        self.calls.append(("set_ex_style", hwnd, style))

    def refresh(self, hwnd):
        self.calls.append(("refresh", hwnd))


class FakeX11:
    """Stands in for the libX11 calls, with the same recording shape."""

    def __init__(self, xid=333, error=None):
        self.xid_value = xid
        self.error = error
        self.calls = []

    def xid(self, window):
        self.calls.append(("xid", window))
        return self.xid_value

    def set_skip_hints(self, xid):
        if self.error:
            raise self.error
        self.calls.append(("set_skip_hints", xid))


class TestToolWindowStyle(unittest.TestCase):
    def test_it_sets_toolwindow_and_clears_appwindow(self):
        style = tool_window_style(WINDOWY)
        self.assertTrue(style & WS_EX_TOOLWINDOW)
        self.assertFalse(style & WS_EX_APPWINDOW)

    def test_it_leaves_every_other_bit_alone(self):
        # WS_EX_NOACTIVATE (0x08000000) is set by pywebview itself, and the
        # topmost bit is what keeps the strip over the reader.
        style = tool_window_style(WINDOWY)
        self.assertTrue(style & 0x08000000)
        self.assertTrue(style & 0x00000008)

    def test_a_style_that_is_already_a_tool_window_is_unchanged(self):
        plain = WS_EX_TOOLWINDOW | 0x00000008
        self.assertEqual(tool_window_style(plain), plain)


class TestAsToolWindow(unittest.TestCase):
    @on_windows
    def test_it_sets_the_style_on_the_strip_and_refreshes_it(self):
        api = FakeApi()
        warnings = []
        self.assertTrue(as_tool_window(STRIP, on_warning=warnings.append, api=api))
        self.assertEqual(warnings, [])
        self.assertEqual(api.calls, [
            ("hwnd", STRIP),
            ("set_ex_style", 222, tool_window_style(WINDOWY)),
            ("refresh", 222),
        ])

    @on_windows
    def test_it_never_touches_window_ownership(self):
        # Ownership is what made the App survive its own shutdown: Windows
        # disposes of an owned window without raising the event pywebview
        # deregisters by. Guard the decision, not just the absence of a call.
        api = FakeApi()
        as_tool_window(STRIP, api=api)
        self.assertFalse(hasattr(api, "set_owner"))

    @on_windows
    def test_a_missing_handle_warns_once_and_returns_false(self):
        warnings = []
        applied = as_tool_window(STRIP, on_warning=warnings.append, api=FakeApi(hwnd=None))
        self.assertFalse(applied)
        self.assertEqual(len(warnings), 1)
        self.assertIn("native handle", warnings[0])

    @on_windows
    def test_a_failing_call_warns_once_and_does_not_raise(self):
        warnings = []
        applied = as_tool_window(STRIP, on_warning=warnings.append,
                                 api=FakeApi(error=OSError("access denied")))
        self.assertFalse(applied)
        self.assertEqual(len(warnings), 1)
        self.assertIn("access denied", warnings[0])

    @on_windows
    def test_a_warning_callback_is_optional(self):
        self.assertFalse(as_tool_window(STRIP, api=FakeApi(hwnd=None)))


class TestAsToolWindowOnX11(unittest.TestCase):
    """The Linux path: EWMH skip hints, or one warning and no change."""

    @off_windows
    def test_it_sets_the_skip_hints_on_the_strips_x11_window(self):
        api = FakeX11()
        warnings = []
        self.assertTrue(as_tool_window(STRIP, on_warning=warnings.append, api=api))
        self.assertEqual(warnings, [])
        self.assertEqual(api.calls, [("xid", STRIP), ("set_skip_hints", 333)])

    @off_windows
    def test_a_window_with_no_x11_id_says_so_and_returns_false(self):
        # The ordinary Wayland case: GTK there is not on X11, so there is no
        # window ID to hint at -- and the App keeps its taskbar entry.
        warnings = []
        applied = as_tool_window(STRIP, on_warning=warnings.append, api=FakeX11(xid=None))
        self.assertFalse(applied)
        self.assertEqual(len(warnings), 1)
        self.assertIn("Wayland", warnings[0])

    @off_windows
    def test_a_failing_libx11_call_warns_once_and_does_not_raise(self):
        warnings = []
        applied = as_tool_window(STRIP, on_warning=warnings.append,
                                 api=FakeX11(error=OSError("libX11 was not found")))
        self.assertFalse(applied)
        self.assertEqual(len(warnings), 1)
        self.assertIn("libX11 was not found", warnings[0])

    @off_windows
    def test_a_warning_callback_is_optional(self):
        self.assertFalse(as_tool_window(STRIP, api=FakeX11(xid=None)))


class TestX11Hints(unittest.TestCase):
    def test_the_atoms_are_written_as_one_net_wm_state_property(self):
        from window_group import x11_skip_taskbar_hints

        written = {}

        class FakeLibX11:
            def XChangeProperty(self, display, xid, prop, kind, fmt, mode, data, count):
                written.update(
                    display=display, xid=xid, prop=prop, kind=kind,
                    fmt=fmt, count=count, values=list(data),
                )

            def XFlush(self, display):
                written["flushed"] = True

        x11_skip_taskbar_hints(FakeLibX11(), "dpy", 42, 999, [11, 22])
        self.assertEqual(written["xid"], 42)
        self.assertEqual(written["prop"], 999)
        self.assertEqual(written["kind"], XA_ATOM)
        self.assertEqual(written["fmt"], 32)
        self.assertEqual(written["count"], 2)
        self.assertEqual(written["values"], [11, 22])
        self.assertTrue(written["flushed"])


if __name__ == "__main__":
    unittest.main()
