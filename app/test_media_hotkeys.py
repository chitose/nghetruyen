"""Tests for `app/media_hotkeys.py`, which registers the three media-key
hotkeys system-wide via `RegisterHotKey`.

The ctypes plumbing is faked the same way `test_window_group.py` fakes the
Win32 calls: what is worth asserting is the dispatch (a WM_HOTKEY with a given
id calls the right handler, anything else is left to DefWindowProcW) and the
contract `main.py` relies on -- every way this can fail ends in `False`/`None`
plus at most one warning, never an exception.
"""
import unittest
from unittest.mock import patch

from media_hotkeys import (
    NEXT_ID,
    PLAY_PAUSE_ID,
    PREV_ID,
    VK_MEDIA_NEXT_TRACK,
    VK_MEDIA_PLAY_PAUSE,
    VK_MEDIA_PREV_TRACK,
    WM_HOTKEY,
    MediaHotkeys,
    hotkey_vks,
    start,
)


def _on_windows() -> bool:
    return True


def _off_windows() -> bool:
    return False


on_windows = patch("platform_paths.is_windows", new=_on_windows)
off_windows = patch("platform_paths.is_windows", new=_off_windows)


class FakeApi:
    """Stands in for the Win32 calls; records what it was asked to do."""

    def __init__(self, hwnd=111, register_ok=True, error=None):
        self.hwnd_value = hwnd
        self.register_ok = register_ok
        self.error = error
        self.calls = []
        self.on_message = None

    def create_window(self, on_message):
        self.calls.append(("create_window",))
        if self.error:
            raise self.error
        self.on_message = on_message
        return self.hwnd_value

    def register_hotkey(self, hwnd, hotkey_id, vk):
        self.calls.append(("register_hotkey", hwnd, hotkey_id, vk))
        return self.register_ok

    def unregister_hotkey(self, hwnd, hotkey_id):
        self.calls.append(("unregister_hotkey", hwnd, hotkey_id))

    def destroy_window(self, hwnd):
        self.calls.append(("destroy_window", hwnd))


class TestHotkeyVks(unittest.TestCase):
    def test_binds_the_three_media_keys(self):
        self.assertEqual(hotkey_vks(), {
            PLAY_PAUSE_ID: VK_MEDIA_PLAY_PAUSE,
            NEXT_ID: VK_MEDIA_NEXT_TRACK,
            PREV_ID: VK_MEDIA_PREV_TRACK,
        })


