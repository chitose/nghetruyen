# Nghe Truyện

A personal Windows app that reads Vietnamese web novels aloud, using a
local sidecar for text-to-speech. ("Nghe Truyện" is "listen to stories"; the
repository directory is still `reading-web`.) See [CONTEXT.md](CONTEXT.md) for terminology
and [docs/adr/](docs/adr/) for why it's built this way.

Single user, never published (Q4) -- see [ADR-0009](docs/adr/0009-standalone-app-replaces-extension.md)
for why this is a standalone app instead of a Chrome extension, and
[ADR-0008](docs/adr/0008-switch-to-vieneu-tts.md) for the current TTS engine.

## Setup

1. **Sidecar** -- see [sidecar/README.md](sidecar/README.md). Native Windows
   Python, no WSL2.
2. **App** -- see [app/README.md](app/README.md). Starts the Sidecar for you
   and opens two windows: the reader (a Web View) and the NiceGUI Controls
   window that holds the Player Bar. `run.bat` runs it from source;
   [`app/NgheTruyen.exe`](docs/adr/0012-standalone-app-exe.md) is the same App
   bundled into one standalone file (still needs `sidecar/`).
3. Open a chapter and press ▶ in the Controls window. Playback only does
   anything where extraction actually found something to read, and the
   Controls window says so when it didn't. It also has a speed slider and a
   voice picker (populated live from the Sidecar's `/speakers`); both persist
   for next time.

## Configuration

Open Options (see [app/README.md](app/README.md)): the Start URL the reader
opens on launch, the same Sidecar URL, voice, and default speed as the Player
Bar (whichever you change last wins), plus the Adapter list (content/strip/next
selectors per hostname) which only lives here.

By default the App reopens the Page you were last on, at the same window
position and dock height
([ADR-0011](docs/adr/0011-restore-session-on-launch.md)); turn "Reopen the last
page on launch" off in Options to always start at Start URL.

Two extraction paths, per [ADR-0006](docs/adr/0006-generic-extraction-fallback.md):

- **Configured Adapter** (metruyenchu.co, khotruyenchu.fun, dichtienghoa.net
  by default) -- exact selectors, reliable. Add more from the options page;
  the content selector and (for CSS-selectable next links) next selector are
  usually all a new Adapter needs -- strip selectors, text-matched next
  links, and computed next-by-URL are opt-in for sites that need them (see
  [docs/adapters.md](docs/adapters.md) for why each of the three does).
- **No Adapter for this host** -- a generic best-effort guess: largest
  link-light text block, next link found by keyword. Works passably
  anywhere; no watermark stripping, no probed next-link selector.

## What this doesn't do

By design, not by oversight -- see the ADRs for why:

- No sentence highlighting, no reader view -- just play/pause and speed.
- No audio caching -- chapters synthesize fresh each time.
- No mid-chapter resume -- the App reopens the Chapter you were last on
  (ADR-0011), but starts at its first Paragraph; press play.
- No engine fallback -- if the current engine's quality or the Sidecar breaks,
  swap the one call in `sidecar/server.py` (ADR-0003's whole point; already
  exercised once, see ADR-0008).
- No real readability library for the generic fallback -- a naive score-and-
  pick heuristic (ADR-0006). Sites read often enough to be annoying get a
  proper Adapter instead of a smarter heuristic.
