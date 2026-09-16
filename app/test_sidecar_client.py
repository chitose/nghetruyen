# app/test_sidecar_client.py
import json
import unittest
from unittest.mock import patch, MagicMock

from sidecar_client import SidecarClient


def _fake_response(body: bytes):
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = body
    return cm


class TestSidecarClient(unittest.TestCase):
    @patch("sidecar_client.urllib.request.urlopen")
    def test_synthesize_posts_text_and_speaker_returns_wav_bytes(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response(b"RIFF....WAVEfmt ")
        client = SidecarClient("http://localhost:8934")
        result = client.synthesize("Xin chào.", "Minh Quân")
        self.assertEqual(result, b"RIFF....WAVEfmt ")
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "http://localhost:8934/synthesize")
        sent = json.loads(req.data.decode("utf-8"))
        self.assertEqual(sent, {"text": "Xin chào.", "speaker": "Minh Quân"})

    @patch("sidecar_client.urllib.request.urlopen")
    def test_speakers_returns_list(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response(json.dumps({"speakers": ["A", "B"]}).encode("utf-8"))
        client = SidecarClient("http://localhost:8934")
        self.assertEqual(client.speakers(), ["A", "B"])

    def test_base_url_trailing_slash_is_stripped(self):
        client = SidecarClient("http://localhost:8934/")
        self.assertEqual(client.base_url, "http://localhost:8934")


if __name__ == "__main__":
    unittest.main()
