# Nghe Truyện

A personal app that reads Vietnamese web novels aloud, using a
local sidecar for text-to-speech. ("Nghe Truyện" is "listen to stories".) See
[CONTEXT.md](CONTEXT.md) for terminology and [docs/adr/](docs/adr/) for why
it's built this way.

Single user, never published (Q4) -- see [ADR-0009](docs/adr/0009-standalone-app-replaces-extension.md)
for why this is a standalone app instead of a Chrome extension,
[ADR-0008](docs/adr/0008-switch-to-vieneu-tts.md) for the current TTS engine,
and [ADR-0017](docs/adr/0017-linux-launcher.md) for how it runs on Windows and
Linux.

## Setup

1. **Sidecar** -- nothing to do: the App creates `sidecar/venv` and installs
   its requirements on first launch, saying so on the Controls strip's status
   line ([ADR-0016](docs/adr/0016-app-provisions-the-sidecar-environment.md)).
   Native Python, no WSL2; you can still run it by hand instead
   ([sidecar/README.md](sidecar/README.md)).
2. **App** -- see [app/README.md](app/README.md). On Windows that is
   `run.bat`; on Linux it is [`run.sh`](run.sh), or
   [`dist/linux/install.sh`](dist/linux/install.sh) to also get an entry in the
   desktop's application list. Either way it starts the Sidecar for you
   (a small startup window covers the launch, then the Controls strip's status
   line reports how it goes, with a Retry button if it doesn't) and opens two
   windows: the reader (a Web View) and the Controls window that holds the
   Player Bar -- the strip is the reader's tool window, so Windows shows them
   as one: a single taskbar button and a single Alt-Tab entry. (On a Wayland
   session the shell has no way to be asked that, so there the two are listed
   separately -- [ADR-0017](docs/adr/0017-linux-launcher.md).)
   `run.bat`/`run.sh` run it from source;
   [`app/NgheTruyen.exe`](docs/adr/0012-standalone-app-exe.md) is the same App
   bundled into one standalone Windows file (still needs `sidecar/`), which
   pushing a `v*` tag builds and publishes as a GitHub Release
   ([ADR-0014](docs/adr/0014-release-by-tag.md)). Its icon is baked from
   `app/assets/nghetruyen-source.png` by `app/make_icon.py`
   ([ADR-0015](docs/adr/0015-app-icon.md)).
3. Open a chapter and press ▶ in the Controls window. Playback only does
   anything where extraction actually found something to read, and the
   Controls window says so when it didn't. It also has a speed slider and a
   voice picker (populated live from the Sidecar's `/speakers`); both persist
   for next time.

### Linux

`run.sh` needs Python 3.10+ with the `venv` module, plus these system
packages:

| | Debian/Ubuntu | Arch | Fedora |
|---|---|---|---|
| `venv` module | `python3-venv` | (in `python`) | (in `python3`) |
| Audio (PortAudio) | `libportaudio2` | `portaudio` | `portaudio` |
| Web View backend | `python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1` | `python-gobject webkit2gtk-4.1` | `python3-gobject webkit2gtk4.1` |

`run.sh` names the missing `venv` package itself if it cannot find an
interpreter. The rest shows up where it matters rather than at launch: the Web
View backend when a window is created (pywebview chooses its backend then, so
an import alone will not catch it), and PortAudio as a message on the Controls
strip and in `nghetruyen.log`.

## Configuration

Open Options (see [app/README.md](app/README.md)): the Start URL the reader
opens on launch, the same Sidecar URL, voice, and default speed as the Player
Bar (whichever you change last wins), plus the Adapter list (content/strip/next
selectors per hostname) which only lives here.

By default the App reopens the Page you were last on, at the same window
position and dock height, and with the reader window hidden or in front exactly
as you left it ([ADR-0011](docs/adr/0011-restore-session-on-launch.md)); turn
"Reopen the last page on launch" off in Options to always start at Start URL.

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

## Credits

The voice is [VieNeu-TTS](https://github.com/pnnbao97/VieNeu-TTS), the engine
the Sidecar wraps and the App would not exist without
([ADR-0008](docs/adr/0008-switch-to-vieneu-tts.md)). If you use it, cite it:

```bibtex
@misc{vieneutts2026,
  title        = {VieNeu-TTS: Advanced Vietnamese Text-to-Speech with Instant Voice Cloning},
  author       = {Pham Nguyen Ngoc Bao},
  year         = {2026},
  publisher    = {Hugging Face},
  howpublished = {\url{https://huggingface.co/pnnbao-ump/VieNeu-TTS}}
}
```

