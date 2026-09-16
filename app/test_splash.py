"""Tests for the startup window (`app/splash.py`).

The window itself is a real window and cannot be asserted on from here --
showing one would put it on screen -- so what is tested is the rule that turns
a Sidecar state into the line it shows, that both implementations are safe to
drive from another thread in any order (`main.py` updates it from the startup
thread and closes it from a pywebview event, and closing it before it is up has
to work), and that `make_splash` picks the right one per platform (ADR-0017).
"""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import platform_paths
from sidecar_manager import FAILED, MODEL_MESSAGE, PREPARING, READY, STARTING
from splash import Splash, TkSplash, make_splash, status_line


class TestStatusLine(unittest.TestCase):
    def test_before_anything_is_reported_it_says_starting_up(self):
        self.assertEqual(status_line(STARTING), "Starting up…")

    def test_the_sidecars_own_words_win(self):
        # SidecarStartup writes all of these as the message: building the venv,
        # downloading the model, or why it failed.
        for state in (STARTING, PREPARING, FAILED):
            with self.subTest(state=state):
                self.assertEqual(
                    status_line(state, MODEL_MESSAGE),
                    MODEL_MESSAGE,
                )

    def test_ready_is_short_and_says_nothing_about_the_chapter(self):
        # Once the App's windows are up the Controls strip takes over, so
        # "Open a chapter to start reading." would be noise here.
        self.assertEqual(status_line(READY), "Ready.")

    def test_a_failure_without_a_message_still_says_something(self):
        self.assertEqual(status_line(FAILED), "Starting up…")


class TestSplash(unittest.TestCase):
    def test_status_updates_before_start_never_raise(self):
        splash = Splash()
        splash.set_status(STARTING, "Setting up the Sidecar's environment…")
        splash.set_status(READY)

    def test_closing_before_it_is_up_is_allowed_and_idempotent(self):
        splash = Splash()
        splash.close()
        splash.close()
        splash.set_status(READY)  # too late for the window, but not an error

    def test_a_warning_reaches_the_callback_main_py_hands_over(self):
        # main.py passes warn, so a splash that cannot be created lands in
        # nghetruyen.log instead of disappearing.
        warnings = []
        Splash(on_warning=warnings.append)._warn("Warning: no startup window (test).")
        self.assertEqual(warnings, ["Warning: no startup window (test)."])

    def test_warning_is_optional(self):
        Splash(on_warning=None)._warn("nothing to report")  # must not raise


class TestLazyWin32Types(unittest.TestCase):
    """The Win32 ctypes types are built on first use, not at import.

    `ctypes.WINFUNCTYPE` and `ctypes.WinDLL` do not exist off Windows, and
    `main.py` imports this module on every platform because `make_splash` lives
    here -- building them at module scope made `import splash` itself fail on
    Linux (ADR-0017). These two tests are the pair that keeps that honest: the
    module imports everywhere, and the types still work where they are used.
    """

    def test_the_win32_types_are_not_built_at_import(self):
        # The exact regression: defining WNDPROC (and friends) at module scope
        # made `import splash` itself fail on Linux, taking main.py with it,
        # because ctypes.WINFUNCTYPE does not exist there. A fresh interpreter
        # is the only honest way to ask "what happens at import" once tests in
        # this process may already have triggered the definitions.
        probe = (
            "import splash; "
            "print(','.join(n for n in ('WNDPROC', 'WNDCLASSEXW', 'PAINTSTRUCT') "
            "if hasattr(splash, n)))"
        )
        done = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=Path(__file__).parent, capture_output=True, text=True, check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "", "built at import: " + done.stdout)

    def test_building_them_produces_usable_ctypes_types(self):
        if not platform_paths.is_windows():
            self.skipTest("ctypes.WINFUNCTYPE is Windows-only")
        import ctypes

        import splash

        splash._win32_types()
        self.assertTrue(issubclass(splash.WNDCLASSEXW, ctypes.Structure))
        self.assertTrue(issubclass(splash.PAINTSTRUCT, ctypes.Structure))
        # Constructible, and with the field list actually applied -- an empty
        # _fields_ would mean the definitions silently did not take.
        self.assertGreater(len(splash.PAINTSTRUCT._fields_), 0)
        self.assertGreater(len(splash.WNDCLASSEXW._fields_), 0)

    def test_building_twice_is_harmless(self):
        if not platform_paths.is_windows():
            self.skipTest("ctypes.WINFUNCTYPE is Windows-only")
        import splash

        splash._win32_types()
        first = splash.WNDCLASSEXW
        splash._win32_types()
        self.assertIs(splash.WNDCLASSEXW, first)  # cached, not rebuilt


class TestTkSplash(unittest.TestCase):
    """The Linux implementation's thread-safety contract, not its window."""

    def test_status_updates_before_start_never_raise(self):
        splash = TkSplash()
        splash.set_status(STARTING, "Setting up the Sidecar's environment…")
        splash.set_status(READY)

    def test_closing_before_it_is_up_is_allowed_and_idempotent(self):
        splash = TkSplash()
        splash.close()
        splash.close()
        splash.set_status(READY)  # too late for the window, but not an error

    def test_a_warning_reaches_the_callback(self):
        warnings = []
        TkSplash(on_warning=warnings.append)._warn("Warning: no startup window (test).")
        self.assertEqual(warnings, ["Warning: no startup window (test)."])

    def test_warning_is_optional(self):
        TkSplash(on_warning=None)._warn("nothing to report")  # must not raise

    def test_a_run_with_no_tkinter_warns_once_and_stops(self):
        # No display, no Tk: one line in nghetruyen.log and the App starts.
        warnings = []
        splash = TkSplash(on_warning=warnings.append)
        with patch.dict("sys.modules", {"tkinter": None}):
            splash._run()
        self.assertEqual(len(warnings), 1)
        self.assertIn("startup window", warnings[0])


class TestMakeSplash(unittest.TestCase):
    def test_windows_gets_the_win32_window(self):
        with patch("platform_paths.is_windows", return_value=True):
            self.assertIsInstance(make_splash(), Splash)

    def test_linux_gets_the_tk_window(self):
        with patch("platform_paths.is_windows", return_value=False):
            self.assertIsInstance(make_splash(), TkSplash)

    def test_the_callers_arguments_are_passed_through(self):
        warnings = []

        def on_warning(message):
            warnings.append(message)

        with patch("platform_paths.is_windows", return_value=False):
            splash = make_splash(icon_path="/tmp/icon.png", on_warning=on_warning)
        self.assertEqual(splash._icon_path, "/tmp/icon.png")
        splash._warn("Warning: test")
        self.assertEqual(warnings, ["Warning: test"])


if __name__ == "__main__":
    unittest.main()
