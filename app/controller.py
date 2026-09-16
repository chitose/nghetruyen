"""Shared state and actions for the App's two surfaces.

The App now has a NiceGUI chrome (address bar + Player Bar + Options, its own
window) and a native Web View showing the Chapter (its own window). Both send
intents here, and this one object owns the settings, the playback engine, and
the values the chrome renders -- so there is still exactly one source of truth
for playback state, the property ADR-0009 was written to protect.

See docs/adr/0010-nicegui-chrome.md.
"""
import threading

from chunker import build_paragraph_chunks, join_short_paragraphs
from config import (
    DEFAULT_SHORT_PARAGRAPH_WORDS,
    DEFAULT_START_URL,
    DEFAULT_VISUALIZER_STYLE,
    KNOWN_SPEAKERS,
    VISUALIZER_STYLES,
)
from sidecar_manager import FAILED as SIDECAR_FAILED
from sidecar_manager import READY as SIDECAR_READY
from sidecar_manager import STARTING as SIDECAR_STARTING

# A burst of next/prev clicks is applied as one jump once the clicks pause, so
# holding the buttons skips several Paragraphs instead of firing a synthesis
# (and a thread) per click.
SKIP_COALESCE_SECONDS = 0.25


def _start_timer(delay: float, callback) -> "threading.Timer":
    timer = threading.Timer(delay, callback)
    timer.daemon = True
    timer.start()
    return timer


