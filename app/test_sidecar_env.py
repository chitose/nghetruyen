"""Tests for sidecar_env -- where the Sidecar is, and how its venv gets built.

Everything that would run pip is mocked: a test must not install ~700 MB of
packages, and the real path is exercised once by launching the App (see
docs/adr/0016-app-provisions-the-sidecar-environment.md).
"""
import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sidecar_env
import platform_paths
from tempdirs import ephemeral_dir


def ok(*_args, **_kwargs):
    """A subprocess.run result that succeeded."""
    return MagicMock(returncode=0)


class SidecarEnvTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = ephemeral_dir()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sidecar = self.root / "sidecar"
        self.sidecar.mkdir()
        (self.sidecar / "server.py").write_text("", encoding="utf-8")
        self.requirements = self.sidecar / sidecar_env.REQUIREMENTS_NAME
        self.requirements.write_text("vieneu\n", encoding="utf-8")

    # --- helpers -------------------------------------------------------------

    def requirements_hash(self) -> str:
        return hashlib.sha256(self.requirements.read_bytes()).hexdigest()

    def make_venv(self):
        """A sidecar/venv whose launcher exists, as a real one would."""
        python = sidecar_env.venv_python(self.sidecar)
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_text("", encoding="utf-8")
        return python

    def marker(self) -> Path:
        return self.sidecar / sidecar_env.VENV_DIRNAME / sidecar_env.MARKER_NAME

    def write_marker(self, digest: str) -> None:
        self.marker().parent.mkdir(parents=True, exist_ok=True)
        self.marker().write_text(digest, encoding="utf-8")

    def call_args(self, mock_run) -> list:
        return [call.args[0] for call in mock_run.call_args_list]


class TestFindSidecarDir(SidecarEnvTestCase):
    def test_beside_the_app(self):
        app = self.root / "repo" / "app"
        (app / "sidecar").mkdir(parents=True)
        (app / "sidecar" / "server.py").write_text("", encoding="utf-8")
        self.assertEqual(sidecar_env.find_sidecar_dir(app), app / "sidecar")

    def test_one_level_up(self):
        app = self.root / "repo" / "app"
        app.mkdir(parents=True)
        self.assertEqual(sidecar_env.find_sidecar_dir(app), self.root / "repo" / "sidecar")

    def test_falls_back_when_there_is_none(self):
        app = self.root / "repo" / "app"
        app.mkdir(parents=True)
        self.root.joinpath("repo", "sidecar").mkdir()
        self.assertEqual(sidecar_env.find_sidecar_dir(app), self.root / "repo" / "sidecar")

    def test_venv_python_is_the_venvs_launcher(self):
        # bin/python on Linux, Scripts/python.exe on Windows (platform_paths).
        expected = ("Scripts", "python.exe") if platform_paths.is_windows() else ("bin", "python")
        self.assertEqual(
            sidecar_env.venv_python(self.sidecar),
            self.sidecar / "venv" / Path(*expected),
        )


class TestExtractBundledSidecar(SidecarEnvTestCase):
    def setUp(self):
        super().setUp()
        self.bundle = self.root / "bundle" / "sidecar"
        self.bundle.mkdir(parents=True)
        (self.bundle / "server.py").write_text("# bundled server\n", encoding="utf-8")
        (self.bundle / sidecar_env.REQUIREMENTS_NAME).write_text("vieneu\n", encoding="utf-8")
        self.empty = self.root / "empty_dest" / "sidecar"

    def test_copies_both_files_when_the_destination_has_neither(self):
        self.assertTrue(sidecar_env.extract_bundled_sidecar(self.bundle, self.empty))
        self.assertEqual((self.empty / "server.py").read_text(encoding="utf-8"), "# bundled server\n")
        self.assertEqual(
            (self.empty / sidecar_env.REQUIREMENTS_NAME).read_text(encoding="utf-8"), "vieneu\n",
        )

    def test_an_existing_server_py_is_left_alone(self):
        # self.sidecar already has server.py and requirements.txt (setUp).
        (self.sidecar / "server.py").write_text("# already here\n", encoding="utf-8")
        self.assertTrue(sidecar_env.extract_bundled_sidecar(self.bundle, self.sidecar))
        self.assertEqual((self.sidecar / "server.py").read_text(encoding="utf-8"), "# already here\n")

    def test_a_bundle_missing_either_file_changes_nothing_and_returns_false(self):
        (self.bundle / sidecar_env.REQUIREMENTS_NAME).unlink()
        self.assertFalse(sidecar_env.extract_bundled_sidecar(self.bundle, self.empty))
        self.assertFalse(self.empty.exists())


