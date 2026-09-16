# The App reopens where it left off

Closing the App used to mean losing your place: the reader always reopened at
the configured Start URL, and both windows came back at their default size and
position. Now the App writes what it was doing to
`%APPDATA%\reading-web\session.json` on shutdown and reads it back on launch:
the Page the reader was showing, the reader window's bounds, and the dock's
height.

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

Whether the reader window was hidden at close is *not* restored: a hidden
reader on launch looks like a failure, and Show page is one click away.
