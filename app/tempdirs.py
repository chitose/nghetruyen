# app/test_dir.py
"""A temporary directory a test does not have to clean up.

Every test that writes a config.json, a session.json or a sidecar log used
`tempfile.TemporaryDirectory()` and let its `cleanup()` run in `tearDown`.
That is fine on a developer machine, but a sandboxed harness can refuse to
delete those trees, and a refused delete fails the test that had already
passed its assertions -- which says nothing about the code under test.

`delete=False` keeps the directory and leaves it to the OS's temp reaper.
The assertions are unchanged, and nothing here is specific to this App.
"""
from tempfile import TemporaryDirectory


def ephemeral_dir() -> TemporaryDirectory:
    """Like `TemporaryDirectory()`, but cleanup is a no-op."""
    return TemporaryDirectory(delete=False)
