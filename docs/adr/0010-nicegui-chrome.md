# The App's chrome is NiceGUI in its own window; the Page keeps a native Web View

The Player Bar, address bar, and Options screen were hand-written HTML/CSS/JS
rendered into whatever Page the Web View happened to be showing. They are now
a NiceGUI app (`app/ui.py`), served on `127.0.0.1:8935`. The address bar and
Player Bar live in a second, native pywebview window ("Nghe Truyện --
Controls"); Options is far too big for that strip, so it is loaded into the
reader window itself, with Back returning to the Page and leaving playback and
position alone. NiceGUI owns how the chrome looks; `app/controller.py` owns
what it means.

The Player Bar also carries an audio visualizer. Since the audio never reaches
the browser -- sounddevice plays it in Python -- there is no `<audio>` element
for the Web Audio API to analyze; `app/visualizer.py` instead runs a small FFT
over the samples `AudioPlayer` is sending out at that moment, and the chrome
pushes the resulting band levels to a canvas once per frame.

NiceGUI was chosen because it is Python: the controls, the Options form, and
the state they read are now one language, one process, and one testable object
(`Controller`) instead of a js_api bridge into a page script. The ad-hoc
`options.html`/`options.js`/`addressbar.js`/`player-bar.css` are deleted, and
content.js shrinks to extraction and next-chapter navigation -- the only work
that still needs a live DOM. `Api` (`app/api.py`) is now nothing but the
three-method bridge content.js calls.

The Page itself does not move. NiceGUI can only render its own document, so a
Chapter would have to sit in an iframe -- and a cross-origin iframe cannot run
our extraction script or the Player Bar, and many sites refuse framing
outright. A local proxy that fetched and rewrote each Page into our own origin
was rejected for the same reason the App embeds a real Web View in the first
place: it would work for server-rendered novel sites and quietly break
everywhere else. So the Web View stays, content.js stays injected on load, and
the two surfaces are joined by `Controller` rather than by the DOM.

That gives the App two windows instead of one. The Controls window is
frameless and docked flush under the reader -- same x and width, following
every move and resize, pinned to the bottom of the screen when the reader is
maximized, and hidden while it is minimized (`app/docking.py`) -- so the pair
still reads as one window. Frameless also means no native title bar and no
resize border, so both are drawn in the page (`app/ui.py`): a title bar to
drag the strip around and a close button, plus a grip along the bottom edge
that reports a new height through `Controller.set_dock_height` (kept across
every later dock). Moving the strip by hand detaches it: it stays put and
resizes in place until the reader's own geometry changes, which re-attaches
it. That is what makes the strip usable on its own once the reader window is
hidden. The single-source-of-truth rule from ADR-0009 now
applies to `Controller` exactly as it did to the js_api bridge, so a Page
reload still cannot desync playback. Closing the reader window stops the
Sidecar and the Controls window with it.

[ADR-0009](0009-standalone-app-replaces-extension.md)'s audio, chunking, and
playback decisions are untouched. This supersedes only its assumption that the
App's injected JS renders the Player Bar, and it adds `nicegui` to
`app/requirements.txt`.
