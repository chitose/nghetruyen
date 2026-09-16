import os
import subprocess
import sys
import unittest
import urllib.error
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from sidecar_manager import SidecarManager


class TestSidecarManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
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


if __name__ == "__main__":
    unittest.main()
