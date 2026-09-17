import unittest
from pathlib import Path

from tempdirs import ephemeral_dir
from version import VERSION_FILENAME, app_version


class TestAppVersion(unittest.TestCase):
    def setUp(self):
        self.tmp = ephemeral_dir()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_reads_the_bundled_version_file(self):
        (self.root / VERSION_FILENAME).write_text("v0.2.0\n", encoding="utf-8")
        self.assertEqual(app_version(self.root), "v0.2.0")

    def test_a_missing_file_falls_back_to_dev(self):
        self.assertEqual(app_version(self.root), "dev")

    def test_an_empty_file_falls_back_to_dev(self):
        (self.root / VERSION_FILENAME).write_text("", encoding="utf-8")
        self.assertEqual(app_version(self.root), "dev")


if __name__ == "__main__":
    unittest.main()
