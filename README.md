# NgheTruyen

A personal Windows app that reads Vietnamese web novels aloud, using a
local sidecar for text-to-speech. See [CONTEXT.md](CONTEXT.md) for terminology
and [docs/adr/](docs/adr/) for why it's built this way.

Single user, never published (Q4) -- see [ADR-0009](docs/adr/0009-standalone-app-replaces-extension.md)
for why this is a standalone app instead of a Chrome extension, and
[ADR-0008](docs/adr/0008-switch-to-vieneu-tts.md) for the current TTS engine.

## Setup

1. **Sidecar** -- see [sidecar/README.md](sidecar/README.md). Native Windows
   Python, no WSL2.
2. **App** -- see [app/README.md](app/README.md). Starts the Sidecar for you
   and opens a window with the reader's Player Bar built in.
3. Open a chapter and click ▶ on the bar in the bottom-right corner. The bar
   only appears where extraction actually found something to read. It also
   has a speed slider and a voice picker (populated live from the Sidecar's
   `/speakers`); both persist for next time.

## Configuration

Open Options (see [app/README.md](app/README.md)): same Sidecar URL, voice, and
default speed as the Player Bar (whichever you change last wins), plus the
Adapter list (content/strip/next selectors per hostname) which only lives here.

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
- No mid-chapter resume -- reopen the chapter and press play.
- No engine fallback -- if the current engine's quality or the Sidecar breaks,
  swap the one call in `sidecar/server.py` (ADR-0003's whole point; already
  exercised once, see ADR-0008).
- No real readability library for the generic fallback -- a naive score-and-
  pick heuristic (ADR-0006). Sites read often enough to be annoying get a
  proper Adapter instead of a smarter heuristic.
