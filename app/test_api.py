import unittest
from unittest.mock import MagicMock

from api import Api
from config import DEFAULT_ADAPTERS


class TestApi(unittest.TestCase):
    def setUp(self):
        self.config = MagicMock()
        self.config.get.side_effect = lambda key, default=None: {
            "defaultRate": 1.0, "speaker": "Minh Quân", "autoNext": True,
        }.get(key, default)
        self.config.find_adapter.side_effect = lambda host: next(
            (a for a in DEFAULT_ADAPTERS if a["hostname"] == host), None
        )
        self.playback = MagicMock()
        self.sidecar = MagicMock()
        self.api = Api(self.config, self.playback, self.sidecar)

    def test_get_init_data_returns_matching_adapter_for_known_host(self):
        data = self.api.get_init_data("metruyenchu.co")
        self.assertEqual(data["adapter"]["hostname"], "metruyenchu.co")
        self.assertEqual(data["defaultRate"], 1.0)
        self.assertEqual(data["speaker"], "Minh Quân")
        self.assertTrue(data["autoNext"])
        self.assertIn("Minh Quân", data["knownSpeakers"])

    def test_get_init_data_returns_none_adapter_for_unknown_host(self):
        data = self.api.get_init_data("some-other-site.example")
        self.assertIsNone(data["adapter"])

    def test_chapter_ready_builds_chunks_and_loads_playback_engine(self):
        result = self.api.chapter_ready(["Câu một. Câu hai.", "Đoạn hai."], "My Chapter")
        self.playback.load_chapter.assert_called_once()
        args, kwargs = self.playback.load_chapter.call_args
        chunks = args[0]
        self.assertEqual(len(chunks), 3)
        self.assertIn("autoStart", result)
        self.assertFalse(result["autoStart"])

    def test_chapter_ready_auto_starts_playback_when_pending(self):
        self.api.set_pending_auto_start(True)
        result = self.api.chapter_ready(["Câu một."], "My Chapter")
        self.playback.play_current.assert_called_once()
        self.assertTrue(result["autoStart"])
        # the flag must be consumed, not sticky across chapters
        result2 = self.api.chapter_ready(["Câu hai."], "Another Chapter")
        self.assertFalse(result2["autoStart"])

    def test_start_playback_delegates_to_engine(self):
        self.api.start_playback()
        self.playback.play_current.assert_called_once()

    def test_set_rate_persists_and_updates_engine(self):
        self.api.set_rate(1.5)
        self.config.set.assert_called_with("defaultRate", 1.5)
        self.playback.set_rate.assert_called_with(1.5)

    def test_set_speaker_persists_and_updates_engine(self):
        self.api.set_speaker("Thái Sơn")
        self.config.set.assert_called_with("speaker", "Thái Sơn")
        self.playback.set_speaker.assert_called_with("Thái Sơn")

    def test_get_speakers_ok(self):
        self.sidecar.speakers.return_value = ["A", "B"]
        self.assertEqual(self.api.get_speakers(), {"ok": True, "speakers": ["A", "B"]})

    def test_get_speakers_handles_sidecar_down(self):
        self.sidecar.speakers.side_effect = RuntimeError("refused")
        self.assertEqual(self.api.get_speakers(), {"ok": False})

    def test_get_adapters_returns_config_adapters(self):
        self.config.get.side_effect = lambda key, default=None: (
            DEFAULT_ADAPTERS if key == "adapters" else {
                "defaultRate": 1.0, "speaker": "Minh Quân", "autoNext": True,
            }.get(key, default)
        )
        self.assertEqual(self.api.get_adapters(), DEFAULT_ADAPTERS)

    def test_save_adapters_persists_to_config(self):
        new_adapters = [{"hostname": "example.com", "contentSelector": "main", "stripSelectors": [], "nextMode": "generic", "nextValue": ""}]
        self.api.save_adapters(new_adapters)
        self.config.set.assert_called_with("adapters", new_adapters)

    def test_get_settings_returns_sidecar_url_speaker_rate(self):
        self.config.get.side_effect = lambda key, default=None: {
            "sidecarUrl": "http://localhost:8934", "speaker": "Minh Quân", "defaultRate": 1.0,
        }.get(key, default)
        settings = self.api.get_settings()
        self.assertEqual(settings["sidecarUrl"], "http://localhost:8934")

    def test_save_settings_persists_each_field(self):
        self.api.save_settings({"sidecarUrl": "http://localhost:9999", "speaker": "Adam", "defaultRate": 1.2})
        self.config.set.assert_any_call("sidecarUrl", "http://localhost:9999")
        self.config.set.assert_any_call("speaker", "Adam")
        self.config.set.assert_any_call("defaultRate", 1.2)


if __name__ == "__main__":
    unittest.main()
