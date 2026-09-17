import unittest
from unittest.mock import MagicMock

from api import Api


class TestApi(unittest.TestCase):
    """Api is only the js_api bridge for content.js; Controller does the work."""

    def setUp(self):
        self.controller = MagicMock()
        self.api = Api(self.controller)

    def test_get_init_data_delegates(self):
        self.controller.get_init_data.return_value = {"adapter": None}
        self.assertEqual(self.api.get_init_data("x.test"), {"adapter": None})
        self.controller.get_init_data.assert_called_once_with("x.test")

    def test_page_loaded_delegates(self):
        self.api.page_loaded("https://x.test/", "T", 2)
        self.controller.page_loaded.assert_called_once_with("https://x.test/", "T", 2)

    def test_chapter_ready_delegates_and_returns_the_result(self):
        self.controller.chapter_ready.return_value = {"autoStart": True}
        self.assertEqual(self.api.chapter_ready(["a"], "T"), {"autoStart": True})
        self.controller.chapter_ready.assert_called_once_with(["a"], "T")

    def test_play_pause_delegates(self):
        self.api.play_pause()
        self.controller.play_pause.assert_called_once_with()

    def test_skip_delegates(self):
        self.api.skip(-1)
        self.controller.skip.assert_called_once_with(-1)


if __name__ == "__main__":
    unittest.main()
