"""Tests for ui.status_text -- the one rule the chrome's status line applies.

The page itself is a NiceGUI view with nothing to unit-test; this rule is the
exception, because the Sidecar's startup shares that line with the Chapter
position and getting the precedence wrong hides a failure the reader has to act
on (see docs/adr/0013-sidecar-startup-status.md).
"""
import unittest
from types import SimpleNamespace

from ui import status_text, window_toggle_text


def controller(**overrides):
    state = {
        "sidecar_starting": False,
        "sidecar_failed": False,
        "sidecar_message": "",
        "error_message": "",
        "total_paragraphs": 0,
        "paragraph_index": 0,
        "status": "Open a chapter to start reading.",
        "window_visible": True,
    }
    state.update(overrides)
    return SimpleNamespace(**state)


class TestStatusText(unittest.TestCase):
    def test_starting_sidecar_is_shown_on_launch(self):
        self.assertEqual(status_text(controller(sidecar_starting=True)), "Starting the Sidecar…")

    def test_a_slow_startup_says_what_it_is_doing(self):
        # Building sidecar/venv, or downloading the model, takes minutes; the
        # line carries the reason instead of "Starting the Sidecar…" the whole
        # time (docs/adr/0016-app-provisions-the-sidecar-environment.md).
        text = status_text(controller(
            sidecar_starting=True, sidecar_message="Setting up the Sidecar's environment…",
        ))
        self.assertEqual(text, "Setting up the Sidecar's environment…")

    def test_failure_is_shown_with_its_message(self):
        message = r"The Sidecar did not start. See C:\sidecar\sidecar.log"
        text = status_text(controller(sidecar_failed=True, sidecar_message=message))
        self.assertEqual(text, message)

    def test_failure_outranks_the_chapter_position(self):
        text = status_text(controller(
            sidecar_failed=True, sidecar_message="The Sidecar did not start.",
            total_paragraphs=9, paragraph_index=2,
        ))
        self.assertEqual(text, "The Sidecar did not start.")

    def test_a_playback_error_outranks_the_starting_notice(self):
        # A retry clears the error it supersedes (controller.report_sidecar),
        # so this ordering is a backstop: anything that went wrong most
        # recently is the more specific thing to say.
        text = status_text(controller(
            sidecar_starting=True, error_message="Sidecar unreachable: refused",
        ))
        self.assertEqual(text, "Sidecar unreachable: refused")

    def test_starting_outranks_the_chapter_position(self):
        text = status_text(controller(
            sidecar_starting=True, total_paragraphs=4, paragraph_index=1,
        ))
        self.assertEqual(text, "Starting the Sidecar…")

    def test_position_is_shown_once_the_sidecar_is_up(self):
        text = status_text(controller(total_paragraphs=4, paragraph_index=1))
        self.assertEqual(text, "2 / 4")

    def test_the_controller_status_is_the_fallback(self):
        self.assertEqual(status_text(controller()), "Open a chapter to start reading.")

    def test_ready_sidecar_leaves_error_and_status_alone(self):
        text = status_text(controller(status="No readable Chapter found on this Page."))
        self.assertEqual(text, "No readable Chapter found on this Page.")


class TestWindowToggleText(unittest.TestCase):
    def test_a_visible_reader_offers_to_hide_it(self):
        self.assertEqual(window_toggle_text(controller()), "Hide page")

    def test_a_hidden_reader_offers_to_show_it(self):
        # Including one that was already hidden when the App launched: that is
        # the session's doing, not a click's (docs/adr/0011).
        self.assertEqual(
            window_toggle_text(controller(window_visible=False)), "Show page",
        )


if __name__ == "__main__":
    unittest.main()