class Controller:
    def __init__(self, config, playback, sidecar_client, schedule_timer=None):
        self._config = config
        self._playback = playback
        self._sidecar = sidecar_client
        self._content_window = None
        self._lock = threading.Lock()
        self._pending_auto_start = False
        self._reader_url = ""  # last real Page, so Options can hand the reader back
        self._returning_to_reader = False
        self._skip_chapter_reload = False
        self._dock = None  # docking.Dock, for resizing/moving the Controls strip
        self._quit = None  # main.py's shutdown, for the chrome's close button
        self._sidecar_retry = None  # main.py's SidecarStartup.start, for Retry
        self._visualizer = None  # visualizer.Visualizer, for the chrome's bars
        self._schedule_timer = schedule_timer or _start_timer
        self._skip_lock = threading.Lock()
        self._skip_pending = 0
        self._skip_scheduled = False

        # --- what the chrome renders. Plain attributes updated from the
        # playback worker threads and polled by the NiceGUI page -- each
        # assignment is atomic, so a stale read is harmless. ---
        self.current_url = ""
        self.page_title = ""
        self.url_rev = 0  # bumped on every real navigation, so the chrome knows
                          # when to overwrite the address bar (and when not to)
        self.settings_rev = 0  # bumped when rate/speaker/auto-next change, so
                               # the Options page and the Player Bar agree
        self.paragraph_index = 0
        self.total_paragraphs = 0
        self.paragraph_text = ""
        self.window_visible = True  # the reader window, toggled from the chrome
        self.playback_state = "idle"  # idle | buffering | playing | paused
        self.status = "Open a chapter to start reading."
        self.error_message = ""
        self.chapter_loaded = False
        self.chapter_done = False

        # --- Sidecar startup, which happens while the chrome is already on
        # screen. The status line reports it and Retry appears after a failure
        # -- the Sidecar used to be spawned in silence (see
        # docs/adr/0013-sidecar-startup-status.md). ---
        self.sidecar_starting = True
        self.sidecar_failed = False
        self.sidecar_message = ""

    # --- wiring -------------------------------------------------------------

    def attach_content_window(self, window, hidden: bool = False) -> None:
        """The native Web View the chrome drives. Set once, right after
        webview.create_window().

        `hidden` says the window was created hidden -- Hide page was the last
        thing the reader did before closing, and the session remembered it
        (ADR-0011). `window_visible` has to agree from the start, so the
        chrome's first tick draws "Show page" rather than a button that claims
        a window you cannot see is on screen.
        """
        self._content_window = window
        self.window_visible = not hidden

    def attach_dock(self, dock) -> None:
        """The docked Controls strip, so the chrome can resize and move it.
        main.py passes the docking.Dock."""
        self._dock = dock

    def set_dock_height(self, height) -> None:
        if self._dock is not None:
            self._dock.set_height(height)

    def begin_dock_move(self) -> None:
        if self._dock is not None:
            self._dock.begin_move()

    def move_dock(self, dx, dy) -> None:
        if self._dock is not None:
            self._dock.move_by(dx, dy)

    def end_dock_move(self) -> None:
        if self._dock is not None:
            self._dock.end_move()

    def attach_visualizer(self, visualizer) -> None:
        """main.py's audio Visualizer, for the control window's bars."""
        self._visualizer = visualizer

    def visualizer_levels(self):
        """Bar heights for this instant, or None when nothing is playing."""
        if self._visualizer is None:
            return None
        return self._visualizer.snapshot()

    @property
    def visualizer_style(self) -> str:
        style = self._config.get("visualizerStyle")
        return style if style in VISUALIZER_STYLES else DEFAULT_VISUALIZER_STYLE

    def cycle_visualizer_style(self, step: int = 1) -> None:
        """Next/previous visualizer style -- the chrome's carousel arrows."""
        styles = VISUALIZER_STYLES
        index = styles.index(self.visualizer_style)
        self._config.set("visualizerStyle", styles[(index + step) % len(styles)])
        self.settings_rev += 1

    def attach_quit(self, quit_fn) -> None:
        """main.py's shutdown, so the chrome's close button can quit the App."""
        self._quit = quit_fn

    def quit(self) -> None:
        if self._quit is not None:
            self._quit()

    def attach_sidecar_retry(self, retry_fn) -> None:
        """main.py's SidecarStartup.start, for the chrome's Retry button."""
        self._sidecar_retry = retry_fn

    def retry_sidecar(self) -> None:
        if self._sidecar_retry is not None:
            self._sidecar_retry()

    def report_sidecar(self, state: str, message: str = "") -> None:
        """Sidecar startup progress, from main.py's SidecarStartup thread.

        The chrome polls this instead of the Sidecar failing silently into
        sidecar.log. A watch that starts or finally succeeds also clears a
        stale "Sidecar unreachable" from an earlier attempt; a failure that
        persists reports itself again."""
        with self._lock:
            self.sidecar_starting = state not in (SIDECAR_READY, SIDECAR_FAILED)
            self.sidecar_failed = state == SIDECAR_FAILED
            self.sidecar_message = message
            if state in (SIDECAR_STARTING, SIDECAR_READY):
                self.error_message = ""

    @property
    def known_speakers(self) -> list:
        return KNOWN_SPEAKERS

    # --- config, for the chrome's Options page -------------------------------

    def get_settings(self) -> dict:
        return {
            "sidecarUrl": self._config.get("sidecarUrl"),
            "startUrl": self._config.get("startUrl"),
            "restoreLastPage": bool(self._config.get("restoreLastPage", True)),
            "speaker": self._config.get("speaker"),
            "defaultRate": self._config.get("defaultRate"),
            "backendModel": self._config.get("backendModel"),
            "joinShortParagraphs": bool(self._config.get("joinShortParagraphs", False)),
            "shortParagraphWords": self.short_paragraph_words,
        }

    def save_settings(self, settings: dict) -> None:
        for key in ("sidecarUrl", "startUrl", "restoreLastPage",
                    "speaker", "defaultRate", "backendModel",
                    "joinShortParagraphs", "shortParagraphWords"):
            if key in settings:
                self._config.set(key, settings[key])
        self.settings_rev += 1

    @property
    def start_url(self) -> str:
        """Where the Web View opens; a bare host gets https:// like the
        address bar does."""
        url = (self._config.get("startUrl") or DEFAULT_START_URL).strip()
        return url if "://" in url else "https://" + url

    @property
    def join_short_paragraphs(self) -> bool:
        """Whether a Short paragraph is read together with the ones after it."""
        return bool(self._config.get("joinShortParagraphs", False))

    @property
    def short_paragraph_words(self) -> int:
        try:
            words = int(self._config.get("shortParagraphWords", DEFAULT_SHORT_PARAGRAPH_WORDS))
        except (TypeError, ValueError):
            return DEFAULT_SHORT_PARAGRAPH_WORDS
        return max(1, words)

    @property
    def restore_last_page(self) -> bool:
        """Whether launch reopens session.json's lastUrl instead of start_url."""
        return bool(self._config.get("restoreLastPage", True))

    def get_adapters(self) -> list:
        return self._config.get("adapters")

    def save_adapters(self, adapters: list) -> None:
        self._config.set("adapters", adapters)

    @property
    def rate(self) -> float:
        return self._config.get("defaultRate")

    @property
    def speaker(self) -> str:
        return self._config.get("speaker")

    @property
    def auto_next(self) -> bool:
        return bool(self._config.get("autoNext"))

    def get_speakers(self) -> dict:
        """Live voice list from the Sidecar; the chrome falls back to the
        baked-in KNOWN_SPEAKERS when this says ok is False."""
        try:
            return {"ok": True, "speakers": self._sidecar.speakers()}
        except Exception:
            return {"ok": False}

    # --- content.js -> Python ------------------------------------------------

    def get_init_data(self, hostname: str) -> dict:
        return {
            "adapter": self._config.find_adapter(hostname),
            "defaultRate": self._config.get("defaultRate"),
            "speaker": self._config.get("speaker"),
            "autoNext": self._config.get("autoNext"),
            "knownSpeakers": KNOWN_SPEAKERS,
        }

    def page_loaded(self, url: str, title: str, paragraph_count: int) -> None:
        """Every navigation reports in, readable or not, so the chrome can show
        where it is and say so when a Page has nothing to read.

        A report that matches the Page we left for Options is a return, not a
        new read: the Chapter stays loaded, so playback and position survive
        the round-trip (see open_options/leave_options)."""
        returning = bool(
            self._returning_to_reader
            and url == self._reader_url
            and self.chapter_loaded
            and paragraph_count
        )
        with self._lock:
            self.current_url = url or ""
            self.page_title = title or ""
            self.url_rev += 1
            self._returning_to_reader = False
            self._skip_chapter_reload = returning
            if returning:
                return
            self.chapter_loaded = False
            self.chapter_done = False
            self.error_message = ""
            self.paragraph_index = 0
            self.total_paragraphs = paragraph_count or 0
            self.paragraph_text = ""
            self.status = "" if paragraph_count else "No readable Chapter found on this Page."

    def chapter_ready(self, paragraphs: list, title: str) -> dict:
        if self.join_short_paragraphs:
            paragraphs = join_short_paragraphs(paragraphs, self.short_paragraph_words)
        with self._lock:
            skip_reload = (
                self._skip_chapter_reload
                and self.chapter_loaded
                and len(paragraphs) == self.total_paragraphs
            )
            self._skip_chapter_reload = False
        if skip_reload:
            return {"autoStart": False}

        chunks = build_paragraph_chunks(paragraphs)
        self._playback.load_chapter(
            chunks, paragraphs,
            speaker=self._config.get("speaker"),
            rate=self._config.get("defaultRate"),
        )
        with self._lock:
            auto_start = self._pending_auto_start
            self._pending_auto_start = False
            self.page_title = title or self.page_title
            self.chapter_loaded = True
            self.chapter_done = False
            self.total_paragraphs = len(paragraphs)
            self.paragraph_index = 0
            self.paragraph_text = paragraphs[0] if paragraphs else ""
            self.error_message = ""
            self.status = ""
        if auto_start:
            self._playback.play_current()
        return {"autoStart": auto_start}

    # --- chrome -> Python ----------------------------------------------------

    def toggle_window(self) -> None:
        """Show or hide the reader window. The Controls strip stays visible, so
        the button that hid it is also the one that brings it back."""
        if self._content_window is None:
            return
        if self.window_visible:
            self._content_window.hide()
            self.window_visible = False
        else:
            self.show_window()

    def show_window(self) -> None:
        """Bring the reader window back, if it is hidden.

        Anything that puts something *in* the reader window has to call this
        first: Options opens there (open_options below), and on a hidden reader
        that click looked like it had done nothing at all.
        """
        if self._content_window is None or self.window_visible:
            return
        self._content_window.show()
        self.window_visible = True

    def open_options(self, url: str) -> None:
        """Show the Options page in the reader window (the Controls strip is
        too small for it), remembering the Page so leave_options() can hand it
        back. The reader is revealed first -- Options in a window the reader
        has hidden behind the strip is Options nobody can see."""
        self._reader_url = self.current_url or self._reader_url
        self.show_window()
        self._load_url(url)

    def leave_options(self) -> None:
        """Return the reader window to the Page it was showing before."""
        if self._reader_url:
            self._returning_to_reader = True
            self._load_url(self._reader_url)
        else:
            self._eval("history.back()")

    def navigate(self, url: str) -> None:
        url = (url or "").strip()
        if not url:
            return
        if "://" not in url:
            url = "https://" + url
        self._load_url(url)

    def go_back(self) -> None:
        self._eval("history.back()")

    def go_forward(self) -> None:
        self._eval("history.forward()")

    def play_pause(self) -> None:
        """First press starts the loaded Chapter; after that it pauses/resumes.
        A press at the end of a finished Chapter is a no-op rather than a
        second auto-next."""
        if not self.chapter_loaded or self.chapter_done:
            return
        if self.playback_state in ("playing", "paused"):
            self._playback.toggle_play()
        elif self.playback_state == "idle":
            self._playback.play_current()

    def toggle_play(self) -> None:
        self._playback.toggle_play()

    def skip(self, direction: int) -> None:
        """Next/prev Paragraph.

        Clicks are coalesced: a burst moves once, by the number of clicks, when
        it ends. Applying each click as it came fired one synthesis request per
        click, so spamming (or a stuck mouse) stuttered and queued work the
        click had already superseded."""
        if direction not in (-1, 1):
            return
        with self._skip_lock:
            self._skip_pending += direction
            if self._skip_scheduled:
                return
            self._skip_scheduled = True
        self._schedule_timer(SKIP_COALESCE_SECONDS, self._flush_skip)

    def _flush_skip(self) -> None:
        with self._skip_lock:
            pending = self._skip_pending
            self._skip_pending = 0
            self._skip_scheduled = False
        if pending:
            self._playback.skip(1 if pending > 0 else -1, steps=abs(pending))

    def set_rate(self, rate: float) -> None:
        self._config.set("defaultRate", rate)
        self._playback.set_rate(rate)
        self.settings_rev += 1

    def set_speaker(self, speaker: str) -> None:
        self._config.set("speaker", speaker)
        self._playback.set_speaker(speaker)
        self.settings_rev += 1

    def set_auto_next(self, enabled: bool) -> None:
        self._config.set("autoNext", bool(enabled))
        self.settings_rev += 1

    def advance_chapter(self) -> bool:
        """Ask the Web View to follow its next-chapter link. False when there
        is no link (end of novel) or no Page is loaded."""
        result = self._eval("window.__vnTtsGoNext ? window.__vnTtsGoNext() : null")
        return bool(result)

    # --- PlaybackEngine notify target ----------------------------------------

    def on_playback_event(self, event: dict) -> None:
        etype = event["type"]
        if etype == "CHUNK_INDEX":
            with self._lock:
                self.paragraph_index = event["paragraphIndex"]
                self.total_paragraphs = event["totalParagraphs"]
                self.paragraph_text = event["paragraphText"]
                self.error_message = ""
                # Audio exists, so the Sidecar answered: a startup failure
                # banner is stale now (it may have been started by hand after
                # the App gave up on it).
                self.sidecar_starting = False
                self.sidecar_failed = False
                self.sidecar_message = ""
        elif etype == "PLAYBACK_STATE":
            with self._lock:
                self.playback_state = event["state"]
        elif etype == "ERROR":
            with self._lock:
                self.playback_state = "paused"
                self.error_message = event["message"]
                self.status = event["message"]
        elif etype == "CHAPTER_DONE":
            with self._lock:
                if self.chapter_done:
                    return  # already handled; don't auto-next twice
                self.playback_state = "idle"
                self.chapter_done = True
                auto_next = self.auto_next
                if auto_next:
                    self._pending_auto_start = True
            if auto_next and not self.advance_chapter():
                with self._lock:
                    self._pending_auto_start = False
                    self.status = "End of novel."

    # --- window helpers ------------------------------------------------------

    def _eval(self, script: str):
        if self._content_window is None:
            return None
        try:
            return self._content_window.evaluate_js(script)
        except Exception:
            return None

    def _load_url(self, url: str) -> None:
        if self._content_window is None:
            return
        try:
            self._content_window.load_url(url)
        except Exception:
            pass
