import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from config import Config, DEFAULT_ADAPTERS, DEFAULT_SIDECAR_URL, DEFAULT_SPEAKER


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "config.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_file_seeds_defaults(self):
        cfg = Config(self.path)
        self.assertEqual(cfg.get("sidecarUrl"), DEFAULT_SIDECAR_URL)
        self.assertEqual(cfg.get("speaker"), DEFAULT_SPEAKER)
        self.assertEqual(len(cfg.get("adapters")), len(DEFAULT_ADAPTERS))

    def test_set_persists_to_disk(self):
        cfg = Config(self.path)
        cfg.set("speaker", "Thái Sơn")
        reloaded = Config(self.path)
        self.assertEqual(reloaded.get("speaker"), "Thái Sơn")

    def test_new_default_adapter_is_merged_into_existing_stored_list(self):
        # Simulates upgrading from an install that only ever saved the old
        # two-adapter default set -- new built-ins must still show up.
        self.path.write_text(
            json.dumps({"adapters": [DEFAULT_ADAPTERS[0]]}), encoding="utf-8"
        )
        cfg = Config(self.path)
        hosts = {a["hostname"] for a in cfg.get("adapters")}
        self.assertEqual(hosts, {a["hostname"] for a in DEFAULT_ADAPTERS})

    def test_users_own_added_adapter_is_preserved(self):
        custom = {"hostname": "example.com", "contentSelector": "main", "stripSelectors": [], "nextMode": "generic", "nextValue": ""}
        self.path.write_text(json.dumps({"adapters": DEFAULT_ADAPTERS + [custom]}), encoding="utf-8")
        cfg = Config(self.path)
        hosts = {a["hostname"] for a in cfg.get("adapters")}
        self.assertIn("example.com", hosts)

    def test_find_adapter_matches_by_hostname(self):
        cfg = Config(self.path)
        adapter = cfg.find_adapter("metruyenchu.co")
        self.assertIsNotNone(adapter)
        self.assertEqual(adapter["hostname"], "metruyenchu.co")

    def test_find_adapter_returns_none_for_unknown_host(self):
        cfg = Config(self.path)
        self.assertIsNone(cfg.find_adapter("unknown-site.example"))


if __name__ == "__main__":
    unittest.main()
