"""Persistent settings (adapters, voice, speed, Sidecar URL) as one JSON file
at %APPDATA%\\reading-web\\config.json -- the folder predates the App's name
and is kept so existing settings survive the rename. Replaces
extension/defaults.js and
chrome.storage.sync. See docs/adr/0009-standalone-app-replaces-extension.md.
"""
import json
from pathlib import Path

DEFAULT_SIDECAR_URL = "http://localhost:8934"
DEFAULT_SPEAKER = "Minh Quân"
DEFAULT_RATE = 1.0
DEFAULT_AUTO_NEXT = True
DEFAULT_BACKEND_MODEL = "default"  # or "v3nano" -- see sidecar/server.py
# Where the Web View opens on launch; the reader's address bar goes anywhere
# from there. Editable in Options.
DEFAULT_START_URL = "https://metruyenchu.co"
# Reopen the Page the reader was last on (see session.py) instead of Start URL.
DEFAULT_RESTORE_LAST_PAGE = True
# The control window's audio visualizer has a few drawing styles; the chrome's
# carousel arrows cycle through them, and this is the one a fresh install uses.
# The names must match the switch in ui.VISUALIZER_JS.
VISUALIZER_STYLES = ("bars", "mirrored", "wave", "blocks")
DEFAULT_VISUALIZER_STYLE = VISUALIZER_STYLES[0]
# Read a Paragraph shorter than this together with the ones after it, so a
# one-line piece of dialogue does not become its own reading stop. Off by
# default; see chunker.join_short_paragraphs.
DEFAULT_JOIN_SHORT_PARAGRAPHS = False
DEFAULT_SHORT_PARAGRAPH_WORDS = 8

# VieNeu-TTS's built-in preset voices (ADR-0008). Static fallback shown
# before the Sidecar's own /speakers responds.
KNOWN_SPEAKERS = [
    "Minh Đức", "Phạm Tuyên", "Thái Sơn", "Xuân Vĩnh", "Thanh Bình", "Trúc Ly",
    "Ngọc Linh", "Đoan Trang", "Mai Anh", "Thục Đoan", "Minh Triết", "Thùy Dung",
    "Quang Sơn", "Ngọc Trân", "Mỹ Duyên", "Quỳnh Anh", "Đức Trí", "Kim Thanh",
    "Ngọc Huyền", "Adam", "Mạnh Dũng", "Minh Quân", "Anh Khôi",
]

DEFAULT_ADAPTERS = [
    {
        "hostname": "metruyenchu.co",
        "contentSelector": "main article",
        "stripSelectors": [],
        "nextMode": "text",
        "nextValue": "Chương sau",
    },
    {
        "hostname": "khotruyenchu.fun",
        "contentSelector": ".entry-content",
        "stripSelectors": [
            ".story-navigation", ".reading-tools-bar", ".code-block", "script",
            'a[href*="discovernative.com"]', 'strong[style*="height:0"]', 'i[style*="opacity:0"]',
        ],
        "nextMode": "css",
        "nextValue": ".story-navigation .nav-next a",
    },
    {
        "hostname": "dichtienghoa.net",
        "contentSelector": ".chapter-content .chapter-body",
        "stripSelectors": [],
        "nextMode": "increment-url",
        "nextValue": "",
    },
]


def merge_default_adapters(stored: list) -> list:
    existing_hosts = {a["hostname"] for a in stored}
    missing = [a for a in DEFAULT_ADAPTERS if a["hostname"] not in existing_hosts]
    return stored + missing if missing else stored


class Config:
    def __init__(self, path: Path):
        self.path = path
        self._data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            data = {}
        data.setdefault("sidecarUrl", DEFAULT_SIDECAR_URL)
        data.setdefault("speaker", DEFAULT_SPEAKER)
        data.setdefault("defaultRate", DEFAULT_RATE)
        data.setdefault("autoNext", DEFAULT_AUTO_NEXT)
        data.setdefault("backendModel", DEFAULT_BACKEND_MODEL)
        data.setdefault("startUrl", DEFAULT_START_URL)
        data.setdefault("restoreLastPage", DEFAULT_RESTORE_LAST_PAGE)
        data.setdefault("visualizerStyle", DEFAULT_VISUALIZER_STYLE)
        data.setdefault("joinShortParagraphs", DEFAULT_JOIN_SHORT_PARAGRAPHS)
        data.setdefault("shortParagraphWords", DEFAULT_SHORT_PARAGRAPH_WORDS)
        stored_adapters = data.get("adapters")
        data["adapters"] = merge_default_adapters(stored_adapters) if stored_adapters else list(DEFAULT_ADAPTERS)
        return data

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value) -> None:
        self._data[key] = value
        self.save()

    def find_adapter(self, hostname: str):
        return next((a for a in self._data["adapters"] if a["hostname"] == hostname), None)
