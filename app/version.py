"""The App's version, for the Controls strip.

Written once at build time -- `build.bat` and `.github/workflows/release.yml`
both run `git describe --tags --always --dirty` into `app/VERSION` right
before PyInstaller runs, and it travels into the exe the same way `web/` and
`assets/` do (see NgheTruyen.spec). A source checkout has no VERSION file (it
is gitignored, generated per build) and no interpreter-level way to guess a
tag without invoking git itself, which this deliberately does not do -- the
App reads a file, it does not shell out. `app_version` falls back to "dev" so
that absence reads as "not a build", not as an error.
"""
from pathlib import Path

VERSION_FILENAME = "VERSION"


def app_version(bundle_dir: Path) -> str:
    try:
        return (Path(bundle_dir) / VERSION_FILENAME).read_text(encoding="utf-8").strip() or "dev"
    except OSError:
        return "dev"