class TestMediaHotkeys(unittest.TestCase):
    def test_start_creates_the_window_and_registers_every_hotkey(self):
        api = FakeApi()
        hotkeys = MediaHotkeys(lambda: None, lambda: None, lambda: None, api=api)
        self.assertTrue(hotkeys.start())
        self.assertEqual(api.calls, [
            ("create_window",),
            ("register_hotkey", 111, PLAY_PAUSE_ID, VK_MEDIA_PLAY_PAUSE),
            ("register_hotkey", 111, NEXT_ID, VK_MEDIA_NEXT_TRACK),
            ("register_hotkey", 111, PREV_ID, VK_MEDIA_PREV_TRACK),
        ])

    def test_play_pause_hotkey_calls_its_handler(self):
        calls = []
        api = FakeApi()
        hotkeys = MediaHotkeys(lambda: calls.append("play_pause"), lambda: None, lambda: None, api=api)
        hotkeys.start()
        result = api.on_message(999, WM_HOTKEY, PLAY_PAUSE_ID, 0)
        self.assertEqual(calls, ["play_pause"])
        self.assertEqual(result, 0)

    def test_next_and_previous_hotkeys_call_their_handlers(self):
        calls = []
        api = FakeApi()
        hotkeys = MediaHotkeys(
            lambda: None, lambda: calls.append("next"), lambda: calls.append("previous"), api=api,
        )
        hotkeys.start()
        api.on_message(999, WM_HOTKEY, NEXT_ID, 0)
        api.on_message(999, WM_HOTKEY, PREV_ID, 0)
        self.assertEqual(calls, ["next", "previous"])

    def test_a_message_that_is_not_a_hotkey_is_left_unhandled(self):
        api = FakeApi()
        hotkeys = MediaHotkeys(lambda: None, lambda: None, lambda: None, api=api)
        hotkeys.start()
        self.assertIsNone(api.on_message(999, 0x000F, PLAY_PAUSE_ID, 0))  # WM_PAINT

    def test_an_unknown_hotkey_id_is_a_noop(self):
        api = FakeApi()
        hotkeys = MediaHotkeys(lambda: None, lambda: None, lambda: None, api=api)
        hotkeys.start()
        self.assertEqual(api.on_message(999, WM_HOTKEY, 999, 0), 0)

    def test_a_handler_that_raises_does_not_escape(self):
        def boom():
            raise RuntimeError("nope")

        api = FakeApi()
        hotkeys = MediaHotkeys(boom, lambda: None, lambda: None, api=api)
        hotkeys.start()
        self.assertEqual(api.on_message(999, WM_HOTKEY, PLAY_PAUSE_ID, 0), 0)

    def test_a_missing_window_handle_warns_once_and_returns_false(self):
        warnings = []
        api = FakeApi(hwnd=None)
        hotkeys = MediaHotkeys(lambda: None, lambda: None, lambda: None, on_warning=warnings.append, api=api)
        self.assertFalse(hotkeys.start())
        self.assertEqual(len(warnings), 1)

    def test_a_hotkey_already_owned_by_another_app_warns_once_and_returns_false(self):
        warnings = []
        api = FakeApi(register_ok=False)
        hotkeys = MediaHotkeys(lambda: None, lambda: None, lambda: None, on_warning=warnings.append, api=api)
        self.assertFalse(hotkeys.start())
        self.assertEqual(len(warnings), 1)
        self.assertIn("another app", warnings[0])

    def test_a_failing_call_warns_once_and_does_not_raise(self):
        warnings = []
        api = FakeApi(error=OSError("access denied"))
        hotkeys = MediaHotkeys(lambda: None, lambda: None, lambda: None, on_warning=warnings.append, api=api)
        self.assertFalse(hotkeys.start())
        self.assertEqual(len(warnings), 1)
        self.assertIn("access denied", warnings[0])

    def test_stop_unregisters_every_hotkey_and_destroys_the_window(self):
        api = FakeApi()
        hotkeys = MediaHotkeys(lambda: None, lambda: None, lambda: None, api=api)
        hotkeys.start()
        api.calls.clear()
        hotkeys.stop()
        self.assertEqual(api.calls, [
            ("unregister_hotkey", 111, PLAY_PAUSE_ID),
            ("unregister_hotkey", 111, NEXT_ID),
            ("unregister_hotkey", 111, PREV_ID),
            ("destroy_window", 111),
        ])

    def test_stop_before_start_is_safe(self):
        MediaHotkeys(lambda: None, lambda: None, lambda: None, api=FakeApi()).stop()

    def test_stop_is_safe_to_call_twice(self):
        api = FakeApi()
        hotkeys = MediaHotkeys(lambda: None, lambda: None, lambda: None, api=api)
        hotkeys.start()
        hotkeys.stop()
        api.calls.clear()
        hotkeys.stop()
        self.assertEqual(api.calls, [])


class TestStart(unittest.TestCase):
    @on_windows
    def test_on_windows_it_returns_a_started_instance(self):
        api = FakeApi()
        hotkeys = start(lambda: None, lambda: None, lambda: None, api=api)
        self.assertIsInstance(hotkeys, MediaHotkeys)

    @on_windows
    def test_a_failure_to_start_returns_none(self):
        hotkeys = start(lambda: None, lambda: None, lambda: None, api=FakeApi(hwnd=None))
        self.assertIsNone(hotkeys)

    @off_windows
    def test_off_windows_it_does_nothing(self):
        self.assertIsNone(start(lambda: None, lambda: None, lambda: None, api=FakeApi()))


if __name__ == "__main__":
    unittest.main()
