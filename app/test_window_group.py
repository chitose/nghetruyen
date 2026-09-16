"""Tests for `app/window_group.py`, which makes the Controls strip a tool window
so the App shows up once in the taskbar and in Alt-Tab.

The styles themselves only mean anything to the shell, so what is tested is the
bit arithmetic and the contract `main.py` relies on: it applies the style to the
strip's handle, it does *not* touch ownership, and every way it can fail ends in
`False` plus at most one warning instead of an exception on the startup path.
"""
import unittest
from unittest.mock import patch

from window_group import (
    WS_EX_APPWINDOW,
    WS_EX_TOOLWINDOW,
    as_tool_window,
    tool_window_style,
)

# A style as WinForms leaves it, plus two bits pywebview sets itself.
WINDOWY = WS_EX_APPWINDOW | 0x08000000 | 0x00000008  # NOACTIVATE | TOPMOST

STRIP = object()


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

    def test_it_never_touches_window_ownership(self):
        # Ownership is what made the App survive its own shutdown: Windows
        # disposes of an owned window without raising the event pywebview
        # deregisters by. Guard the decision, not just the absence of a call.
        api = FakeApi()
        as_tool_window(STRIP, api=api)
        self.assertFalse(hasattr(api, "set_owner"))

    def test_a_missing_handle_warns_once_and_returns_false(self):
        warnings = []
        applied = as_tool_window(STRIP, on_warning=warnings.append, api=FakeApi(hwnd=None))
        self.assertFalse(applied)
        self.assertEqual(len(warnings), 1)
        self.assertIn("native handle", warnings[0])

    def test_a_failing_call_warns_once_and_does_not_raise(self):
        warnings = []
        applied = as_tool_window(STRIP, on_warning=warnings.append,
                                 api=FakeApi(error=OSError("access denied")))
        self.assertFalse(applied)
        self.assertEqual(len(warnings), 1)
        self.assertIn("access denied", warnings[0])

    def test_a_warning_callback_is_optional(self):
        self.assertFalse(as_tool_window(STRIP, api=FakeApi(hwnd=None)))

    @patch("window_group.sys.platform", "darwin")
    def test_off_windows_it_does_nothing_and_says_nothing(self):
        api = FakeApi()
        warnings = []
        self.assertFalse(as_tool_window(STRIP, on_warning=warnings.append, api=api))
        self.assertEqual(api.calls, [])
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
