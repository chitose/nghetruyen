<!--
Prepended to every release's generated notes by .github/workflows/release.yml
(gh release create --notes-file). Keep it to what someone reading the release
page needs in order to run the exe; it is the same for every version, so
per-version notes belong in the commits.
-->
`NgheTruyen.exe` is the whole App -- the reader Web View, the NiceGUI Controls
window, and playback -- in one file. Copy it anywhere and double-click: it needs
no Python install and no checkout.

**It still needs the Sidecar**, which is not bundled (ADR-0012): `sidecar/` with
its venv and the ~1.3 GB VieNeu voice model, which it downloads on first use.
Put `sidecar/` beside the exe or one level up -- `sidecar/README.md` covers the
rest -- and the App starts it on launch. A Sidecar already answering on port 8934
-- including the Docker image -- is used as it is, and left running when the App
closes.

The exe is unsigned, so Windows SmartScreen warns the first time; "More info" ->
"Run anyway". Startup reports what the Sidecar is doing on the Controls strip's
status line, with a Retry button if it never comes up; its output -- and any
startup error -- is in `sidecar/sidecar.log`, since it runs without a console.
