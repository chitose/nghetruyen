import unittest
from unittest.mock import MagicMock

from config import (
    DEFAULT_ADAPTERS,
    DEFAULT_SHORT_PARAGRAPH_WORDS,
    DEFAULT_START_URL,
)
from controller import Controller
from sidecar_manager import FAILED, READY, STARTING


class FakeScheduler:
    """Stands in for threading.Timer, so skip coalescing is deterministic."""

    def __init__(self):
        self.scheduled = []

    def __call__(self, delay, callback):
        self.scheduled.append((delay, callback))
        return None

    def run_pending(self):
        pending, self.scheduled = self.scheduled, []
        for _delay, callback in pending:
            callback()


class TestController(unittest.TestCase):
    def setUp(self):
        self.config = MagicMock()
        self.config.get.side_effect = lambda key, default=None: {
            "defaultRate": 1.0, "speaker": "Minh Quân", "autoNext": True,
            "sidecarUrl": "http://localhost:8934", "backendModel": "default",
            "adapters": list(DEFAULT_ADAPTERS),
        }.get(key, default)
        self.config.find_adapter.side_effect = lambda host: next(
            (a for a in DEFAULT_ADAPTERS if a["hostname"] == host), None
        )
        self.playback = MagicMock()
        self.sidecar = MagicMock()
        self.window = MagicMock()
        self.scheduler = FakeScheduler()
        self.controller = Controller(
            self.config, self.playback, self.sidecar, schedule_timer=self.scheduler,
        )
        self.controller.attach_content_window(self.window)

    # --- Page reporting ------------------------------------------------------

    def test_page_loaded_records_url_and_bumps_revision(self):
        before = self.controller.url_rev
        self.controller.page_loaded("https://x.test/c1", "Chapter 1", 3)
        self.assertEqual(self.controller.current_url, "https://x.test/c1")
        self.assertEqual(self.controller.page_title, "Chapter 1")
        self.assertEqual(self.controller.total_paragraphs, 3)
        self.assertEqual(self.controller.url_rev, before + 1)
        self.assertEqual(self.controller.status, "")

    def test_page_loaded_with_no_paragraphs_says_so(self):
        self.controller.page_loaded("https://x.test/", "Nothing", 0)
        self.assertIn("No readable Chapter", self.controller.status)
        self.assertFalse(self.controller.chapter_loaded)

    def test_chapter_ready_builds_chunks_and_loads_playback_engine(self):
        result = self.controller.chapter_ready(["Câu một. Câu hai.", "Đoạn hai."], "My Chapter")
        self.playback.load_chapter.assert_called_once()
        chunks = self.playback.load_chapter.call_args.args[0]
        # One chunk per Paragraph here: each Paragraph fits in a chunk, and
        # chunks never span a Paragraph boundary (chunker.build_paragraph_chunks).
        self.assertEqual(
            [(c["text"], c["paragraphIndex"]) for c in chunks],
            [("Câu một. Câu hai.", 0), ("Đoạn hai.", 1)],
        )
        self.assertFalse(result["autoStart"])
        self.assertTrue(self.controller.chapter_loaded)
        self.assertEqual(self.controller.paragraph_text, "Câu một. Câu hai.")

    def test_chapter_ready_auto_starts_when_pending(self):
        self.controller._pending_auto_start = True
        result = self.controller.chapter_ready(["Câu một."], "My Chapter")
        self.playback.play_current.assert_called_once()
        self.assertTrue(result["autoStart"])
        # consumed, not sticky across chapters
        self.controller.chapter_ready(["Câu hai."], "Another")
        self.assertEqual(self.playback.play_current.call_count, 1)

    # --- Address bar ---------------------------------------------------------

    def test_navigate_defaults_to_https(self):
        self.controller.navigate("example.com/chap")
        self.window.load_url.assert_called_once_with("https://example.com/chap")

    def test_navigate_keeps_an_explicit_scheme_and_ignores_blanks(self):
        self.controller.navigate("http://example.com")
        self.window.load_url.assert_called_with("http://example.com")
        self.controller.navigate("   ")
        self.assertEqual(self.window.load_url.call_count, 1)

    def test_back_and_forward_drive_webview_history(self):
        self.controller.go_back()
        self.controller.go_forward()
        self.assertEqual(
            [c.args[0] for c in self.window.evaluate_js.call_args_list],
            ["history.back()", "history.forward()"],
        )

    # --- Player Bar ----------------------------------------------------------

    def test_play_pause_is_a_noop_before_a_chapter_is_loaded(self):
        self.controller.play_pause()
        self.playback.play_current.assert_not_called()
        self.playback.toggle_play.assert_not_called()

    def test_play_pause_starts_an_idle_loaded_chapter(self):
        self.controller.chapter_ready(["Câu một."], "C")
        self.playback.reset_mock()
        self.controller.playback_state = "idle"
        self.controller.play_pause()
        self.playback.play_current.assert_called_once()

    def test_play_pause_toggles_while_playing_or_paused(self):
        self.controller.chapter_ready(["Câu một."], "C")
        self.controller.playback_state = "playing"
        self.controller.play_pause()
        self.controller.playback_state = "paused"
        self.controller.play_pause()
        self.assertEqual(self.playback.toggle_play.call_count, 2)

    def test_play_pause_does_nothing_once_the_chapter_is_done(self):
        self.controller.chapter_ready(["Câu một."], "C")
        self.controller.chapter_done = True
        self.controller.play_pause()
        self.playback.play_current.assert_not_called()
        self.playback.toggle_play.assert_not_called()

    def test_set_rate_persists_updates_engine_and_bumps_settings_revision(self):
        before = self.controller.settings_rev
        self.controller.set_rate(1.5)
        self.config.set.assert_called_with("defaultRate", 1.5)
        self.playback.set_rate.assert_called_with(1.5)
        self.assertEqual(self.controller.settings_rev, before + 1)

    def test_set_speaker_and_auto_next_persist(self):
        self.controller.set_speaker("Thái Sơn")
        self.config.set.assert_any_call("speaker", "Thái Sơn")
        self.controller.set_auto_next(False)
        self.config.set.assert_any_call("autoNext", False)

    def test_get_speakers_ok_and_down(self):
        self.sidecar.speakers.return_value = ["A", "B"]
        self.assertEqual(self.controller.get_speakers(), {"ok": True, "speakers": ["A", "B"]})
        self.sidecar.speakers.side_effect = RuntimeError("refused")
        self.assertEqual(self.controller.get_speakers(), {"ok": False})

    # --- Options -------------------------------------------------------------

    def test_get_init_data_returns_matching_adapter_for_known_host(self):
        data = self.controller.get_init_data("metruyenchu.co")
        self.assertEqual(data["adapter"]["hostname"], "metruyenchu.co")
        self.assertIsNone(self.controller.get_init_data("nope.test")["adapter"])

    def test_get_settings_includes_backend_model(self):
        settings = self.controller.get_settings()
        self.assertEqual(settings["sidecarUrl"], "http://localhost:8934")
        self.assertEqual(settings["backendModel"], "default")

    def test_save_settings_persists_each_field(self):
        self.controller.save_settings({
            "sidecarUrl": "http://localhost:9999", "speaker": "Adam",
            "defaultRate": 1.2, "backendModel": "v3nano",
        })
        self.config.set.assert_any_call("sidecarUrl", "http://localhost:9999")
        self.config.set.assert_any_call("speaker", "Adam")
        self.config.set.assert_any_call("defaultRate", 1.2)
        self.config.set.assert_any_call("backendModel", "v3nano")

    def test_get_and_save_adapters(self):
        self.assertEqual(self.controller.get_adapters(), list(DEFAULT_ADAPTERS))
        new = [{"hostname": "e.test", "contentSelector": "main", "stripSelectors": [],
                "nextMode": "generic", "nextValue": ""}]
        self.controller.save_adapters(new)
        self.config.set.assert_called_with("adapters", new)

    # --- PlaybackEngine notifications ---------------------------------------

    def test_chunk_index_updates_chrome_state(self):
        self.controller.on_playback_event({
            "type": "CHUNK_INDEX", "paragraphIndex": 2, "totalParagraphs": 5,
            "paragraphText": "Đoạn ba.",
        })
        self.assertEqual(self.controller.paragraph_index, 2)
        self.assertEqual(self.controller.total_paragraphs, 5)
        self.assertEqual(self.controller.paragraph_text, "Đoạn ba.")

    def test_playback_state_and_error_are_recorded(self):
        self.controller.on_playback_event({"type": "PLAYBACK_STATE", "state": "playing"})
        self.assertEqual(self.controller.playback_state, "playing")
        self.controller.on_playback_event({"type": "ERROR", "message": "Sidecar unreachable"})
        self.assertEqual(self.controller.playback_state, "paused")
        self.assertEqual(self.controller.error_message, "Sidecar unreachable")

    def test_chapter_done_auto_next_asks_the_page_to_advance(self):
        self.window.evaluate_js.return_value = True
        self.controller.on_playback_event({"type": "CHAPTER_DONE"})
        self.assertTrue(self.controller.chapter_done)
        self.assertTrue(self.controller._pending_auto_start)
        self.assertIn("__vnTtsGoNext", self.window.evaluate_js.call_args.args[0])

    def test_chapter_done_without_a_next_link_reports_end_of_novel(self):
        self.window.evaluate_js.return_value = False
        self.controller.on_playback_event({"type": "CHAPTER_DONE"})
        self.assertIn("End of novel", self.controller.status)
        self.assertFalse(self.controller._pending_auto_start)

    def test_chapter_done_is_not_advanced_twice(self):
        self.window.evaluate_js.return_value = True
        self.controller.on_playback_event({"type": "CHAPTER_DONE"})
        self.controller.on_playback_event({"type": "CHAPTER_DONE"})
        self.assertEqual(self.window.evaluate_js.call_count, 1)

    def test_chapter_done_with_auto_next_off_does_not_advance(self):
        self.config.get.side_effect = lambda key, default=None: {
            "defaultRate": 1.0, "speaker": "Minh Quân", "autoNext": False,
            "sidecarUrl": "http://localhost:8934", "backendModel": "default",
        }.get(key, default)
        self.controller.on_playback_event({"type": "CHAPTER_DONE"})
        self.window.evaluate_js.assert_not_called()

    def test_advance_chapter_reports_whether_the_page_had_a_link(self):
        self.window.evaluate_js.return_value = True
        self.assertTrue(self.controller.advance_chapter())
        self.window.evaluate_js.return_value = None
        self.assertFalse(self.controller.advance_chapter())

    # --- Start URL + showing/hiding the reader ------------------------------

    def test_start_url_comes_from_config(self):
        self.config.get.side_effect = lambda key, default=None: {
            "startUrl": "https://example.com/novel",
        }.get(key, default)
        self.assertEqual(self.controller.start_url, "https://example.com/novel")

    def test_start_url_falls_back_to_the_default_and_adds_https(self):
        self.assertEqual(self.controller.start_url, DEFAULT_START_URL)
        self.config.get.side_effect = lambda key, default=None: {
            "startUrl": "example.com/novel",
        }.get(key, default)
        self.assertEqual(self.controller.start_url, "https://example.com/novel")

    def test_settings_round_trip_includes_the_start_url(self):
        self.assertIn("startUrl", self.controller.get_settings())
        self.controller.save_settings({"startUrl": "https://example.com"})
        self.config.set.assert_any_call("startUrl", "https://example.com")

    def test_toggle_window_hides_then_shows_the_reader(self):
        self.controller.toggle_window()
        self.window.hide.assert_called_once()
        self.assertFalse(self.controller.window_visible)
        self.controller.toggle_window()
        self.window.show.assert_called_once()
        self.assertTrue(self.controller.window_visible)

    def test_toggle_window_without_a_window_is_safe(self):
        Controller(self.config, self.playback, self.sidecar).toggle_window()

    def test_a_window_created_hidden_is_reported_hidden(self):
        # main.py restores Hide page from the session by creating the window
        # hidden (ADR-0011); the chrome's first tick has to read "Show page".
        controller = Controller(self.config, self.playback, self.sidecar)
        controller.attach_content_window(self.window, hidden=True)
        self.assertFalse(controller.window_visible)

    def test_show_window_reveals_a_hidden_reader(self):
        self.controller.toggle_window()
        self.controller.show_window()
        self.window.show.assert_called_once()
        self.assertTrue(self.controller.window_visible)

    def test_show_window_leaves_a_visible_reader_alone(self):
        # Nothing to do, and nothing to raise to the front: the reader is
        # already there.
        self.controller.show_window()
        self.window.show.assert_not_called()
        self.assertTrue(self.controller.window_visible)

    def test_show_window_without_a_window_is_safe(self):
        Controller(self.config, self.playback, self.sidecar).show_window()

    def test_restore_last_page_defaults_on_and_is_in_settings(self):
        self.assertTrue(self.controller.restore_last_page)
        self.assertIn("restoreLastPage", self.controller.get_settings())

    def test_save_settings_persists_restore_last_page(self):
        self.controller.save_settings({"restoreLastPage": False})
        self.config.set.assert_any_call("restoreLastPage", False)

    # --- joining short paragraphs -------------------------------------------

    def test_short_paragraph_joining_is_off_by_default(self):
        self.assertFalse(self.controller.join_short_paragraphs)
        settings = self.controller.get_settings()
        self.assertIn("joinShortParagraphs", settings)
        self.assertIn("shortParagraphWords", settings)

    def test_short_paragraphs_are_joined_when_enabled(self):
        self.config.get.side_effect = lambda key, default=None: {
            "joinShortParagraphs": True, "shortParagraphWords": 6,
        }.get(key, default)
        self.controller.chapter_ready(["Ngắn.", "Đây là đoạn dài hơn nhiều từ."], "C")
        self.assertEqual(
            self.playback.load_chapter.call_args.args[1],
            ["Ngắn. Đây là đoạn dài hơn nhiều từ."],
        )

    def test_paragraphs_are_left_alone_when_joining_is_off(self):
        self.controller.chapter_ready(["Ngắn.", "Đoạn hai."], "C")
        self.assertEqual(
            self.playback.load_chapter.call_args.args[1],
            ["Ngắn.", "Đoạn hai."],
        )

    def test_short_paragraph_words_falls_back_on_garbage(self):
        self.config.get.side_effect = lambda key, default=None: {
            "shortParagraphWords": "many",
        }.get(key, default)
        self.assertEqual(self.controller.short_paragraph_words, DEFAULT_SHORT_PARAGRAPH_WORDS)

    def test_short_paragraph_words_is_at_least_one(self):
        self.config.get.side_effect = lambda key, default=None: {
            "shortParagraphWords": 0,
        }.get(key, default)
        self.assertEqual(self.controller.short_paragraph_words, 1)

    def test_save_settings_persists_the_joining_options(self):
        self.controller.save_settings({"joinShortParagraphs": True, "shortParagraphWords": 12})
        self.config.set.assert_any_call("joinShortParagraphs", True)
        self.config.set.assert_any_call("shortParagraphWords", 12)

    def test_returning_from_options_still_skips_the_reload_when_joining(self):
        # Joining changes the Paragraph count, which must not look like a
        # different Chapter when the reader comes back from Options.
        self.config.get.side_effect = lambda key, default=None: {
            "joinShortParagraphs": True, "shortParagraphWords": 6,
        }.get(key, default)
        self.controller.page_loaded("https://x.test/c1", "C", 2)
        self.controller.chapter_ready(["Ngắn.", "Đây là đoạn dài hơn nhiều từ."], "C")
        self.assertEqual(self.controller.total_paragraphs, 1)  # the joined count
        self.playback.reset_mock()
        self.controller.open_options("http://127.0.0.1:8935/options")
        self.controller.leave_options()
        self.controller.page_loaded("https://x.test/c1", "C", 2)
        result = self.controller.chapter_ready(["Ngắn.", "Đây là đoạn dài hơn nhiều từ."], "C")
        self.playback.load_chapter.assert_not_called()
        self.assertFalse(result["autoStart"])

    # --- visualizer styles --------------------------------------------------

    def test_visualizer_style_defaults_to_bars(self):
        self.assertEqual(self.controller.visualizer_style, "bars")

    def test_visualizer_style_falls_back_when_the_stored_value_is_unknown(self):
        self.config.get.side_effect = lambda key, default=None: {
            "visualizerStyle": "sparkles",
        }.get(key, default)
        self.assertEqual(self.controller.visualizer_style, "bars")

    def test_cycling_the_visualizer_style_wraps_forward(self):
        self.config.get.side_effect = lambda key, default=None: {
            "visualizerStyle": "blocks",
        }.get(key, default)
        self.controller.cycle_visualizer_style(1)
        self.config.set.assert_called_with("visualizerStyle", "bars")

    def test_cycling_the_visualizer_style_wraps_backward(self):
        self.controller.cycle_visualizer_style(-1)
        self.config.set.assert_called_with("visualizerStyle", "blocks")

    def test_cycling_the_visualizer_style_bumps_the_settings_revision(self):
        before = self.controller.settings_rev
        self.controller.cycle_visualizer_style(1)
        self.assertEqual(self.controller.settings_rev, before + 1)

    # --- coalescing rapid next/prev -----------------------------------------

    def test_a_skip_moves_once_the_burst_window_closes(self):
        self.controller.skip(1)
        self.playback.skip.assert_not_called()  # coalesced, not applied yet
        self.scheduler.run_pending()
        self.playback.skip.assert_called_once_with(1, steps=1)

    def test_a_burst_of_skips_becomes_one_multi_paragraph_jump(self):
        self.controller.skip(1)
        self.controller.skip(1)
        self.controller.skip(1)
        self.scheduler.run_pending()
        self.playback.skip.assert_called_once_with(1, steps=3)

    def test_bursts_accumulate_in_both_directions(self):
        self.controller.skip(-1)
        self.controller.skip(-1)
        self.controller.skip(1)
        self.scheduler.run_pending()
        self.playback.skip.assert_called_once_with(-1, steps=1)

    def test_a_burst_that_cancels_out_skips_nothing(self):
        self.controller.skip(1)
        self.controller.skip(-1)
        self.scheduler.run_pending()
        self.playback.skip.assert_not_called()

    def test_only_one_timer_is_scheduled_per_burst(self):
        self.controller.skip(1)
        self.controller.skip(-1)
        self.controller.skip(1)
        self.assertEqual(len(self.scheduler.scheduled), 1)

    def test_the_next_burst_schedules_a_fresh_timer(self):
        self.controller.skip(1)
        self.scheduler.run_pending()
        self.controller.skip(-1)
        self.assertEqual(len(self.scheduler.scheduled), 1)
        self.scheduler.run_pending()
        self.playback.skip.assert_called_with(-1, steps=1)

    def test_skip_ignores_anything_but_a_single_step(self):
        self.controller.skip(0)
        self.controller.skip(7)
        self.assertEqual(self.scheduler.scheduled, [])

    # --- the chrome's dock controls -----------------------------------------

    def test_dock_controls_delegate_to_the_dock(self):
        dock = MagicMock()
        self.controller.attach_dock(dock)
        self.controller.set_dock_height(240)
        self.controller.begin_dock_move()
        self.controller.move_dock(5, -7)
        self.controller.end_dock_move()
        dock.set_height.assert_called_once_with(240)
        dock.begin_move.assert_called_once()
        dock.move_by.assert_called_once_with(5, -7)
        dock.end_move.assert_called_once()

    def test_dock_controls_without_a_dock_are_safe(self):
        self.controller.set_dock_height(240)
        self.controller.begin_dock_move()
        self.controller.move_dock(5, -7)
        self.controller.end_dock_move()

    def test_visualizer_levels_delegate_to_the_visualizer(self):
        visualizer = MagicMock()
        visualizer.snapshot.return_value = [0.1, 0.2]
        self.controller.attach_visualizer(visualizer)
        self.assertEqual(self.controller.visualizer_levels(), [0.1, 0.2])
        visualizer.snapshot.assert_called_once()

    def test_visualizer_levels_without_a_visualizer_are_none(self):
        self.assertIsNone(self.controller.visualizer_levels())

    def test_quit_calls_the_attached_shutdown(self):
        quit_fn = MagicMock()
        self.controller.attach_quit(quit_fn)
        self.controller.quit()
        quit_fn.assert_called_once()

    def test_quit_without_a_shutdown_is_safe(self):
        self.controller.quit()

    # --- Options in the reader window ---------------------------------------

    OPTIONS_URL = "http://127.0.0.1:8935/options"

    def _read_chapter(self, url="https://x.test/c1", paragraphs=("a.", "b.", "c.")):
        self.controller.page_loaded(url, "Chapter", len(paragraphs))
        self.controller.chapter_ready(list(paragraphs), "Chapter")

    def test_open_options_loads_it_in_the_reader_window(self):
        self._read_chapter()
        self.window.load_url.reset_mock()
        self.controller.open_options(self.OPTIONS_URL)
        self.window.load_url.assert_called_once_with(self.OPTIONS_URL)

    def test_open_options_reveals_a_hidden_reader(self):
        # Options renders in the reader window, so with the reader tucked away
        # behind the strip the click used to look like it did nothing.
        self._read_chapter()
        self.controller.toggle_window()
        self.window.load_url.reset_mock()
        self.controller.open_options(self.OPTIONS_URL)
        self.window.show.assert_called_once()
        self.assertTrue(self.controller.window_visible)
        self.window.load_url.assert_called_once_with(self.OPTIONS_URL)

    def test_open_options_leaves_a_visible_reader_where_it_is(self):
        self._read_chapter()
        self.controller.open_options(self.OPTIONS_URL)
        self.window.show.assert_not_called()

    def test_leave_options_returns_to_the_remembered_page(self):
        self._read_chapter()
        self.controller.open_options(self.OPTIONS_URL)
        self.window.load_url.reset_mock()
        self.controller.leave_options()
        self.window.load_url.assert_called_once_with("https://x.test/c1")

    def test_leave_options_without_a_remembered_page_uses_history(self):
        self.controller.leave_options()
        self.window.evaluate_js.assert_called_with("history.back()")

    def test_returning_to_the_same_page_keeps_the_chapter_loaded(self):
        self._read_chapter()
        self.controller.paragraph_index = 2
        self.controller.paragraph_text = "c."
        self.playback.reset_mock()
        self.controller.open_options(self.OPTIONS_URL)
        self.controller.leave_options()
        self.controller.page_loaded("https://x.test/c1", "Chapter", 3)
        result = self.controller.chapter_ready(["a.", "b.", "c."], "Chapter")
        self.playback.load_chapter.assert_not_called()
        self.assertFalse(result["autoStart"])
        self.assertEqual(self.controller.paragraph_index, 2)
        self.assertEqual(self.controller.paragraph_text, "c.")

    def test_returning_to_a_different_page_reloads_the_chapter(self):
        self._read_chapter()
        self.playback.reset_mock()
        self.controller.open_options(self.OPTIONS_URL)
        self.controller.leave_options()
        self.controller.page_loaded("https://x.test/c2", "Other", 2)
        self.controller.chapter_ready(["x.", "y."], "Other")
        self.playback.load_chapter.assert_called_once()

    def test_returning_with_a_different_paragraph_count_reloads_the_chapter(self):
        self._read_chapter()
        self.playback.reset_mock()
        self.controller.open_options(self.OPTIONS_URL)
        self.controller.leave_options()
        self.controller.page_loaded("https://x.test/c1", "Chapter", 2)
        self.controller.chapter_ready(["a.", "b."], "Chapter")
        self.playback.load_chapter.assert_called_once()

    def test_a_fresh_page_load_still_resets_the_position(self):
        self._read_chapter()
        self.controller.paragraph_index = 2
        self.playback.reset_mock()
        self.controller.page_loaded("https://x.test/c2", "Other", 2)
        self.assertEqual(self.controller.paragraph_index, 0)
        self.controller.chapter_ready(["x.", "y."], "Other")
        self.playback.load_chapter.assert_called_once()

    def test_missing_content_window_never_raises(self):
        controller = Controller(self.config, self.playback, self.sidecar)
        controller.navigate("example.com")
        controller.go_back()
        controller.advance_chapter()
        controller.on_playback_event({"type": "CHAPTER_DONE"})

    # --- Sidecar startup status ----------------------------------------------

    def test_the_sidecar_starts_out_reported_as_starting(self):
        # main.py starts it before the chrome exists, so the chrome's first
        # tick has to see "starting" rather than a blank status line.
        self.assertTrue(self.controller.sidecar_starting)
        self.assertFalse(self.controller.sidecar_failed)

    def test_report_sidecar_ready_clears_the_starting_flag(self):
        self.controller.report_sidecar(READY)
        self.assertFalse(self.controller.sidecar_starting)
        self.assertFalse(self.controller.sidecar_failed)
        self.assertEqual(self.controller.sidecar_message, "")

    def test_report_sidecar_failure_keeps_the_message_for_the_chrome(self):
        self.controller.report_sidecar(FAILED, r"The Sidecar did not start. See C:\sidecar\sidecar.log")
        self.assertFalse(self.controller.sidecar_starting)
        self.assertTrue(self.controller.sidecar_failed)
        self.assertIn("sidecar.log", self.controller.sidecar_message)

    def test_a_retry_reports_starting_again(self):
        # Which is what hides the Retry button while the new watch runs.
        self.controller.report_sidecar(FAILED, "The Sidecar did not start.")
        self.controller.report_sidecar(STARTING)
        self.assertTrue(self.controller.sidecar_starting)
        self.assertFalse(self.controller.sidecar_failed)

    def test_recovering_clears_a_stale_sidecar_error(self):
        self.controller.report_sidecar(FAILED, "The Sidecar did not start.")
        self.controller.on_playback_event({"type": "ERROR", "message": "Sidecar unreachable: refused"})
        self.controller.report_sidecar(READY)
        self.assertFalse(self.controller.sidecar_failed)
        self.assertEqual(self.controller.error_message, "")

    def test_a_retry_clears_a_stale_sidecar_error(self):
        self.controller.on_playback_event({"type": "ERROR", "message": "Sidecar unreachable: refused"})
        self.controller.report_sidecar(STARTING)
        self.assertEqual(self.controller.error_message, "")

    def test_audio_proves_the_sidecar_is_up(self):
        # It was started by hand after the App gave up: a Chunk could only have
        # been synthesized if the Sidecar answered, so the banner is stale.
        self.controller.report_sidecar(FAILED, "The Sidecar did not start.")
        self.controller.on_playback_event({
            "type": "CHUNK_INDEX", "paragraphIndex": 0,
            "totalParagraphs": 2, "paragraphText": "a.",
        })
        self.assertFalse(self.controller.sidecar_failed)
        self.assertFalse(self.controller.sidecar_starting)
        self.assertEqual(self.controller.sidecar_message, "")

    def test_retry_sidecar_runs_the_attached_starter(self):
        calls = []
        self.controller.attach_sidecar_retry(lambda: calls.append("retry"))
        self.controller.retry_sidecar()
        self.assertEqual(calls, ["retry"])

    def test_retry_sidecar_without_a_starter_never_raises(self):
        self.controller.retry_sidecar()


if __name__ == "__main__":
    unittest.main()
