"""Tests for `app/platform_paths.py` -- the one module allowed to know which
platform the App is on (ADR-0017).

The point of these is that the *other* modules do not repeat the platform
question, so this file is where "Windows vs Linux" is actually pinned down.

Two rules, both learned the hard way:

- A test that only cares *which branch* was taken patches
  `platform_paths.is_windows` directly, because `os.name` is fixed at import
  and patching it changes how every `Path` is constructed on this host.
- A test that asserts on a real path uses `Path(...)` rather than a hardcoded
  separator, so it means the same thing on Windows and on Linux.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import platform_paths


def windows():
    return patch("platform_paths.is_windows", return_value=True)


def linux():
    return patch("platform_paths.is_windows", return_value=False)


class TestPlatform(unittest.TestCase):
    def test_it_reads_os_name(self):
        # The one unpatched assertion: on this host, is_windows() agrees with
        # os.name -- which is why a test can patch the former and not the latter.
        self.assertEqual(platform_paths.is_windows(), os.name == "nt")

    def test_windows_means_nt(self):
        with patch.object(platform_paths.os, "name", "nt"):
            self.assertTrue(platform_paths.is_windows())

    def test_linux_is_not_windows(self):
        with patch("platform_paths.is_windows", return_value=False):
            self.assertFalse(platform_paths.is_windows())


class TestVenvLayout(unittest.TestCase):
    def test_this_hosts_launcher_is_where_the_platform_says(self):
        # The one assertion that would actually have caught the old
        # hardcoded `Scripts/python.exe`: on Linux this must be bin/python.
        expected_name = "python.exe" if platform_paths.is_windows() else "python"
        expected_dir = "Scripts" if platform_paths.is_windows() else "bin"
        launcher = platform_paths.venv_python(Path("venv"))
        self.assertEqual(launcher.name, expected_name)
        self.assertEqual(launcher.parent.name, expected_dir)

    def test_the_launcher_is_inside_the_bin_directory(self):
        for venv in (Path("venv"), Path("/tmp/sidecar/venv")):
            self.assertEqual(
                platform_paths.venv_python(venv).parent,
                platform_paths.venv_bin_directory(venv),
            )

    def test_the_venv_command_is_the_same_everywhere(self):
        # Only the interpreter passed in differs, which is the point of
        # splitting this out of bootstrap/sidecar_env.
        self.assertEqual(
            platform_paths.create_venv_argv("python3", "/tmp/venv"),
            ["python3", "-m", "venv", "/tmp/venv"],
        )

    def test_the_constants_agree_with_each_other_and_with_this_host(self):
        if platform_paths.is_windows():
            self.assertEqual(platform_paths.VENV_PYTHON_NAME, "python.exe")
            self.assertEqual(platform_paths.VENV_BIN_DIRECTORY, ("Scripts",))
        else:
            self.assertEqual(platform_paths.VENV_PYTHON_NAME, "python")
            self.assertEqual(platform_paths.VENV_BIN_DIRECTORY, ("bin",))


class TestPythonOnPath(unittest.TestCase):
    def test_a_bare_python_is_used_when_it_exists(self):
        with patch("platform_paths.shutil.which",
                   side_effect=lambda name: f"/usr/bin/{name}" if name == "python" else None):
            self.assertEqual(platform_paths.python_on_path(), "/usr/bin/python")

    def test_python3_is_the_fallback_for_a_box_without_python(self):
        # The normal Debian/Ubuntu case: no `python`, and that is not broken.
        with patch("platform_paths.shutil.which",
                   side_effect=lambda name: "/usr/bin/python3" if name == "python3" else None):
            self.assertEqual(platform_paths.python_on_path(), "/usr/bin/python3")

    def test_nothing_on_path_is_none(self):
        with patch("platform_paths.shutil.which", return_value=None):
            self.assertIsNone(platform_paths.python_on_path())

    def test_the_names_tried_are_python_first(self):
        tried = []

        def which(name):
            tried.append(name)
            return None

        with patch("platform_paths.shutil.which", side_effect=which):
            platform_paths.python_on_path()
        self.assertEqual(tried, list(platform_paths.PYTHON_CANDIDATES))
        self.assertEqual(tried[0], "python")
        self.assertIn("python3", tried)


class TestDataDir(unittest.TestCase):
    def test_windows_keeps_the_original_appdata_folder(self):
        # The name predates the App; renaming it would strand existing settings.
        with windows(), patch("platform_paths.Path.home", return_value=Path("C:/Users/me")):
            self.assertEqual(
                platform_paths.data_dir(),
                Path("C:/Users/me") / "AppData" / "Roaming" / "reading-web",
            )

    def test_linux_follows_xdg_data_home(self):
        with linux(), patch.dict(os.environ, {"XDG_DATA_HOME": "/home/me/.local/share"}):
            self.assertEqual(
                platform_paths.data_dir(),
                Path("/home/me/.local/share") / "reading-web",
            )

    def test_linux_falls_back_to_local_share_when_xdg_is_unset(self):
        environment = {key: value for key, value in os.environ.items() if key != "XDG_DATA_HOME"}
        with linux(), patch.dict(os.environ, environment, clear=True), \
                patch("platform_paths.Path.home", return_value=Path("/home/me")):
            self.assertEqual(
                platform_paths.data_dir(),
                Path("/home/me") / ".local" / "share" / "reading-web",
            )

    def test_the_folder_name_is_still_overridable(self):
        with linux(), patch.dict(os.environ, {"XDG_DATA_HOME": "/data"}):
            self.assertEqual(platform_paths.data_dir("other"), Path("/data/other"))


class TestInstallHint(unittest.TestCase):
    def test_windows_points_at_python_org(self):
        with windows():
            self.assertIn("python.org", platform_paths.python_install_hint())

    def test_linux_names_the_package_to_install(self):
        with linux():
            hint = platform_paths.python_install_hint()
        self.assertIn("python3-venv", hint)  # Debian/Ubuntu
        self.assertIn("pacman", hint)        # Arch
        self.assertIn("dnf", hint)           # Fedora


class TestFrozen(unittest.TestCase):
    def test_a_frozen_build_says_so(self):
        with patch.object(platform_paths.sys, "frozen", True, create=True):
            self.assertTrue(platform_paths.frozen())
        # The attribute the patch created is gone again.
        self.assertFalse(getattr(sys, "frozen", False))


if __name__ == "__main__":
    unittest.main()
