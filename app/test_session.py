import json
import unittest
from pathlib import Path

from session import (
    DEFAULTS,
    Session,
    restore_bounds,
    restore_dock_height,
    restore_hidden,
)
from tempdirs import ephemeral_dir


class TestSession(unittest.TestCase):
    def setUp(self):
        self.tmpdir = ephemeral_dir()
        self.path = Path(self.tmpdir.name) / "session.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_file_gives_defaults(self):
        session = Session(self.path)
        for key, value in DEFAULTS.items():
            self.assertEqual(session.get(key), value)

    def test_corrupt_file_gives_defaults(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(Session(self.path).get("lastUrl"), "")

    def test_non_dict_json_gives_defaults(self):
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertIsNone(Session(self.path).get("dockHeight"))

    def test_unknown_keys_are_ignored_when_saved(self):
        self.path.write_text(json.dumps({"lastUrl": "x", "junk": 1}), encoding="utf-8")
        session = Session(self.path)
        self.assertEqual(session.get("lastUrl"), "x")
        session.save()
        self.assertNotIn("junk", json.loads(self.path.read_text(encoding="utf-8")))

    def test_update_and_save_round_trip(self):
        session = Session(self.path)
        session.update(
            lastUrl="https://x.test/c1", readerBounds=[1, 2, 800, 600],
            dockHeight=200, readerHidden=True,
        )
        session.save()
        reloaded = Session(self.path)
        self.assertEqual(reloaded.get("lastUrl"), "https://x.test/c1")
        self.assertEqual(reloaded.get("readerBounds"), [1, 2, 800, 600])
        self.assertEqual(reloaded.get("dockHeight"), 200)
        self.assertTrue(reloaded.get("readerHidden"))

    def test_save_creates_the_parent_directory(self):
        nested = Path(self.tmpdir.name) / "nested" / "session.json"
        session = Session(nested)
        session.update(lastUrl="x")
        session.save()
        self.assertTrue(nested.exists())


class TestRestoreBounds(unittest.TestCase):
    SCREENS = [(0, 0, 1920, 1080), (1920, 0, 1920, 1080)]

    def test_keeps_bounds_that_are_still_on_a_screen(self):
        self.assertEqual(restore_bounds([100, 50, 1200, 760], self.SCREENS), (100, 50, 1200, 760))

    def test_keeps_bounds_on_a_secondary_screen(self):
        self.assertEqual(restore_bounds([2000, 100, 1200, 760], self.SCREENS), (2000, 100, 1200, 760))

    def test_drops_bounds_that_are_off_every_screen(self):
        self.assertIsNone(restore_bounds([5000, 5000, 1200, 760], self.SCREENS))

    def test_drops_bounds_that_are_too_small(self):
        self.assertIsNone(restore_bounds([100, 50, 200, 100], self.SCREENS))

    def test_drops_missing_or_malformed_bounds(self):
        for stored in (None, [], [1, 2, 3], "nope", ["a", "b", "c", "d"]):
            self.assertIsNone(restore_bounds(stored, self.SCREENS))

    def test_no_screens_means_no_restore(self):
        self.assertIsNone(restore_bounds([100, 50, 1200, 760], []))

    def test_respects_custom_minimums(self):
        self.assertEqual(
            restore_bounds([100, 50, 200, 100], self.SCREENS, min_width=200, min_height=100),
            (100, 50, 200, 100),
        )


class TestRestoreDockHeight(unittest.TestCase):
    def test_uses_the_stored_number(self):
        self.assertEqual(restore_dock_height(240, 176), 240)

    def test_falls_back_for_missing_or_bad_values(self):
        for stored in (None, "tall", True):
            self.assertEqual(restore_dock_height(stored, 176), 176)


class TestRestoreHidden(unittest.TestCase):
    def test_a_reader_hidden_at_close_comes_back_hidden(self):
        self.assertTrue(restore_hidden(True))

    def test_anything_else_comes_back_on_screen(self):
        # A session.json from before this was stored, or one somebody edited,
        # must not launch the App with the reader tucked away behind the strip.
        for stored in (False, None, "yes", 1, {}, []):
            self.assertFalse(restore_hidden(stored))


if __name__ == "__main__":
    unittest.main()
