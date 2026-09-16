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

    @patch("sidecar_manager.subprocess.Popen", side_effect=FileNotFoundError("no such file"))
    def test_start_handles_missing_python_exe_gracefully(self, mock_popen):
        mgr = SidecarManager(python_exe="nonexistent-python.exe", cwd=".", port=8934)
        mgr.start()  # must not raise
        self.assertFalse(mgr.is_running)


if __name__ == "__main__":
    unittest.main()
