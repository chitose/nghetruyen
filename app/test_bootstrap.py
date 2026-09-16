"""Tests for the self-bootstrapping launcher (app/bootstrap.py), which
creates app/venv, installs/refreshes requirements.txt, then hands off to
main.py -- so a compiled .exe wrapper (or run.bat) can be a single
double-click/command.
"""
import unittest
from unittest.mock import patch

import bootstrap


class TestBootstrap(unittest.TestCase):
    @patch("bootstrap._requirements_hash", return_value="same")
    @patch("bootstrap._installed_requirements_hash", return_value="same")
    @patch("bootstrap.VENV_PYTHON")
    @patch("bootstrap.subprocess.run")
    def test_skips_setup_when_venv_and_requirements_are_current(
        self, mock_run, mock_venv_python, mock_installed, mock_hash,
    ):
        mock_venv_python.exists.return_value = True
        bootstrap.bootstrap()
        mock_run.assert_called_once()
        self.assertEqual(mock_run.call_args[0][0], [str(mock_venv_python), "main.py"])

    @patch("bootstrap._requirements_hash", return_value="new")
    @patch("bootstrap._installed_requirements_hash", return_value="old")
    @patch("bootstrap.REQUIREMENTS_MARKER")
    @patch("bootstrap.VENV_PYTHON")
    @patch("bootstrap.subprocess.run")
    def test_installs_requirements_when_they_changed(
        self, mock_run, mock_venv_python, mock_marker, mock_installed, mock_hash,
    ):
        mock_venv_python.exists.return_value = True
        bootstrap.bootstrap()
        self.assertEqual(mock_run.call_count, 2)
        pip_call, run_call = mock_run.call_args_list
        self.assertIn("pip", pip_call[0][0])
        self.assertEqual(run_call[0][0], [str(mock_venv_python), "main.py"])

    @patch("bootstrap.shutil.which", return_value=r"C:\Python\python.exe")
    @patch("bootstrap._requirements_hash", return_value="new")
    @patch("bootstrap._installed_requirements_hash", return_value=None)
    @patch("bootstrap.REQUIREMENTS_MARKER")
    @patch("bootstrap.VENV_PYTHON")
    @patch("bootstrap.subprocess.run")
    def test_creates_venv_and_installs_requirements_when_missing(
        self, mock_run, mock_venv_python, mock_marker, mock_installed, mock_hash, mock_which,
    ):
        mock_venv_python.exists.return_value = False
        bootstrap.bootstrap()
        self.assertEqual(mock_run.call_count, 3)
        venv_call, pip_call, run_call = mock_run.call_args_list
        self.assertIn("venv", venv_call[0][0])
        self.assertIn("pip", pip_call[0][0])
        self.assertEqual(run_call[0][0], [str(mock_venv_python), "main.py"])

    @patch("bootstrap.shutil.which", return_value=None)
    @patch("bootstrap.VENV_PYTHON")
    @patch("bootstrap.subprocess.run")
    def test_exits_cleanly_when_system_python_not_found(self, mock_run, mock_venv_python, mock_which):
        mock_venv_python.exists.return_value = False
        with patch("builtins.input", return_value=""), patch("bootstrap.sys.exit", side_effect=SystemExit) as mock_exit:
            with self.assertRaises(SystemExit):
                bootstrap.bootstrap()
        mock_exit.assert_called_once_with(1)
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