class TestInterpreterDiscovery(unittest.TestCase):
    def test_running_from_source_prefers_this_interpreter(self):
        # It is certainly present, unlike a Python on PATH.
        self.assertEqual(sidecar_env.find_system_python(), sys.executable)

    def test_a_frozen_exe_has_to_find_one_on_path(self):
        # Which *names* are tried is platform_paths' business now; the names
        # themselves are POSIX-shaped here on purpose, so this asserts the
        # first one that resolves is the one returned (platform_paths checks
        # `python` before `python3`).
        with patch.object(sidecar_env.platform_paths.sys, "frozen", True, create=True), \
                patch("platform_paths.shutil.which", side_effect=lambda name: rf"C:\py\{name}.exe"):
            self.assertEqual(sidecar_env.find_system_python(), r"C:\py\python.exe")

    def test_a_linux_box_with_only_python3_is_still_found(self):
        # The ordinary Debian case: no `python` at all, and that is not a
        # broken install.
        with patch.object(sidecar_env.platform_paths.sys, "frozen", True, create=True), \
                patch("platform_paths.shutil.which",
                      side_effect=lambda name: "/usr/bin/python3" if name == "python3" else None):
            self.assertEqual(sidecar_env.find_system_python(), "/usr/bin/python3")

    def test_no_python_on_path_is_reported_as_none(self):
        with patch.object(sidecar_env.platform_paths.sys, "frozen", True, create=True), \
                patch("platform_paths.shutil.which", return_value=None):
            self.assertIsNone(sidecar_env.find_system_python())

    def test_running_from_source_needs_no_python_on_path(self):
        # ...because this process's own interpreter is used.
        with patch("platform_paths.shutil.which", return_value=None):
            self.assertEqual(sidecar_env.find_system_python(), sys.executable)

    @patch("sidecar_env.subprocess.run", side_effect=ok)
    def test_a_working_interpreter_is_usable(self, mock_run):
        self.assertTrue(sidecar_env.usable_python("python"))
        self.assertIn("-c", mock_run.call_args.args[0])  # the version probe

    @patch("sidecar_env.subprocess.run", return_value=MagicMock(returncode=1))
    def test_the_store_stub_or_an_old_python_is_not(self, _mock_run):
        # Windows' Store alias exits non-zero instead of running anything.
        self.assertFalse(sidecar_env.usable_python("python"))

    @patch("sidecar_env.subprocess.run", side_effect=OSError("no such file"))
    def test_an_interpreter_that_cannot_run_is_not_usable(self, _mock_run):
        self.assertFalse(sidecar_env.usable_python("nope.exe"))


class TestModelCache(SidecarEnvTestCase):
    def test_an_empty_cache_means_the_model_still_has_to_come_down(self):
        cache = self.root / "hub"
        with patch.object(sidecar_env, "MODEL_CACHE_DIR", cache):
            self.assertFalse(sidecar_env.model_cache_present())  # missing
            cache.mkdir()
            self.assertFalse(sidecar_env.model_cache_present())  # empty
            (cache / "models--pnnbao97--VieNeu-TTS").mkdir()
            self.assertTrue(sidecar_env.model_cache_present())


