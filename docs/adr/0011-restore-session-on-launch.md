# The App reopens where it left off

**Amended:** the reader window's hidden/shown state is saved and restored too
(`readerHidden`), and clicking Options now reveals a hidden reader. The last
paragraph below argued for the opposite; it has been rewritten to say what the
App does instead and why the old objection no longer applies.

Closing the App used to mean losing your place: the reader always reopened at
the configured Start URL, and both windows came back at their default size and
position. Now the App writes what it was doing to
`%APPDATA%\reading-web\session.json` on shutdown and reads it back on launch:
the Page the reader was showing, the reader window's bounds, the dock's
height, and whether the reader was tucked away behind the strip.

This is deliberately separate from `config.json`. Settings are what the reader
edits in Options; session state is what the App writes by itself, and it should
never need hand-editing or migrating the way a setting might. Keeping them
apart also means a failed session write cannot corrupt the settings.

The *Page* is where this stops. The App still has no mid-chapter resume
("What this doesn't do" in the README): reopening the same Chapter starts at
its first Paragraph, because the Chapter is re-extracted from the site rather
than kept around. Saving a Paragraph index would mean either trusting an index
across a re-extraction that can produce a different Paragraph list, or caching
Chapter text -- both bigger changes than picking up where you were reading, and
neither was asked for.

Bounds are validated against the screens that exist at launch, so a stored
position from a monitor that has since been unplugged falls back to the normal
centered layout instead of opening off-screen where it cannot be reached. The
same guard rejects a stored size below the reader's minimum.

Options gained "Reopen the last page on launch" (on by default). Turning it off
makes Start URL authoritative again, for anyone who treats the App as a
launcher for one fixed Chapter list rather than a place to resume.

Whether the reader window was hidden at close is restored as well. This file
used to argue the other way -- a hidden reader on launch looks like a failure --
and what changed is the second half of that worry: the strip is on screen
either way, carrying the Sidecar's status and the Chapter position, and its
button says "Show page" from the first tick (`ui.window_toggle_text`), so the
App never comes up with nothing to look at and nothing to click. The window is
created hidden (`webview.create_window(hidden=...)`) rather than shown and then
hidden, so it does not flash on screen on the way. Only a real `true` counts
(`session.restore_hidden`): a session.json written before this was stored, or
one edited by hand, still launches with the reader in front of you.

Clicking Options reveals a hidden reader too. Options renders *in* the reader
window (ADR-0010), so with the reader tucked away that click used to load a
page into a window nobody could see, which looked exactly like a dead button.
