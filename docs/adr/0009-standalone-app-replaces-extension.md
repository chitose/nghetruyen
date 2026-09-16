# A standalone Windows app replaces the Chrome extension; the App owns audio directly

The extension is retired. In its place: a single Windows program (the App) built
on `pywebview` (WebView2), spawning the Sidecar as a child process instead of
requiring a manual terminal ([ADR-0001](0001-local-sidecar-for-tts.md)'s "started
manually" cost moves up one level -- you still start something by hand, but now
it's the App, which starts the Sidecar for you).

This supersedes [ADR-0002](0002-navigate-tab-with-offscreen-audio.md). That ADR's
offscreen document existed only to survive MV3 killing the content script on tab
navigation -- a constraint specific to Chrome's extension model. The App's Python
host is not part of any page; it survives navigation trivially, so there's no
offscreen-equivalent to build. Audio playback, the prefetch cache, chunking,
playback state, and auto-next decisions all move into the Python host. The
webview's injected JS shrinks to what only a live DOM can do: extraction
(`extractWithAdapter`/`genericExtract`), rendering the Player Bar, and
re-querying `findNextTarget` to click or navigate at the moment the App decides
to advance. JS sends intents (play/pause/skip/rate/speaker) over `pywebview`'s
`js_api` bridge; the App pushes state back. The App is the single source of
truth for playback state -- if JS kept any of its own, it would desync the
moment the page reloads, the exact failure ADR-0002 was written to avoid.

Audio plays via `sounddevice` (pure-pip, no native install) instead of
`python-vlc`. This keeps [ADR-0003](0003-sentence-chunk-contract.md)'s instant,
mid-chunk rate change, but the voice's pitch now shifts with speed -- nothing
free does pitch-preserving time-stretch outside a browser, and the alternative
(`pyrubberband`) needs the same kind of native binary dependency `python-vlc`
was rejected for. `preservesPitch` was never a deliberate requirement in any
ADR, just an incidental default of `HTMLMediaElement`; losing it is a smaller
cost than a second native dependency.

Also rejected: a system tray icon for background playback, and OS media-key /
lock-screen integration (`navigator.mediaSession`'s Windows equivalent, SMTC).
Both existed in the extension because Chrome hides the extension's UI once you
navigate away; the App's Player Bar is always on-screen in its one window, so
neither reason applies. Closing the App's window quits it and the Sidecar
outright.

The multi-tab guard in the old `offscreen.js` (`activeSessionId` vs
`chapterSessionId`, guarding a shared player against other tabs) is dropped
entirely -- a single-window app has no "other tabs" to guard against.

`extension/` stays in the repo, unused, until the App has carried a real
reading session end to end; then it gets deleted. No migration path exists
from the old `chrome.storage` adapters/settings -- the App starts from the same
baked-in `DEFAULT_ADAPTERS` a fresh extension install would.

**Amended by [ADR-0010](0010-nicegui-chrome.md):** the Player Bar and address
bar are no longer injected into the Page. They are a NiceGUI app in a second
window, and `app/api.py` is now only the extraction bridge content.js calls.
Everything above about the Python host owning playback state still holds.