class TestEnsureEnv(SidecarEnvTestCase):
    @patch("sidecar_env.usable_python", return_value=True)
    @patch("sidecar_env.subprocess.run", side_effect=ok)
    def test_a_current_venv_is_left_alone(self, mock_run, _mock_usable):
        self.make_venv()
        self.write_marker(self.requirements_hash())
        self.assertEqual(sidecar_env.ensure_env(self.sidecar, python_exe="python"), (True, "", False))
        mock_run.assert_not_called()

    def test_a_missing_venv_is_created_then_installed(self):
        def emulated_run(argv, **_kwargs):
            if "venv" in argv:  # `python -m venv` is what creates the launcher
                self.make_venv()
            return ok()

        with patch("sidecar_env.subprocess.run", side_effect=emulated_run) as mock_run:
            result = sidecar_env.ensure_env(self.sidecar, python_exe="python")
        self.assertEqual(result, (True, "", True))
        calls = self.call_args(mock_run)
        self.assertIn("venv", calls[1])  # probe, then venv, then pip
        self.assertIn("pip", calls[2])
        self.assertEqual(calls[2][-1], str(self.requirements))
        self.assertEqual(self.marker().read_text(encoding="utf-8"), self.requirements_hash())

    @patch("sidecar_env.subprocess.run", side_effect=ok)
    def test_a_venv_made_by_hand_is_installed_into(self, mock_run):
        # Someone followed sidecar/README.md: no marker, so requirements.txt is
        # treated as unverified and pip runs (idempotent), which also writes it.
        self.make_venv()
        self.assertEqual(sidecar_env.ensure_env(self.sidecar, python_exe="python"), (True, "", True))
        calls = self.call_args(mock_run)
        self.assertEqual(len(calls), 2)  # probe + pip; nothing to create
        self.assertIn("pip", calls[1])
        self.assertTrue(self.marker().is_file())

    @patch("sidecar_env.subprocess.run", side_effect=ok)
    def test_changed_requirements_reinstall(self, mock_run):
        self.make_venv()
        self.write_marker("stale")
        self.assertEqual(sidecar_env.ensure_env(self.sidecar, python_exe="python"), (True, "", True))
        self.assertIn("pip", self.call_args(mock_run)[1])
        self.assertEqual(self.marker().read_text(encoding="utf-8"), self.requirements_hash())

    @patch("sidecar_env.subprocess.run", side_effect=[ok(), MagicMock(returncode=1)])
    def test_a_failed_install_reports_and_leaves_no_marker(self, _mock_run):
        self.make_venv()  # so only the install runs, not venv creation
        ok_result, reason, provisioned = sidecar_env.ensure_env(self.sidecar, python_exe="python")
        self.assertFalse(ok_result)
        self.assertIn("Installing the Sidecar's packages failed", reason)
        self.assertFalse(provisioned)
        self.assertFalse(self.marker().exists())  # so the next launch tries again

    @patch("sidecar_env.subprocess.run", side_effect=[ok(), MagicMock(returncode=2)])
    def test_a_failed_venv_creation_reports_before_installing(self, mock_run):
        ok_result, reason, _provisioned = sidecar_env.ensure_env(self.sidecar, python_exe="python")
        self.assertFalse(ok_result)
        self.assertIn("Creating sidecar/venv failed", reason)
        self.assertEqual(len(mock_run.call_args_list), 2)  # probe + venv; no pip

    @patch("sidecar_env.subprocess.run", return_value=MagicMock(returncode=1))
    def test_an_unusable_interpreter_is_reported_before_anything_is_created(self, mock_run):
        ok_result, reason, _provisioned = sidecar_env.ensure_env(self.sidecar, python_exe="stub.exe")
        self.assertFalse(ok_result)
        self.assertIn(sidecar_env.MIN_PYTHON_NOTE, reason)
        self.assertEqual(len(mock_run.call_args_list), 1)  # the probe only
        self.assertFalse((self.sidecar / sidecar_env.VENV_DIRNAME).exists())

    @patch("sidecar_env.find_system_python", return_value=None)
    @patch("sidecar_env.subprocess.run", side_effect=ok)
    def test_no_python_at_all_is_reported_without_running_anything(self, mock_run, _mock_find):
        ok_result, reason, _provisioned = sidecar_env.ensure_env(self.sidecar)
        self.assertFalse(ok_result)
        self.assertIn(sidecar_env.MIN_PYTHON_NOTE, reason)
        mock_run.assert_not_called()

    @patch("sidecar_env.usable_python", return_value=True)
    @patch("sidecar_env.subprocess.run", side_effect=ok)
    def test_a_missing_requirements_file_is_reported(self, mock_run, _mock_usable):
        self.requirements.unlink()
        ok_result, reason, _provisioned = sidecar_env.ensure_env(self.sidecar, python_exe="python")
        self.assertFalse(ok_result)
        self.assertIn("sidecar/requirements.txt", reason)
        mock_run.assert_not_called()

    @patch("sidecar_env.usable_python", return_value=True)
    @patch("sidecar_env.subprocess.run", side_effect=ok)
    def test_a_missing_sidecar_folder_is_reported(self, mock_run, _mock_usable):
        ok_result, reason, _provisioned = sidecar_env.ensure_env(self.sidecar / "gone", python_exe="python")
        self.assertFalse(ok_result)
        self.assertIn("sidecar/requirements.txt", reason)
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
