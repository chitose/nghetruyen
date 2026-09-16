"""Tests for the startup window (`app/splash.py`).

The window itself is Win32 and cannot be asserted on from here -- showing one
would put a window on screen -- so what is tested is the rule that turns a
Sidecar state into the line it shows, and that `Splash` is safe to drive from
another thread in any order: `main.py` updates it from the startup thread and
closes it from a pywebview event, and closing it before it is up has to work.
"""
import unittest

from sidecar_manager import FAILED, MODEL_MESSAGE, PREPARING, READY, STARTING
from splash import Splash, status_line


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


if __name__ == "__main__":
    unittest.main()
