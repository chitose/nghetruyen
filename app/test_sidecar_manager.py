import os
import subprocess
import sys
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from sidecar_manager import (
    DEFAULT_HEALTH_TIMEOUT,
    FAILED,
    FIRST_RUN_TIMEOUT,
    MODEL_MESSAGE,
    PREPARING,
    READY,
    SETUP_MESSAGE,
    STARTING,
    SidecarManager,
    SidecarStartup,
)
from tempdirs import ephemeral_dir


class FakeManager:
    """Stands in for SidecarManager: liveness, health, and provisioning are
    scripted, and the wait can flip them mid-flight the way a real one changes
    state."""

    def __init__(self, healthy=False, running=True, using_existing=False,
                 on_wait=None, prepare_result=(True, "", False)):
        self.log_path = r"C:\sidecar\sidecar.log"
        self.healthy = healthy
        self.running = running
        self.using_existing = using_existing
        self.on_wait = on_wait
        self.prepare_result = prepare_result
        self.calls = []
        self.ensure_calls = []
        self.waits = 0
        self.wait_timeouts = []

    def is_healthy(self):
        return self.healthy

    def prepare(self):
        self.calls.append("prepare")
        return self.prepare_result

    def ensure_running(self, backend_model="default"):
        self.calls.append("ensure_running")
        self.ensure_calls.append(backend_model)

    @property
    def is_running(self):
        return self.running

    def wait_healthy(self, timeout=None):
        self.calls.append("wait_healthy")
        self.waits += 1
        self.wait_timeouts.append(timeout)
        if self.on_wait is not None:
            self.on_wait(self)
        return self.healthy


class TestSidecarManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = ephemeral_dir()
        self.log_path = os.path.join(self.tmpdir.name, "sidecar.log")
        self._managers = []
        # Nothing is listening unless a test says otherwise, so start() spawns.
        urlopen = patch("sidecar_manager.urllib.request.urlopen",
                        side_effect=urllib.error.URLError("refused"))
        self.addCleanup(urlopen.stop)
        urlopen.start()

    def tearDown(self):
        for mgr in self._managers:
            mgr._close_log()  # Windows won't delete a temp dir with an open file
        self.tmpdir.cleanup()

    def manager(self, **kwargs):
        kwargs.setdefault("python_exe", "python")
        kwargs.setdefault("cwd", ".")
        kwargs.setdefault("port", 8934)
        kwargs.setdefault("log_path", self.log_path)
        mgr = SidecarManager(**kwargs)
        self._managers.append(mgr)
        return mgr

    @patch("sidecar_manager.subprocess.Popen")
    def test_start_spawns_uvicorn_with_expected_args(self, mock_popen):
        mgr = self.manager(python_exe=r"C:\venv\Scripts\python.exe", cwd=r"C:\sidecar")
        mgr.start()
        args, kwargs = mock_popen.call_args
        self.assertEqual(
            args[0],
            [r"C:\venv\Scripts\python.exe", "-m", "uvicorn", "server:app", "--port", "8934"],
        )
        self.assertEqual(kwargs["cwd"], r"C:\sidecar")
        self.assertNotIn("TTS_BACKEND_MODEL", kwargs["env"])

    @patch("sidecar_manager.subprocess.Popen")
    def test_start_passes_backend_model_as_env_var(self, mock_popen):
        mgr = self.manager()
        mgr.start(backend_model="v3nano")
        self.assertEqual(mock_popen.call_args.kwargs["env"]["TTS_BACKEND_MODEL"], "v3nano")

    @patch("sidecar_manager.subprocess.Popen")
    def test_start_is_idempotent(self, mock_popen):
        mgr = self.manager()
        mgr.start()
        mgr.start()
        self.assertEqual(mock_popen.call_count, 1)

    @patch("sidecar_manager.subprocess.Popen")
    def test_start_uses_an_already_running_sidecar_instead_of_spawning(self, mock_popen):
        with patch.object(SidecarManager, "is_healthy", return_value=True):
            messages = []
            mgr = self.manager(on_warning=messages.append)
            mgr.start()
        mock_popen.assert_not_called()
        self.assertTrue(mgr.using_existing)
        self.assertEqual(len(messages), 1)
        self.assertIn("already running", messages[0])

    @patch("sidecar_manager.subprocess.Popen")
    def test_stop_leaves_an_existing_sidecar_alone(self, mock_popen):
        with patch.object(SidecarManager, "is_healthy", return_value=True):
            mgr = self.manager()
            mgr.start()
        mgr.stop()  # the App did not start that Sidecar, so it must not stop it
        mock_popen.assert_not_called()
        self.assertFalse(mgr.is_running)

    @patch("sidecar_manager.subprocess.Popen")
    def test_start_spawns_when_nothing_is_listening(self, mock_popen):
        with patch.object(SidecarManager, "is_healthy", return_value=False):
            mgr = self.manager()
            mgr.start()
        mock_popen.assert_called_once()
        self.assertFalse(mgr.using_existing)

    @patch("sidecar_manager.subprocess.Popen")
    def test_ensure_running_spawns_when_nothing_was_started(self, mock_popen):
        with patch.object(SidecarManager, "is_healthy", return_value=False):
            mgr = self.manager()
            mgr.ensure_running()
        mock_popen.assert_called_once()

    @patch("sidecar_manager.subprocess.Popen")
    def test_ensure_running_leaves_a_live_sidecar_alone(self, mock_popen):
        # Retry after a health timeout: the process is alive, which usually
        # means it is still loading its model -- waiting again beats throwing
        # that work away and starting over.
        live = MagicMock()
        live.poll.return_value = None
        mock_popen.return_value = live
        with patch.object(SidecarManager, "is_healthy", return_value=False):
            mgr = self.manager()
            mgr.ensure_running()
            mgr.ensure_running(backend_model="v3nano")
        mock_popen.assert_called_once()
        live.terminate.assert_not_called()

    @patch("sidecar_manager.subprocess.Popen")
    def test_ensure_running_respawns_a_sidecar_that_died(self, mock_popen):
        dead, live = MagicMock(), MagicMock()
        dead.poll.return_value = 1  # exited between the spawn and the Retry
        live.poll.return_value = None
        mock_popen.side_effect = [dead, live]
        with patch.object(SidecarManager, "is_healthy", return_value=False):
            mgr = self.manager()
            mgr.ensure_running()
            mgr.ensure_running()
        self.assertEqual(mock_popen.call_count, 2)
        dead.terminate.assert_called_once()  # the dead handle is cleaned up

    @patch("sidecar_manager.subprocess.Popen")
    def test_ensure_running_leaves_an_existing_sidecar_alone(self, mock_popen):
        with patch.object(SidecarManager, "is_healthy", return_value=True):
            mgr = self.manager()
            mgr.ensure_running()
            mgr.ensure_running()
        mock_popen.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "Windows-only creation flag")
    @patch("sidecar_manager.subprocess.Popen")
    def test_start_hides_the_sidecar_console_window(self, mock_popen):
        mgr = self.manager()
        mgr.start()
        self.assertEqual(
            mock_popen.call_args.kwargs["creationflags"],
            subprocess.CREATE_NO_WINDOW,
        )

    @patch("sidecar_manager.subprocess.Popen")
    def test_start_sends_sidecar_output_to_the_log(self, mock_popen):
        mgr = self.manager()
        mgr.start()
        kwargs = mock_popen.call_args.kwargs
        self.assertIsNot(kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], subprocess.STDOUT)
        with open(self.log_path, encoding="utf-8") as handle:
            self.assertIn("Sidecar started", handle.read())

    @patch("sidecar_manager.subprocess.Popen")
    def test_start_discards_output_when_the_log_cannot_be_opened(self, mock_popen):
        mgr = self.manager(log_path=os.path.join(self.tmpdir.name, "missing", "sidecar.log"))
        mgr.start()
        self.assertIs(mock_popen.call_args.kwargs["stdout"], subprocess.DEVNULL)

    @patch("sidecar_manager.urllib.request.urlopen")
    @patch("sidecar_manager.subprocess.Popen")
    def test_wait_healthy_returns_true_once_reachable(self, mock_popen, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value = MagicMock()
        mgr = self.manager()
        mgr.start()
        self.assertTrue(mgr.wait_healthy(timeout=1.0, interval=0.01))

    @patch("sidecar_manager.time.monotonic")
    @patch("sidecar_manager.urllib.request.urlopen", side_effect=urllib.error.URLError("refused"))
    @patch("sidecar_manager.subprocess.Popen")
    def test_wait_healthy_times_out_if_never_reachable(self, mock_popen, mock_urlopen, mock_monotonic):
        # Two calls per loop iteration (deadline check + nothing else); advance
        # past the timeout on the second read so the loop exits after one try.
        mock_monotonic.side_effect = [0.0, 0.0, 10.0]
        mgr = self.manager()
        mgr.start()
        self.assertFalse(mgr.wait_healthy(timeout=1.0, interval=0.0))

    @patch("sidecar_manager.subprocess.Popen")
    def test_stop_terminates_and_clears_process(self, mock_popen):
        fake_proc = MagicMock()
        fake_proc.wait.return_value = 0
        mock_popen.return_value = fake_proc
        mgr = self.manager()
        mgr.start()
        mgr.stop()
        fake_proc.terminate.assert_called_once()
        self.assertFalse(mgr.is_running)
        self.assertIsNone(mgr._log_file)  # the log handle is released too

    @patch("sidecar_manager.subprocess.Popen")
    def test_stop_before_start_is_a_noop(self, mock_popen):
        mgr = self.manager()
        mgr.stop()  # must not raise
        mock_popen.assert_not_called()

    @patch("sidecar_manager.subprocess.Popen", side_effect=FileNotFoundError("no such file"))
    def test_start_handles_missing_python_exe_gracefully(self, mock_popen):
        mgr = self.manager(python_exe="nonexistent-python.exe")
        mgr.start()  # must not raise
        self.assertFalse(mgr.is_running)
        self.assertIsNone(mgr._log_file)

    @patch("sidecar_manager.subprocess.Popen", side_effect=FileNotFoundError("no such file"))
    def test_start_reports_failure_through_the_warning_callback(self, mock_popen):
        warnings = []
        mgr = self.manager(python_exe="nonexistent-python.exe", on_warning=warnings.append)
        mgr.start()
        self.assertEqual(len(warnings), 1)
        self.assertIn("failed to start the Sidecar", warnings[0])


class TestSidecarStartup(unittest.TestCase):
    """The status main.py's startup thread reports to the chrome, which used to
    be silence plus a line in sidecar.log."""

    def setUp(self):
        self.statuses = []
        self.warnings = []

    def startup(self, manager, spawn=None, cache_present=None,
                timeout=DEFAULT_HEALTH_TIMEOUT, first_run_timeout=FIRST_RUN_TIMEOUT):
        return SidecarStartup(
            manager,
            on_status=lambda state, message: self.statuses.append((state, message)),
            on_warning=self.warnings.append,
            # No real thread: a test runs the watch inline and sees the result.
            spawn=spawn or (lambda watch: watch()),
            timeout=timeout,
            first_run_timeout=first_run_timeout,
            # Scripted: the real check reads this machine's Hugging Face cache,
            # and it only decides how long a wait may last.
            cache_present=cache_present or (lambda: True),
        )

    def test_reports_starting_then_ready(self):
        manager = FakeManager(healthy=True)
        self.startup(manager).start(backend_model="v3nano")
        self.assertEqual(self.statuses, [(STARTING, ""), (READY, "")])
        self.assertEqual(manager.ensure_calls, ["v3nano"])
        self.assertEqual(self.warnings, [])

    def test_reports_failure_when_the_sidecar_cannot_be_spawned(self):
        manager = FakeManager(running=False)  # no sidecar/venv, or a bad path
        self.startup(manager).start()
        self.assertEqual(self.statuses[0], (STARTING, ""))
        state, message = self.statuses[-1]
        self.assertEqual(state, FAILED)
        self.assertIn("did not start", message)
        self.assertIn(manager.log_path, message)  # where to look next
        self.assertEqual(manager.waits, 0)  # no point waiting a minute first
        self.assertEqual(len(self.warnings), 1)
        self.assertIn(manager.log_path, self.warnings[0])

    def test_a_sidecar_still_loading_is_reported_as_still_starting(self):
        # A first run downloads the voice model, so a timeout is not death.
        manager = FakeManager(healthy=False, running=True)
        self.startup(manager).start()
        self.assertEqual(self.statuses[-1][0], FAILED)
        self.assertIn("still starting", self.statuses[-1][1])

    def test_a_sidecar_that_dies_during_the_wait_says_so(self):
        def die(_manager):
            _manager.running = False

        manager = FakeManager(healthy=False, running=True, on_wait=die)
        self.startup(manager).start()
        self.assertEqual(self.statuses[-1][0], FAILED)
        self.assertIn("stopped before it was ready", self.statuses[-1][1])

    def test_an_existing_sidecar_is_waited_for(self):
        # Started by hand, or the Docker image: nothing of ours to watch, but
        # something to wait for rather than a failure.
        manager = FakeManager(healthy=True, running=False, using_existing=True)
        self.startup(manager).start()
        self.assertEqual(self.statuses[-1], (READY, ""))

    def test_a_retry_while_a_watch_is_in_flight_is_ignored(self):
        watchers = []
        startup = self.startup(FakeManager(healthy=True), spawn=watchers.append)
        startup.start()
        startup.start()  # Retry clicked again before the first watch finished
        self.assertEqual(len(watchers), 1)

    def test_start_again_after_a_failure_watches_again(self):
        watchers = []
        manager = FakeManager(running=False)  # first attempt cannot spawn
        startup = self.startup(manager, spawn=watchers.append)
        startup.start()
        watchers.pop()()  # run the first watch inline; it reports the failure
        self.assertEqual(self.statuses[-1][0], FAILED)
        manager.running = True  # the reader fixed sidecar/venv, then hit Retry
        manager.healthy = True
        startup.start()
        self.assertEqual(len(watchers), 1)  # the guard was released
        watchers.pop()()
        self.assertEqual(self.statuses[-1], (READY, ""))

    def test_quitting_cancels_a_retry_that_has_not_spawned_yet(self):
        # Otherwise the App could exit just after a Retry spawned a Sidecar
        # that nothing will ever stop, and it would hold the port.
        watchers = []
        manager = FakeManager(healthy=True)
        startup = self.startup(manager, spawn=watchers.append)
        startup.start()
        startup.stop()
        watchers.pop()()  # the watch runs, but the App is already going away
        self.assertEqual(manager.ensure_calls, [])
        self.assertEqual(self.statuses, [(STARTING, "")])
        startup.start()  # and Retry cannot start another one either
        self.assertEqual(len(watchers), 0)

    # --- provisioning sidecar/venv (ADR-0016) -------------------------------

    def test_an_already_answering_sidecar_needs_no_environment(self):
        # Started by hand, or the Docker image: building a venv beside it would
        # be minutes of work for nothing.
        manager = FakeManager(healthy=True, using_existing=True)
        self.startup(manager).start()
        self.assertEqual(manager.calls, ["ensure_running", "wait_healthy"])
        self.assertNotIn(PREPARING, [state for state, _ in self.statuses])

    def test_the_environment_is_built_before_the_spawn(self):
        manager = FakeManager(healthy=False, prepare_result=(True, "", True))
        self.startup(manager).start()
        self.assertEqual(manager.calls[0], "prepare")
        self.assertEqual(manager.calls[1], "ensure_running")
        self.assertEqual(
            self.statuses[1], (PREPARING, SETUP_MESSAGE),
        )

    def test_a_failed_setup_names_the_readme_instead_of_a_log(self):
        reason = "Python 3.10 or newer was not found on PATH, so the Sidecar's environment cannot be created."
        manager = FakeManager(healthy=False, prepare_result=(False, reason, False))
        self.startup(manager).start()
        state, message = self.statuses[-1]
        self.assertEqual(state, FAILED)
        self.assertIn(reason, message)
        self.assertIn("sidecar/README.md", message)
        self.assertNotIn(manager.log_path, message)  # nothing was spawned, so no log
        self.assertEqual(manager.ensure_calls, [])  # no point spawning without a venv
        self.assertEqual(manager.waits, 0)
        self.assertIn("sidecar/README.md", self.warnings[0])

    def test_a_fresh_install_waits_for_the_model_download(self):
        # The venv just got built, so the model certainly is not cached yet --
        # a 60s timeout would report a normal first run as a failure.
        manager = FakeManager(healthy=False, prepare_result=(True, "", True))
        self.startup(manager, timeout=60.0, first_run_timeout=900.0).start()
        self.assertIn((PREPARING, MODEL_MESSAGE), self.statuses)
        self.assertEqual(manager.wait_timeouts, [900.0])

    def test_an_empty_model_cache_also_counts_as_a_first_run(self):
        manager = FakeManager(healthy=True, prepare_result=(True, "", False))
        self.startup(manager, cache_present=lambda: False).start()
        self.assertIn((PREPARING, MODEL_MESSAGE), self.statuses)
        self.assertEqual(manager.wait_timeouts, [900.0])

    def test_a_warm_cache_with_a_ready_venv_uses_the_normal_timeout(self):
        manager = FakeManager(healthy=False, prepare_result=(True, "", False))
        self.startup(manager, timeout=60.0).start()
        self.assertNotIn(MODEL_MESSAGE, [message for _, message in self.statuses])
        self.assertEqual(manager.wait_timeouts, [60.0])


if __name__ == "__main__":
    unittest.main()
