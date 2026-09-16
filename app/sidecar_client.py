"""HTTP client for the Sidecar's two endpoints (sidecar/server.py). Runs in
the Python host, not page-context JS -- unlike the old content script, there
is no Private Network Access restriction to work around here.
"""
import json
import urllib.request


class SidecarClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def synthesize(self, text: str, speaker: str) -> bytes:
        req = urllib.request.Request(
            f"{self.base_url}/synthesize",
            data=json.dumps({"text": text, "speaker": speaker}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.read()

    def speakers(self) -> list[str]:
        with urllib.request.urlopen(f"{self.base_url}/speakers", timeout=5) as res:
            return json.loads(res.read())["speakers"]
