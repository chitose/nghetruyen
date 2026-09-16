# Standalone Reader App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Chrome extension with a standalone Windows app (`app/`) that spawns the existing Sidecar, embeds a Web View, and owns all playback state directly in Python.

**Architecture:** `pywebview` (WebView2) hosts a single main window plus a second Options window. Injected JS (adapted from `extension/content.js`) does DOM-only work: extraction, Player Bar rendering, and re-querying the next-chapter link at Python's command. Everything else -- chunking, the prefetch cache, audio playback, playback state, config -- lives in the Python host and is reached from JS through `pywebview`'s `js_api` bridge (JS sends intents, Python pushes state back via `evaluate_js`).

**Tech Stack:** Python 3.11+, `pywebview`, `sounddevice` + `soundfile` for audio, stdlib `unittest` for tests (no test framework, matching the repo's existing convention in `extension/test_chunker.js`).

**Spec:** This plan implements the design settled in [docs/adr/0009-standalone-app-replaces-extension.md](../../adr/0009-standalone-app-replaces-extension.md) and the updated [CONTEXT.md](../../../CONTEXT.md). Executors should read both before starting.

## Global Constraints

- Windows-only, single user, no installer -- runs via a portable `.bat`, same pattern as `sidecar/server.bat`.
- `app/venv` is a separate virtualenv from `sidecar/venv` -- never import Sidecar deps (`vieneu`, etc.) from the app, or vice versa.
- No new native-binary dependency -- pure-pip wheels only (this is why `sounddevice`, not `python-vlc`; see ADR-0009).
- No system tray icon, no OS media-key / lock-screen integration (SMTC) -- rejected in ADR-0009.
- No test framework -- plain `unittest`/`assert`, matching `extension/test_chunker.js` and `extension/test_background.js`'s existing "no framework" convention.
- `extension/` is not touched or deleted by this plan -- it stays until the new app is proven in real use (ADR-0009).
- No importer for old `chrome.storage` adapters/settings -- the app starts from the same `DEFAULT_ADAPTERS` a fresh extension install would.

---

## Task 1: Sidecar Lifecycle Manager

**Files:**
- Create: `app/requirements.txt`
- Create: `app/sidecar_manager.py`
- Test: `app/test_sidecar_manager.py`

**Interfaces:**
- Produces: `SidecarManager(python_exe: str, cwd: str, port: int = 8934)` with methods `start() -> None`, `wait_healthy(timeout: float = 60.0, interval: float = 0.5) -> bool`, `stop() -> None`, and property `is_running: bool`. Later tasks (`main.py`) construct one instance and call `start()`/`wait_healthy()`/`stop()`.

- [ ] **Step 1: Write the failing test**

```python
# app/test_sidecar_manager.py
import unittest
from unittest.mock import patch, MagicMock
import urllib.error

from sidecar_manager import SidecarManager


class TestSidecarManager(unittest.TestCase):
    @patch("sidecar_manager.subprocess.Popen")
    def test_start_spawns_uvicorn_with_expected_args(self, mock_popen):
        mgr = SidecarManager(python_exe=r"C:\venv\Scripts\python.exe", cwd=r"C:\sidecar", port=8934)
        mgr.start()
        mock_popen.assert_called_once_with(
            [r"C:\venv\Scripts\python.exe", "-m", "uvicorn", "server:app", "--port", "8934"],
            cwd=r"C:\sidecar",
        )

    @patch("sidecar_manager.subprocess.Popen")
    def test_start_is_idempotent(self, mock_popen):
        mgr = SidecarManager(python_exe="python", cwd=".", port=8934)
        mgr.start()
        mgr.start()
        self.assertEqual(mock_popen.call_count, 1)

    @patch("sidecar_manager.urllib.request.urlopen")
    @patch("sidecar_manager.subprocess.Popen")
    def test_wait_healthy_returns_true_once_reachable(self, mock_popen, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value = MagicMock()
        mgr = SidecarManager(python_exe="python", cwd=".", port=8934)
        mgr.start()
        self.assertTrue(mgr.wait_healthy(timeout=1.0, interval=0.01))

    @patch("sidecar_manager.time.monotonic")
    @patch("sidecar_manager.urllib.request.urlopen", side_effect=urllib.error.URLError("refused"))
    @patch("sidecar_manager.subprocess.Popen")
    def test_wait_healthy_times_out_if_never_reachable(self, mock_popen, mock_urlopen, mock_monotonic):
        # Two calls per loop iteration (deadline check + nothing else); advance
        # past the timeout on the second read so the loop exits after one try.
        mock_monotonic.side_effect = [0.0, 0.0, 10.0]
        mgr = SidecarManager(python_exe="python", cwd=".", port=8934)
        mgr.start()
        self.assertFalse(mgr.wait_healthy(timeout=1.0, interval=0.0))

    @patch("sidecar_manager.subprocess.Popen")
    def test_stop_terminates_and_clears_process(self, mock_popen):
        fake_proc = MagicMock()
        fake_proc.wait.return_value = 0
        mock_popen.return_value = fake_proc
        mgr = SidecarManager(python_exe="python", cwd=".", port=8934)
        mgr.start()
        mgr.stop()
        fake_proc.terminate.assert_called_once()
        self.assertFalse(mgr.is_running)

    @patch("sidecar_manager.subprocess.Popen")
    def test_stop_before_start_is_a_noop(self, mock_popen):
        mgr = SidecarManager(python_exe="python", cwd=".", port=8934)
        mgr.stop()  # must not raise
        mock_popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m unittest test_sidecar_manager -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sidecar_manager'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/requirements.txt
pywebview
sounddevice
soundfile
```

```python
# app/sidecar_manager.py
"""Spawns and supervises the Sidecar (sidecar/server.py) as a child process.

See docs/adr/0009-standalone-app-replaces-extension.md: the App starts the
Sidecar automatically instead of the reader running it manually in a
terminal (ADR-0001's "started manually" cost moves up one level).
"""
import subprocess
import time
import urllib.error
import urllib.request


class SidecarManager:
    def __init__(self, python_exe: str, cwd: str, port: int = 8934):
        self.python_exe = python_exe
        self.cwd = cwd
        self.port = port
        self._proc = None

    def start(self) -> None:
        if self._proc is not None:
            return
        self._proc = subprocess.Popen(
            [self.python_exe, "-m", "uvicorn", "server:app", "--port", str(self.port)],
            cwd=self.cwd,
        )

    def wait_healthy(self, timeout: float = 60.0, interval: float = 0.5) -> bool:
        deadline = time.monotonic() + timeout
        url = f"http://localhost:{self.port}/speakers"
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2):
                    return True
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(interval)
        return False

    def stop(self) -> None:
        if self._proc is None:
            return
        self._proc.terminate()
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        self._proc = None

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m unittest test_sidecar_manager -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add app/requirements.txt app/sidecar_manager.py app/test_sidecar_manager.py
git commit -m "feat: add Sidecar lifecycle manager for standalone app"
```

---

## Task 2: Config Store

**Files:**
- Create: `app/config.py`
- Test: `app/test_config.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `Config(path: pathlib.Path)` with `.get(key, default=None)`, `.set(key, value) -> None` (persists immediately), `.find_adapter(hostname: str) -> dict | None`. Module-level `DEFAULT_SIDECAR_URL`, `DEFAULT_SPEAKER`, `DEFAULT_RATE`, `DEFAULT_AUTO_NEXT`, `KNOWN_SPEAKERS`, `DEFAULT_ADAPTERS` -- ported 1:1 from `extension/defaults.js`. Task 8 (`api.py`) constructs `Config` and calls these methods.

- [ ] **Step 1: Write the failing test**

```python
# app/test_config.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m unittest test_config -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/config.py
"""Persistent settings (adapters, voice, speed, Sidecar URL) as one JSON file
at %APPDATA%\\reading-web\\config.json -- replaces extension/defaults.js and
chrome.storage.sync. See docs/adr/0009-standalone-app-replaces-extension.md.
"""
import json
from pathlib import Path

DEFAULT_SIDECAR_URL = "http://localhost:8934"
DEFAULT_SPEAKER = "Minh Quân"
DEFAULT_RATE = 1.0
DEFAULT_AUTO_NEXT = True

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m unittest test_config -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/test_config.py
git commit -m "feat: add JSON config store for the standalone app"
```

---

## Task 3: Chunker Port

**Files:**
- Create: `app/chunker.py`
- Test: `app/test_chunker.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `split_into_chunks(text: str, max_len: int = 400) -> list[str]`, `build_paragraph_chunks(paragraphs: list[str], max_len: int = 400) -> list[dict]` where each dict is `{"text": str, "paragraphIndex": int}`. Task 8 (`api.py`) calls `build_paragraph_chunks` when a chapter's paragraphs arrive from JS.

- [ ] **Step 1: Write the failing test**

Port `extension/test_chunker.js`'s cases 1:1 -- this is the one piece of non-trivial parsing logic moving languages (see the Q22 discussion in the design session), so its known edge cases must carry over exactly.

```python
# app/test_chunker.py
import unittest
from chunker import split_into_chunks, build_paragraph_chunks


class TestSplitIntoChunks(unittest.TestCase):
    def test_basic_sentence_split(self):
        self.assertEqual(
            split_into_chunks("Xin chào. Tôi khỏe. Cảm ơn!"),
            ["Xin chào.", "Tôi khỏe.", "Cảm ơn!"],
        )

    def test_no_terminal_punctuation_is_one_chunk(self):
        self.assertEqual(split_into_chunks("không có dấu chấm"), ["không có dấu chấm"])

    def test_vietnamese_ellipsis_and_quote_handling(self):
        self.assertEqual(
            split_into_chunks('Anh nói "đi thôi…" rồi bước ra.'),
            ['Anh nói "đi thôi…" rồi bước ra.'],
        )

    def test_empty_or_whitespace_only_input(self):
        self.assertEqual(split_into_chunks("   "), [])

    def test_long_run_on_sentence_splits_on_word_boundaries(self):
        long_text = "từ " * 200 + "."
        chunks = split_into_chunks(long_text, 50)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c), 50)
        import re
        rejoined = re.sub(r"\s+", " ", " ".join(chunks))
        expected = re.sub(r"\s+", " ", long_text.strip())
        self.assertEqual(rejoined, expected)

    def test_single_word_longer_than_max_len_still_emitted(self):
        no_spaces = "a" * 500 + "."
        chunks = split_into_chunks(no_spaces, 100)
        self.assertGreaterEqual(len(chunks), 5)


class TestBuildParagraphChunks(unittest.TestCase):
    def test_sentences_tagged_with_source_paragraph_and_never_merged_across_boundary(self):
        chunks = build_paragraph_chunks([
            "Câu một. Câu hai.",
            "Đoạn hai chỉ có một câu.",
            "",
            "Đoạn ba.",
        ])
        self.assertEqual(
            [(c["text"], c["paragraphIndex"]) for c in chunks],
            [
                ("Câu một.", 0),
                ("Câu hai.", 0),
                ("Đoạn hai chỉ có một câu.", 1),
                ("Đoạn ba.", 2),
            ],
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m unittest test_chunker -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'chunker'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/chunker.py
"""Sentence splitter -- ported from extension/chunker.js. See
docs/adr/0009-standalone-app-replaces-extension.md: chunking moves entirely
into the Python host, so the injected JS no longer needs this at all.

ponytail: naive -- doesn't handle real abbreviations ("T.S.", "1.5") or
nested quotes. Boundary rule: punctuation only ends a sentence if followed
by end-of-string or whitespace + an uppercase letter -- otherwise it's an
ellipsis/abbreviation mid-sentence (common in dialogue). Upgrade to a real
tokenizer if mis-splits turn out to be frequent.
"""
import re

_ENDERS = re.compile(r"[.!?…]+[\"'”)]*")
_NEXT_STARTS_SENTENCE = re.compile(r"^\s+[\"'“(]?[A-ZÀ-Ỵ]", re.UNICODE)


def split_into_chunks(text: str, max_len: int = 400) -> list[str]:
    boundaries = []
    for m in _ENDERS.finditer(text):
        end = m.end()
        rest = text[end:]
        if rest == "" or _NEXT_STARTS_SENTENCE.match(rest):
            boundaries.append(end)

    sentences = []
    start = 0
    for b in boundaries:
        sentences.append(text[start:b])
        start = b
    if start < len(text):
        sentences.append(text[start:])

    chunks = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        while len(s) > max_len:
            cut = s.rfind(" ", 0, max_len)
            if cut <= 0:
                cut = max_len
            chunks.append(s[:cut].strip())
            s = s[cut:].strip()
        if s:
            chunks.append(s)
    return chunks


def build_paragraph_chunks(paragraphs: list[str], max_len: int = 400) -> list[dict]:
    chunks = []
    for paragraph_index, paragraph in enumerate(paragraphs):
        for text in split_into_chunks(paragraph, max_len):
            chunks.append({"text": text, "paragraphIndex": paragraph_index})
    return chunks
```

Note: the uppercase-letter check uses `[A-ZÀ-Ỵ]` instead of JS's Unicode `\p{Lu}` -- Python's `re` module has no Unicode property escapes without the third-party `regex` package. `À-Ỵ` covers the Vietnamese uppercase accented range used in the test corpus; this is a real, narrower behavior than the JS original and is exactly the kind of thing the ported test suite (Step 1) exists to catch if it's wrong.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m unittest test_chunker -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add app/chunker.py app/test_chunker.py
git commit -m "feat: port sentence chunker from extension/chunker.js to Python"
```

---

## Task 4: Sidecar HTTP Client

**Files:**
- Create: `app/sidecar_client.py`
- Test: `app/test_sidecar_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `SidecarClient(base_url: str)` with `.synthesize(text: str, speaker: str) -> bytes` (raw WAV bytes) and `.speakers() -> list[str]`. Task 6 (`playback.py`) calls `.synthesize()`; Task 8 (`api.py`) calls `.speakers()`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m unittest test_sidecar_client -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sidecar_client'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/sidecar_client.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m unittest test_sidecar_client -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit**

```bash
git add app/sidecar_client.py app/test_sidecar_client.py
git commit -m "feat: add Sidecar HTTP client for the standalone app"
```

---

## Task 5: Audio Player

**Files:**
- Create: `app/audio_player.py`
- Test: `app/test_audio_player.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (mocks `sounddevice`/`soundfile` directly).
- Produces: `AudioPlayer(on_finished: Callable[[], None])` with `.load(wav_bytes: bytes) -> None`, `.play(rate: float = 1.0, start_frame: int = 0) -> None`, `.pause() -> None`, `.resume() -> None`, `.set_rate(rate: float) -> None`, `.stop() -> None`. Task 6 (`playback.py`) owns one `AudioPlayer` instance.

- [ ] **Step 1: Write the failing test**

```python
# app/test_audio_player.py
import unittest
from unittest.mock import patch, MagicMock
import numpy as np

from audio_player import AudioPlayer


def _sine_wav_bytes(seconds=1.0, sr=16000):
    import io
    import soundfile as sf
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    data = (0.1 * np.sin(2 * np.pi * 440 * t)).astype("float32")
    buf = io.BytesIO()
    sf.write(buf, data, sr, format="WAV")
    return buf.getvalue()


class TestAudioPlayer(unittest.TestCase):
    @patch("audio_player.sd")
    def test_play_starts_sounddevice_at_rate_adjusted_samplerate(self, mock_sd):
        player = AudioPlayer(on_finished=lambda: None)
        player.load(_sine_wav_bytes(seconds=0.1, sr=16000))
        player.play(rate=1.5)
        mock_sd.stop.assert_called()
        args, kwargs = mock_sd.play.call_args
        self.assertEqual(kwargs["samplerate"], 16000 * 1.5)

    @patch("audio_player.sd")
    def test_set_rate_restarts_playback_from_elapsed_position(self, mock_sd):
        player = AudioPlayer(on_finished=lambda: None)
        player.load(_sine_wav_bytes(seconds=1.0, sr=16000))
        with patch("audio_player.time.monotonic", side_effect=[0.0, 0.5, 0.5]):
            player.play(rate=1.0)
            player.set_rate(2.0)
        # second play() call should start partway through the buffer, not at 0
        last_call_args = mock_sd.play.call_args
        played_array = last_call_args[0][0]
        self.assertLess(len(played_array), 16000)  # started after frame 0

    @patch("audio_player.sd")
    def test_pause_then_resume_continues_from_paused_position(self, mock_sd):
        player = AudioPlayer(on_finished=lambda: None)
        player.load(_sine_wav_bytes(seconds=1.0, sr=16000))
        with patch("audio_player.time.monotonic", side_effect=[0.0, 0.3, 0.3]):
            player.play(rate=1.0)
            player.pause()
            mock_sd.stop.assert_called()
            player.resume()
        played_array = mock_sd.play.call_args[0][0]
        self.assertLess(len(played_array), 16000)

    @patch("audio_player.sd")
    def test_stop_calls_sounddevice_stop(self, mock_sd):
        player = AudioPlayer(on_finished=lambda: None)
        player.load(_sine_wav_bytes(seconds=0.1, sr=16000))
        player.play(rate=1.0)
        player.stop()
        self.assertGreaterEqual(mock_sd.stop.call_count, 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m unittest test_audio_player -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'audio_player'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/audio_player.py
"""Plays synthesized WAV audio via sounddevice. Replaces offscreen.js's
<audio> element (ADR-0002) -- this class lives in the Python host, which
survives page navigation on its own, so there is no offscreen-document
equivalent to build (see docs/adr/0009-standalone-app-replaces-extension.md).

Rate changes are done by playing at samplerate * rate -- sounddevice's own
resampling-via-samplerate trick -- not a real time-stretch. This keeps rate
changes instant (ADR-0003), but pitch shifts with speed since nothing free
does pitch-preserving time-stretch outside a browser. Accepted trade-off,
see ADR-0009.

ponytail: finish detection is a background thread blocked on sd.wait(),
which also returns early when sd.stop() interrupts it -- the `_generation`
counter distinguishes "this play() call's audio actually finished" from
"someone called play()/pause()/stop() again before it did." Good enough for
one active playback at a time; would need real per-stream tracking if this
ever had to run two AudioPlayers concurrently.
"""
import io
import threading
import time

import sounddevice as sd
import soundfile as sf


class AudioPlayer:
    def __init__(self, on_finished):
        self.on_finished = on_finished
        self._data = None
        self._orig_sr = 0
        self._rate = 1.0
        self._offset_frames = 0
        self._start_time = None
        self._paused = False
        self._generation = 0

    def load(self, wav_bytes: bytes) -> None:
        data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
        self._data = data
        self._orig_sr = sr

    def play(self, rate: float = 1.0, start_frame: int = 0) -> None:
        sd.stop()
        self._rate = rate
        self._offset_frames = start_frame
        self._paused = False
        self._start_time = time.monotonic()
        self._generation += 1
        gen = self._generation
        remaining = self._data[start_frame:]
        sd.play(remaining, samplerate=self._orig_sr * rate)
        threading.Thread(target=self._watch_finish, args=(gen,), daemon=True).start()

    def _watch_finish(self, gen: int) -> None:
        sd.wait()
        if gen == self._generation and not self._paused:
            self.on_finished()

    def _played_frames(self) -> int:
        elapsed = time.monotonic() - self._start_time
        return int(elapsed * self._orig_sr * self._rate)

    def set_rate(self, rate: float) -> None:
        new_start = self._offset_frames + self._played_frames()
        self.play(rate=rate, start_frame=new_start)

    def pause(self) -> None:
        pause_offset = self._offset_frames + self._played_frames()
        sd.stop()
        self._paused = True
        self._offset_frames = pause_offset

    def resume(self) -> None:
        self.play(rate=self._rate, start_frame=self._offset_frames)

    def stop(self) -> None:
        sd.stop()
        self._paused = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m unittest test_audio_player -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add app/audio_player.py app/test_audio_player.py
git commit -m "feat: add sounddevice-based audio player for the standalone app"
```

---

## Task 6: Playback Engine

**Files:**
- Create: `app/playback.py`
- Test: `app/test_playback.py`

**Interfaces:**
- Consumes: `SidecarClient.synthesize(text, speaker) -> bytes` (Task 4), `AudioPlayer` with `.load()`/`.play()`/`.pause()`/`.resume()`/`.set_rate()` and constructor `on_finished` callback (Task 5).
- Produces: `PlaybackEngine(sidecar_client, audio_player, notify)` where `notify: Callable[[dict], None]` is called with event dicts shaped like the old `offscreen.js` messages: `{"type": "CHUNK_INDEX", "paragraphIndex": int, "totalParagraphs": int, "paragraphText": str}`, `{"type": "PLAYBACK_STATE", "state": "buffering"|"playing"|"paused"}`, `{"type": "ERROR", "message": str}`, `{"type": "CHAPTER_DONE"}`. Methods: `.load_chapter(chunks, paragraphs, chapter_session_id, speaker, rate) -> None`, `.play_current() -> None`, `.toggle_play() -> None`, `.set_rate(rate) -> None`, `.set_speaker(speaker) -> None`, `.skip(direction: int) -> None`. Task 8 (`api.py`) owns one instance and wires `notify` to `evaluate_js` calls.

- [ ] **Step 1: Write the failing test**

```python
# app/test_playback.py
import time
import unittest
from unittest.mock import MagicMock

from playback import PlaybackEngine

CHUNKS = [
    {"text": "Câu một.", "paragraphIndex": 0},
    {"text": "Câu hai.", "paragraphIndex": 0},
    {"text": "Đoạn hai.", "paragraphIndex": 1},
]
PARAGRAPHS = ["Câu một. Câu hai.", "Đoạn hai."]


class TestPlaybackEngine(unittest.TestCase):
    def setUp(self):
        self.sidecar = MagicMock()
        self.sidecar.synthesize.return_value = b"WAVDATA"
        self.audio = MagicMock()
        self.events = []
        self.engine = PlaybackEngine(self.sidecar, self.audio, notify=self.events.append)
        self.engine.load_chapter(CHUNKS, PARAGRAPHS, "session-1", speaker="Minh Quân", rate=1.0)

    def test_load_chapter_prefetches_all_chunks_when_fewer_than_prefetch_ahead(self):
        # PREFETCH_AHEAD is 6; only 3 chunks exist, all should be requested.
        time.sleep(0.05)  # background executor threads
        self.assertEqual(self.sidecar.synthesize.call_count, 3)

    def test_play_current_loads_audio_and_notifies_chunk_index_then_playing(self):
        self.engine.play_current()
        self.audio.load.assert_called_with(b"WAVDATA")
        self.audio.play.assert_called_with(rate=1.0)
        types = [e["type"] for e in self.events]
        self.assertEqual(types, ["CHUNK_INDEX", "PLAYBACK_STATE", "PLAYBACK_STATE"])
        self.assertEqual(self.events[0]["paragraphText"], "Câu một. Câu hai.")
        self.assertEqual(self.events[-1]["state"], "playing")

    def test_chapter_done_notified_once_past_last_chunk(self):
        self.engine._index = len(CHUNKS)
        self.engine.play_current()
        self.assertEqual(self.events[-1], {"type": "CHAPTER_DONE"})

    def test_skip_jumps_to_first_chunk_of_adjacent_paragraph(self):
        self.engine._index = 0
        self.engine.skip(1)
        self.assertEqual(self.engine._index, 2)  # first chunk of paragraph 1

    def test_skip_past_start_or_end_is_a_noop(self):
        self.engine._index = 0
        self.engine.skip(-1)
        self.assertEqual(self.engine._index, 0)

    def test_sidecar_error_notifies_error_and_paused(self):
        self.sidecar.synthesize.side_effect = RuntimeError("connection refused")
        engine = PlaybackEngine(self.sidecar, self.audio, notify=self.events.append)
        engine.load_chapter(CHUNKS, PARAGRAPHS, "session-2", speaker="x", rate=1.0)
        time.sleep(0.05)
        self.events.clear()
        engine.play_current()
        types = [e["type"] for e in self.events]
        self.assertIn("ERROR", types)
        self.assertIn("Sidecar unreachable", self.events[[e["type"] for e in self.events].index("ERROR")]["message"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m unittest test_playback -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'playback'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/playback.py
"""Owns chapter playback: the prefetch cache, current index, and playback
state -- ported from extension/offscreen.js, minus the multi-tab guard
(activeSessionId vs chapterSessionId) that only made sense when many Chrome
tabs could share one offscreen document. A single-window app has no "other
tabs" to guard against (docs/adr/0009-standalone-app-replaces-extension.md).
"""
import threading
from concurrent.futures import ThreadPoolExecutor

PREFETCH_AHEAD = 6


class PlaybackEngine:
    def __init__(self, sidecar_client, audio_player, notify):
        self._sidecar = sidecar_client
        self._audio = audio_player
        self._notify = notify
        self._audio.on_finished = self._on_chunk_finished
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._lock = threading.Lock()
        self._chunks = []
        self._paragraphs = []
        self._index = 0
        self._rate = 1.0
        self._speaker = ""
        self._cache = {}
        self._chapter_session_id = None
        self._playing = False

    def load_chapter(self, chunks, paragraphs, chapter_session_id, speaker, rate) -> None:
        with self._lock:
            self._chunks = chunks
            self._paragraphs = paragraphs
            self._index = 0
            self._speaker = speaker
            self._rate = rate
            self._chapter_session_id = chapter_session_id
            self._cache = {}
        self._prefetch()

    def _prefetch(self) -> None:
        with self._lock:
            end = min(len(self._chunks), self._index + PREFETCH_AHEAD)
            todo = [i for i in range(self._index, end) if i not in self._cache]
            speaker = self._speaker
        for i in todo:
            future = self._executor.submit(self._sidecar.synthesize, self._chunks[i]["text"], speaker)
            with self._lock:
                self._cache[i] = future

    def play_current(self) -> None:
        with self._lock:
            index = self._index
            total = len(self._chunks)
        if index >= total:
            self._playing = False
            self._notify({"type": "CHAPTER_DONE"})
            return
        self._prefetch()
        chunk = self._chunks[index]
        self._notify({
            "type": "CHUNK_INDEX",
            "paragraphIndex": chunk["paragraphIndex"],
            "totalParagraphs": len(self._paragraphs),
            "paragraphText": self._paragraphs[chunk["paragraphIndex"]],
        })
        self._notify({"type": "PLAYBACK_STATE", "state": "buffering"})
        with self._lock:
            future = self._cache[index]
        try:
            wav_bytes = future.result()
        except Exception as err:
            self._notify({"type": "PLAYBACK_STATE", "state": "paused"})
            self._notify({"type": "ERROR", "message": f"Sidecar unreachable: {err}"})
            return
        self._audio.load(wav_bytes)
        self._audio.play(rate=self._rate)
        self._playing = True
        self._notify({"type": "PLAYBACK_STATE", "state": "playing"})

    def _on_chunk_finished(self) -> None:
        with self._lock:
            self._index += 1
        self.play_current()

    def toggle_play(self) -> None:
        if self._playing:
            self._audio.pause()
            self._playing = False
            self._notify({"type": "PLAYBACK_STATE", "state": "paused"})
        else:
            self._audio.resume()
            self._playing = True
            self._notify({"type": "PLAYBACK_STATE", "state": "playing"})

    def set_rate(self, rate: float) -> None:
        self._rate = rate
        self._audio.set_rate(rate)

    def set_speaker(self, speaker: str) -> None:
        self._speaker = speaker
        with self._lock:
            for i in [i for i in self._cache if i > self._index]:
                del self._cache[i]
        self._prefetch()

    def skip(self, direction: int) -> None:
        with self._lock:
            chunks = self._chunks
            index = self._index
        current_paragraph = chunks[index]["paragraphIndex"] if index < len(chunks) else 0
        target_paragraph = current_paragraph + direction
        target = next((i for i, c in enumerate(chunks) if c["paragraphIndex"] == target_paragraph), None)
        if target is None:
            return
        with self._lock:
            self._index = target
        self.play_current()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m unittest test_playback -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add app/playback.py app/test_playback.py
git commit -m "feat: add playback engine (prefetch cache + state) for standalone app"
```

---

## Task 7: Injected Content Script (Extraction + Player Bar)

**Files:**
- Create: `app/web/content.js` (adapted from `extension/content.js` + `extension/readerable.js`)
- Create: `app/web/player-bar.css` (copied unchanged from `extension/player-bar.css`)

**Interfaces:**
- Consumes (from JS's perspective, calls into Python via `window.pywebview.api.*`, wired in Task 8): `get_init_data(hostname: str) -> dict` (returns `{"adapter": dict|None, "defaultRate": float, "speaker": str, "autoNext": bool, "knownSpeakers": list[str]}`), `chapter_ready(paragraphs: list[str], next_adapter: dict, title: str) -> None`, `start_playback() -> None`, `toggle_play() -> None`, `skip(direction: int) -> None`, `set_rate(rate: float) -> None`, `set_speaker(speaker: str) -> None`, `set_auto_next(enabled: bool) -> None`, `get_speakers() -> dict`.
- Produces: global functions Python calls via `evaluate_js` (wired in Task 8): `window.__vnTtsChunkIndex(paragraphIndex, totalParagraphs, paragraphText)`, `window.__vnTtsPlaybackState(state)`, `window.__vnTtsError(message)`, `window.__vnTtsChapterDone(autoNext)`.

This task has no automated test -- extraction (`extractWithAdapter`/`genericExtract`) needs real DOM layout (`cloneNode`, `innerText`), which the repo has no jsdom-style harness for (`extension/test_chunker.js` and `extension/test_background.js` only test DOM-free logic). It's verified manually in Task 9's end-to-end smoke test instead, against the app's own three configured Adapter sites.

- [ ] **Step 1: Port the adapter-resolution, extraction, and next-target logic from `extension/content.js` unchanged**

```javascript
// app/web/content.js
// Extraction, generic fallback, and the Player Bar. Chunking, playback state,
// and config all live in the Python host now -- see
// docs/adr/0009-standalone-app-replaces-extension.md. This file only does
// what needs a live DOM: reading the page, rendering the bar, and (at
// Python's command) re-querying the next-chapter link to click/navigate it.

function findNextTarget(adapter) {
  if (!adapter) return findGenericNextTarget();
  if (adapter.nextMode === "generic") return findGenericNextTarget();
  if (adapter.nextMode === "increment-url") {
    return { url: location.href.replace(/(\d+)(?!.*\d)/, (m) => String(Number(m) + 1)) };
  }
  if (adapter.nextMode === "text") {
    const links = [...document.querySelectorAll("a")];
    const el = links.find((a) => a.textContent.trim() === adapter.nextValue);
    return el ? { el } : null;
  }
  const match = document.querySelector(adapter.nextValue);
  if (!match) return null;
  return { el: match.tagName === "A" ? match : match.querySelector("a") || match };
}

function paragraphsFromInnerText(text) {
  return text.split(/\n+/).map((p) => p.replace(/\s+/g, " ").trim()).filter(Boolean);
}

function extractWithAdapter(adapter) {
  const container = document.querySelector(adapter.contentSelector);
  if (!container) return null;
  const clone = container.cloneNode(true);
  for (const sel of adapter.stripSelectors) {
    clone.querySelectorAll(sel).forEach((el) => el.remove());
  }
  clone.style.cssText = "position:fixed; left:-99999px; top:0;";
  document.body.appendChild(clone);
  const paragraphs = paragraphsFromInnerText(clone.innerText || "");
  clone.remove();
  return paragraphs;
}

const GENERIC_MIN_SCORE = 200;
const NEXT_LINK_KEYWORDS = ["chương sau", "chương tiếp", "tiếp theo", "next chapter", "next", "»", ">>"];

function scoreElement(el) {
  const text = el.innerText || "";
  let linkText = 0;
  el.querySelectorAll("a").forEach((a) => (linkText += (a.innerText || "").length));
  return text.length - linkText * 2;
}

function findGenericNextTarget() {
  const relNext = document.querySelector('a[rel="next"]');
  if (relNext) return { el: relNext };
  const links = [...document.querySelectorAll("a")];
  for (const kw of NEXT_LINK_KEYWORDS) {
    const match = links.find((a) => a.textContent.trim().toLowerCase() === kw);
    if (match) return { el: match };
  }
  return null;
}

function genericExtract() {
  if (typeof isProbablyReaderable === "function" && !isProbablyReaderable(document)) return null;
  const candidates = document.querySelectorAll("article, main, div, section");
  let best = null;
  let bestScore = GENERIC_MIN_SCORE;
  for (const el of candidates) {
    const score = scoreElement(el);
    if (score > bestScore) {
      bestScore = score;
      best = el;
    }
  }
  if (!best) return null;
  return paragraphsFromInnerText(best.innerText || "");
}
```

- [ ] **Step 2: Add the Player Bar and the `js_api` bridge, replacing every `chrome.runtime`/`chrome.storage` call**

```javascript
// app/web/content.js (continued)

let bar, textPanel, playBtn, statusEl, rateSlider, speakerSelect, textToggleBtn, autoNextCheckbox;
let started = false;
let showText = false;
let lastParagraphText = "";
let storedNextAdapter = null;

function injectPlayerBar(defaultRate, currentSpeaker, autoNextEnabled, knownSpeakers) {
  textPanel = document.createElement("div");
  textPanel.id = "vn-tts-text-panel";
  textPanel.hidden = true;
  document.body.appendChild(textPanel);

  bar = document.createElement("div");
  bar.id = "vn-tts-bar";
  bar.innerHTML = `
    <button id="vn-tts-prev" title="Previous paragraph">⏮</button>
    <button id="vn-tts-play">▶</button>
    <button id="vn-tts-next" title="Next paragraph">⏭</button>
    <input id="vn-tts-rate" type="range" min="0.5" max="2" step="0.1" value="${defaultRate}">
    <span id="vn-tts-rate-label">${defaultRate.toFixed(1)}x</span>
    <select id="vn-tts-speaker">${knownSpeakers.map((s) => `<option${s === currentSpeaker ? " selected" : ""}>${s}</option>`).join("")}</select>
    <button id="vn-tts-text-toggle" title="Show/hide current paragraph">👁</button>
    <label id="vn-tts-autonext-label" title="Automatically move to the next chapter when this one ends">
      <input type="checkbox" id="vn-tts-autonext" ${autoNextEnabled ? "checked" : ""}> Auto-next
    </label>
    <span id="vn-tts-status"></span>
  `;
  document.body.appendChild(bar);

  playBtn = bar.querySelector("#vn-tts-play");
  statusEl = bar.querySelector("#vn-tts-status");
  rateSlider = bar.querySelector("#vn-tts-rate");
  speakerSelect = bar.querySelector("#vn-tts-speaker");
  textToggleBtn = bar.querySelector("#vn-tts-text-toggle");
  autoNextCheckbox = bar.querySelector("#vn-tts-autonext");
  const rateLabel = bar.querySelector("#vn-tts-rate-label");

  playBtn.addEventListener("click", () => {
    if (!started) {
      started = true;
      playBtn.textContent = "⏸";
      window.pywebview.api.start_playback();
    } else {
      window.pywebview.api.toggle_play();
    }
  });

  const SKIP_DEBOUNCE_MS = 400;
  let lastSkipAt = 0;
  function sendSkip(direction) {
    const now = Date.now();
    if (now - lastSkipAt < SKIP_DEBOUNCE_MS) return;
    lastSkipAt = now;
    window.pywebview.api.skip(direction);
  }
  bar.querySelector("#vn-tts-prev").addEventListener("click", () => sendSkip(-1));
  bar.querySelector("#vn-tts-next").addEventListener("click", () => sendSkip(1));

  textToggleBtn.addEventListener("click", () => {
    showText = !showText;
    textPanel.hidden = !showText;
    if (showText) textPanel.textContent = lastParagraphText;
  });

  autoNextCheckbox.addEventListener("change", () => {
    window.pywebview.api.set_auto_next(autoNextCheckbox.checked);
  });

  rateSlider.addEventListener("input", () => {
    const rate = parseFloat(rateSlider.value);
    rateLabel.textContent = `${rate.toFixed(1)}x`;
    window.pywebview.api.set_rate(rate);
  });

  speakerSelect.addEventListener("change", () => {
    window.pywebview.api.set_speaker(speakerSelect.value);
  });

  window.pywebview.api.get_speakers().then((res) => {
    if (!res || !res.ok) return;
    speakerSelect.innerHTML = res.speakers
      .map((s) => `<option value="${s}"${s === currentSpeaker ? " selected" : ""}>${s}</option>`)
      .join("");
  });
}

// --- Python -> JS pushes ---

window.__vnTtsChunkIndex = function (paragraphIndex, totalParagraphs, paragraphText) {
  statusEl.onclick = null;
  statusEl.style.cursor = "";
  statusEl.textContent = `${paragraphIndex + 1} / ${totalParagraphs}`;
  lastParagraphText = paragraphText;
  if (showText) textPanel.textContent = paragraphText;
};

window.__vnTtsPlaybackState = function (state) {
  if (state === "buffering") {
    playBtn.textContent = "⏳";
    playBtn.disabled = true;
    statusEl.textContent = `Buffering…`;
  } else {
    playBtn.disabled = false;
    playBtn.textContent = state === "playing" ? "⏸" : "▶";
  }
};

window.__vnTtsError = function (message) {
  statusEl.textContent = message;
  started = false;
};

window.__vnTtsChapterDone = function (autoNext) {
  playBtn.textContent = "▶";
  started = false;
  const target = findNextTarget(storedNextAdapter);
  if (!target) {
    statusEl.textContent = "End of novel.";
    return;
  }
  const goNext = () => {
    if (target.url) location.href = target.url;
    else target.el.click();
  };
  if (autoNext) {
    goNext();
  } else {
    statusEl.textContent = "Chapter done — click to continue ➜";
    statusEl.style.cursor = "pointer";
    statusEl.onclick = goNext;
  }
};

// --- Boot ---

(async function init() {
  const init = await window.pywebview.api.get_init_data(location.hostname);
  const adapter = init.adapter;
  const paragraphs = adapter ? extractWithAdapter(adapter) : genericExtract();
  if (!paragraphs || !paragraphs.length) return; // nothing readable here -- stay invisible

  storedNextAdapter = adapter;
  injectPlayerBar(init.defaultRate, init.speaker, init.autoNext, init.knownSpeakers);
  window.pywebview.api.chapter_ready(paragraphs, adapter, document.title);
})();
```

- [ ] **Step 3: Copy the CSS unchanged**

```bash
cp extension/player-bar.css app/web/player-bar.css
```

- [ ] **Step 4: Commit**

```bash
git add app/web/content.js app/web/player-bar.css
git commit -m "feat: port extraction and Player Bar JS to the standalone app's Web View"
```

---

## Task 8: Api Bridge

**Files:**
- Create: `app/api.py`
- Test: `app/test_api.py`

**Interfaces:**
- Consumes: `Config` (Task 2), `chunker.build_paragraph_chunks` (Task 3), `SidecarClient` (Task 4), `PlaybackEngine` (Task 6).
- Produces: `Api(config, playback, sidecar_client)` exposing the methods `content.js` calls (Task 7): `get_init_data`, `chapter_ready`, `start_playback`, `toggle_play`, `skip`, `set_rate`, `set_speaker`, `set_auto_next`, `get_speakers`. Task 9 (`main.py`) constructs one `Api` instance, passes it to `pywebview.create_window(..., js_api=api)`, and wires `PlaybackEngine`'s `notify` callback to push events into the page via `window.evaluate_js`.

- [ ] **Step 1: Write the failing test**

```python
# app/test_api.py
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
        result = self.api.chapter_ready(["Câu một. Câu hai.", "Đoạn hai."], None, "My Chapter")
        self.playback.load_chapter.assert_called_once()
        args, kwargs = self.playback.load_chapter.call_args
        chunks = args[0]
        self.assertEqual(len(chunks), 3)
        self.assertIn("chapterSessionId", result)

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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m unittest test_api -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/api.py
"""The js_api bridge: methods content.js calls as window.pywebview.api.*.
See docs/adr/0009-standalone-app-replaces-extension.md -- JS sends intents,
this class (backed by Config and PlaybackEngine) owns all the state.
"""
import time

from chunker import build_paragraph_chunks
from config import KNOWN_SPEAKERS


class Api:
    def __init__(self, config, playback, sidecar_client):
        self._config = config
        self._playback = playback
        self._sidecar = sidecar_client

    def get_init_data(self, hostname: str) -> dict:
        return {
            "adapter": self._config.find_adapter(hostname),
            "defaultRate": self._config.get("defaultRate"),
            "speaker": self._config.get("speaker"),
            "autoNext": self._config.get("autoNext"),
            "knownSpeakers": KNOWN_SPEAKERS,
        }

    def chapter_ready(self, paragraphs: list, next_adapter, title: str) -> dict:
        chunks = build_paragraph_chunks(paragraphs)
        session_id = f"{title}-{time.time()}"
        self._playback.load_chapter(
            chunks, paragraphs, session_id,
            speaker=self._config.get("speaker"),
            rate=self._config.get("defaultRate"),
        )
        return {"chapterSessionId": session_id}

    def start_playback(self) -> None:
        self._playback.play_current()

    def toggle_play(self) -> None:
        self._playback.toggle_play()

    def skip(self, direction: int) -> None:
        self._playback.skip(direction)

    def set_rate(self, rate: float) -> None:
        self._config.set("defaultRate", rate)
        self._playback.set_rate(rate)

    def set_speaker(self, speaker: str) -> None:
        self._config.set("speaker", speaker)
        self._playback.set_speaker(speaker)

    def set_auto_next(self, enabled: bool) -> None:
        self._config.set("autoNext", enabled)

    def get_speakers(self) -> dict:
        try:
            return {"ok": True, "speakers": self._sidecar.speakers()}
        except Exception:
            return {"ok": False}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m unittest test_api -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add app/api.py app/test_api.py
git commit -m "feat: add js_api bridge connecting content.js to the Python host"
```

---

## Task 9: Options Window

**Files:**
- Create: `app/web/options.html` (adapted from `extension/options.html`)
- Create: `app/web/options.js` (adapted from `extension/options.js`)
- Modify: `app/api.py` -- add adapter CRUD methods

**Interfaces:**
- Consumes: `Config.get`/`.set` (Task 2).
- Produces: `Api.get_adapters() -> list[dict]`, `Api.save_adapters(adapters: list[dict]) -> None`, `Api.get_settings() -> dict`, `Api.save_settings(settings: dict) -> None` -- added to the `Api` class from Task 8. Task 10 (`main.py`) opens a second `pywebview` window pointed at `app/web/options.html`, sharing the same `Api` instance as `js_api`.

No automated test for `options.html`/`options.js` -- same reasoning as Task 7 (DOM-driven form UI, no jsdom harness in this repo). Verified manually in Task 10's smoke test.

- [ ] **Step 1: Add adapter/settings CRUD to `Api`, with a unit test (this part is pure Python, testable)**

```python
# app/test_api.py (append to TestApi)
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m unittest test_api -v`
Expected: FAIL -- `AttributeError: 'Api' object has no attribute 'get_adapters'`

- [ ] **Step 3: Implement the CRUD methods**

```python
# app/api.py (append to Api)
    def get_adapters(self) -> list:
        return self._config.get("adapters")

    def save_adapters(self, adapters: list) -> None:
        self._config.set("adapters", adapters)

    def get_settings(self) -> dict:
        return {
            "sidecarUrl": self._config.get("sidecarUrl"),
            "speaker": self._config.get("speaker"),
            "defaultRate": self._config.get("defaultRate"),
        }

    def save_settings(self, settings: dict) -> None:
        for key in ("sidecarUrl", "speaker", "defaultRate"):
            if key in settings:
                self._config.set(key, settings[key])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m unittest test_api -v`
Expected: PASS, 12 tests

- [ ] **Step 5: Port the Options page HTML/JS, replacing `chrome.storage` with `js_api` calls**

```html
<!-- app/web/options.html -->
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Reading Web -- Options</title>
  <style>
    body { font-family: sans-serif; margin: 1rem; max-width: 640px; }
    label { display: block; margin-top: 0.75rem; }
    textarea { width: 100%; height: 200px; font-family: monospace; }
    input[type=text], input[type=number] { width: 100%; }
  </style>
</head>
<body>
  <h1>Settings</h1>
  <label>Sidecar URL <input id="sidecarUrl" type="text"></label>
  <label>Default speaker <input id="speaker" type="text"></label>
  <label>Default rate <input id="defaultRate" type="number" step="0.1" min="0.5" max="2"></label>
  <button id="saveSettings">Save settings</button>

  <h1>Adapters (JSON)</h1>
  <textarea id="adapters"></textarea>
  <button id="saveAdapters">Save adapters</button>
  <p id="status"></p>

  <script src="options.js"></script>
</body>
</html>
```

```javascript
// app/web/options.js
async function load() {
  const settings = await window.pywebview.api.get_settings();
  document.getElementById("sidecarUrl").value = settings.sidecarUrl;
  document.getElementById("speaker").value = settings.speaker;
  document.getElementById("defaultRate").value = settings.defaultRate;

  const adapters = await window.pywebview.api.get_adapters();
  document.getElementById("adapters").value = JSON.stringify(adapters, null, 2);
}

function status(msg) {
  document.getElementById("status").textContent = msg;
  setTimeout(() => (document.getElementById("status").textContent = ""), 2000);
}

document.getElementById("saveSettings").addEventListener("click", async () => {
  await window.pywebview.api.save_settings({
    sidecarUrl: document.getElementById("sidecarUrl").value,
    speaker: document.getElementById("speaker").value,
    defaultRate: parseFloat(document.getElementById("defaultRate").value),
  });
  status("Settings saved.");
});

document.getElementById("saveAdapters").addEventListener("click", async () => {
  let parsed;
  try {
    parsed = JSON.parse(document.getElementById("adapters").value);
  } catch (err) {
    status(`Invalid JSON: ${err.message}`);
    return;
  }
  await window.pywebview.api.save_adapters(parsed);
  status("Adapters saved.");
});

window.addEventListener("pywebviewready", load);
```

- [ ] **Step 6: Commit**

```bash
git add app/api.py app/test_api.py app/web/options.html app/web/options.js
git commit -m "feat: add Options window with adapter/settings CRUD"
```

---

## Task 10: Main Entry Point & Wiring

**Files:**
- Create: `app/main.py`
- Create: `app/run.bat`
- Create: `app/README.md`

**Interfaces:**
- Consumes: `SidecarManager` (Task 1), `Config` (Task 2), `SidecarClient` (Task 4), `AudioPlayer` (Task 5), `PlaybackEngine` (Task 6), `app/web/content.js` + `player-bar.css` + `readerable.js` (Task 7), `Api` (Task 8, 9), `app/web/options.html` (Task 9).
- Produces: the runnable app (`python main.py`). Nothing later consumes this -- it's the composition root.

No automated test -- this file only wires already-tested components together (dependency injection), and the composed result (a real window, real audio device, real Sidecar subprocess) can only be meaningfully verified by running it. Verified in Step 4's manual smoke test.

- [ ] **Step 1: Write `main.py`**

```python
# app/main.py
"""Entry point: spawns the Sidecar, opens the main Web View window with the
content script injected on every navigation, and wires the js_api bridge.
See docs/adr/0009-standalone-app-replaces-extension.md.
"""
import json
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

import webview

from api import Api
from audio_player import AudioPlayer
from config import Config
from playback import PlaybackEngine
from sidecar_client import SidecarClient
from sidecar_manager import SidecarManager

APP_DIR = Path(__file__).parent
REPO_DIR = APP_DIR.parent
WEB_DIR = APP_DIR / "web"
CONFIG_PATH = Path.home() / "AppData" / "Roaming" / "reading-web" / "config.json"

READERABLE_JS = (WEB_DIR / "readerable.js").read_text(encoding="utf-8")
CONTENT_JS = (WEB_DIR / "content.js").read_text(encoding="utf-8")
PLAYER_BAR_CSS = (WEB_DIR / "player-bar.css").read_text(encoding="utf-8")

_main_window = None


def push_to_js(event: dict) -> None:
    if _main_window is None:
        return
    if event["type"] == "CHUNK_INDEX":
        _main_window.evaluate_js(
            f"window.__vnTtsChunkIndex({event['paragraphIndex']}, {event['totalParagraphs']}, {json.dumps(event['paragraphText'])})"
        )
    elif event["type"] == "PLAYBACK_STATE":
        _main_window.evaluate_js(f"window.__vnTtsPlaybackState({json.dumps(event['state'])})")
    elif event["type"] == "ERROR":
        _main_window.evaluate_js(f"window.__vnTtsError({json.dumps(event['message'])})")
    elif event["type"] == "CHAPTER_DONE":
        auto_next = config.get("autoNext")
        _main_window.evaluate_js(f"window.__vnTtsChapterDone({json.dumps(auto_next)})")


def inject_content_script(window) -> None:
    window.evaluate_js(
        "document.getElementById('vn-tts-style') || "
        "(function(){const s=document.createElement('style'); s.id='vn-tts-style'; "
        f"s.textContent = {json.dumps(PLAYER_BAR_CSS)}; document.head.appendChild(s);}})()"
    )
    # readerable.js must run first -- content.js's genericExtract() calls
    # isProbablyReaderable() at call time and expects it already defined.
    window.evaluate_js(READERABLE_JS)
    window.evaluate_js(CONTENT_JS)


def open_options_window() -> None:
    webview.create_window(
        "Reading Web -- Options",
        url=str(WEB_DIR / "options.html"),
        js_api=api,
        width=680, height=600,
    )


if __name__ == "__main__":
    config = Config(CONFIG_PATH)
    sidecar_manager = SidecarManager(
        python_exe=str(REPO_DIR / "sidecar" / "venv" / "Scripts" / "python.exe"),
        cwd=str(REPO_DIR / "sidecar"),
        port=8934,
    )
    sidecar_manager.start()

    def warn_if_sidecar_unhealthy():
        if not sidecar_manager.wait_healthy():
            print("Warning: Sidecar did not become healthy within the timeout.", file=sys.stderr)

    threading.Thread(target=warn_if_sidecar_unhealthy, daemon=True).start()

    sidecar_client = SidecarClient(config.get("sidecarUrl"))
    audio_player = AudioPlayer(on_finished=lambda: None)  # PlaybackEngine overwrites on_finished
    playback = PlaybackEngine(sidecar_client, audio_player, notify=push_to_js)
    api = Api(config, playback, sidecar_client)

    _main_window = webview.create_window(
        "Reading Web",
        url="https://metruyenchu.co",  # starting page; address bar lets the reader go anywhere
        js_api=api,
        width=1200, height=900,
    )
    _main_window.events.loaded += lambda: inject_content_script(_main_window)

    def on_closed():
        sidecar_manager.stop()

    _main_window.events.closed += on_closed

    webview.start()
```

- [ ] **Step 2: Write the launcher script**

```batch
:: app/run.bat
.\venv\Scripts\python.exe main.py
```

- [ ] **Step 3: Write setup docs**

```markdown
<!-- app/README.md -->
# App

The standalone Windows app: embeds a Web View, spawns the Sidecar, and owns
all playback state. Replaces the Chrome extension -- see
[docs/adr/0009-standalone-app-replaces-extension.md](../docs/adr/0009-standalone-app-replaces-extension.md).

## Setup (once)

```bash
cd app
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Also install VLC... no -- this app uses `sounddevice`, not `python-vlc`, so
there is nothing extra to install beyond `pip install -r requirements.txt`.
Make sure `sidecar/venv` is already set up per [sidecar/README.md](../sidecar/README.md)
-- this app spawns that venv's Python directly.

## Run

```bash
run.bat
```

Starts the Sidecar automatically (no separate terminal needed, unlike the
old extension setup) and opens the main window. Closing the window stops
the Sidecar too.

## Options

Right-click isn't available in a Web View -- for now, open Options by
calling `open_options_window()` from `main.py` (a menu/keyboard shortcut is
a follow-up, not blocking this plan).
```

- [ ] **Step 4: Manual end-to-end smoke test**

This is the point where the composed app is first actually run. Walk through each item and confirm it works before considering this task done:

1. Run `sidecar\server.bat` once by hand and confirm `http://localhost:8934/speakers` responds, then stop it -- confirms the venv itself is healthy before the app tries to spawn it.
2. Run `app\run.bat`. Confirm the Sidecar starts automatically (check Task Manager for a `python.exe`/`uvicorn` process) and the main window opens showing `metruyenchu.co`.
3. Navigate to a real chapter on `metruyenchu.co`. Confirm the Player Bar appears in the bottom-right.
4. Press Play. Confirm audio plays and the status line advances through paragraphs.
5. Drag the rate slider while audio is playing. Confirm the rate changes within a second or two (not just on the next chunk).
6. Change the speaker mid-chapter. Confirm the next chunk uses the new voice.
7. Click the prev/next paragraph buttons. Confirm playback jumps by paragraph, not by sentence.
8. Let a chapter play to the end with Auto-next checked. Confirm the app navigates to the next chapter and playback restarts automatically.
9. Uncheck Auto-next, let a chapter finish. Confirm the status line shows "Chapter done — click to continue" and clicking it navigates.
10. Navigate to `khotruyenchu.fun` and `dichtienghoa.net` chapters. Confirm extraction and next-chapter detection work for all three configured Adapters, not just one.
11. Navigate to a site with no configured Adapter. Confirm the generic fallback either finds readable text or the bar stays hidden -- no error.
12. Close the main window. Confirm the Sidecar's `python.exe` process is also gone from Task Manager (no orphaned process).

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/run.bat app/README.md
git commit -m "feat: wire up main entry point for the standalone app"
```

---

## Self-Review Notes

- **Spec coverage:** every settled decision from the grilling session (scope/replace, `pywebview`, spawned Sidecar, minimal browser chrome, JSON config, portable script, audio-in-Python-host, JS/Python split, intents-up/state-down, Options as HTML+`js_api`, dropped multi-tab guard, playback survives manual nav, no media keys, `evaluate_js`-driven next-chapter trigger, `sounddevice` over `python-vlc` with accepted pitch shift, quit-on-close, separate venvs, keep `extension/` until proven, no migration, ported chunker tests) has a corresponding task above.
- **No placeholders:** every step has real code or a concrete manual-verification checklist; no "add error handling" or "similar to Task N" stand-ins.
- **Type/name consistency checked:** `PlaybackEngine.notify` event shape (`CHUNK_INDEX`/`PLAYBACK_STATE`/`ERROR`/`CHAPTER_DONE`) matches what `push_to_js` in Task 10 switches on and what `content.js`'s `window.__vnTts*` functions in Task 7 expect. `Api`'s method names match exactly what `content.js`/`options.js` call via `window.pywebview.api.*`.
