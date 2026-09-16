"""Tests for the self-bootstrapping launcher (app/bootstrap.py), which
creates app/venv and installs requirements.txt on first run so a compiled
.exe wrapper (or run.bat) can be a single double-click/command.
"""
import unittest
from unittest.mock import patch, MagicMock

import bootstrap


class TestBootstrap(unittest.TestCase):
    @patch("bootstrap.subprocess.run")
    @patch("bootstrap.VENV_PYTHON")
    def test_skips_setup_when_venv_already_exists(self, mock_venv_python, mock_run):
        mock_venv_python.exists.return_value = True
        bootstrap.bootstrap()
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        self.assertEqual(args, [str(mock_venv_python), "main.py"])

    @patch("bootstrap.shutil.which", return_value=r"C:\Python\python.exe")
    @patch("bootstrap.subprocess.run")
    @patch("bootstrap.VENV_PYTHON")
    def test_creates_venv_and_installs_requirements_when_missing(self, mock_venv_python, mock_run, mock_which):
        mock_venv_python.exists.return_value = False
        bootstrap.bootstrap()
        self.assertEqual(mock_run.call_count, 3)
        venv_call, pip_call, run_call = mock_run.call_args_list
        self.assertIn("venv", venv_call[0][0])
        self.assertIn("pip", pip_call[0][0])
        self.assertEqual(run_call[0][0], [str(mock_venv_python), "main.py"])

    @patch("bootstrap.shutil.which", return_value=None)
    @patch("bootstrap.subprocess.run")
    @patch("bootstrap.VENV_PYTHON")
    def test_exits_cleanly_when_system_python_not_found(self, mock_venv_python, mock_run, mock_which):
        mock_venv_python.exists.return_value = False
        with patch("builtins.input", return_value=""), patch("bootstrap.sys.exit", side_effect=SystemExit) as mock_exit:
            with self.assertRaises(SystemExit):
                bootstrap.bootstrap()
        mock_exit.assert_called_once_with(1)
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
