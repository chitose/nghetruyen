# The icon is baked from one piece of artwork into every size

The App had no icon: it never set one, so both windows showed whatever default
Windows had for the process they were hosted in (in a source checkout, Python's
own). The chrome's tab showed NiceGUI's favicon. It is now
`app/assets/nghetruyen.ico` -- a rounded navy tile with white headphones and a
cyan play triangle on it -- wired into the two places that render it
(`webview.start(icon=...)` for the two windows, `ui.run(favicon=...)` for the
chrome pages) and into the exe's own resources through `NgheTruyen.spec`'s
`icon=`.

The mark is headphones plus play because those are the two parts of the job a
name cannot carry at 16x16: "Nghe Truyện" is Vietnamese for "listen to
stories", and the App's whole surface is a Page, a Player Bar, and a play
button. An open book was the alternative -- it says "stories" and not "listen",
and the App deliberately has no reader view (ADR-0009's list of what this
doesn't do), so the headphones are the honest half to draw. Two shapes and three
colours is the constraint from the taskbar size: at 16x16 the cyan triangle is
what makes the mark read as anything at all.

The artwork is the source (`assets/nghetruyen-source.png`), one square PNG the
size of a generated image. Replacing it and running `app/make_icon.py` is the
whole change procedure, because everything else about an icon is mechanical:
the artwork arrives on an opaque white margin and with opaque corners, so the
script crops to the tile, grows the mark's colours over the white its
anti-aliased edge blended into, masks the corners transparent at every size,
and writes the sizes Windows asks for -- 16, 24, 32, 48, 64, 128 and 256,
because Windows picks per context (taskbar, Alt-Tab, desktop, large-icon views)
and scales nothing itself.

Two files are committed from that: the `.ico` and a 256px PNG preview. The
preview is what a reader looks at to decide whether to trust the small sizes,
and `test_icon.py` holds the `.ico` to its sizes, to having white in it and
cyan in it, and to still matching the artwork it was baked from -- that last
one because swapping the source and forgetting to re-bake it leaves the taskbar
showing the old mark, and nothing else would notice.

The one thing the icon cost is another path that has to survive being frozen.
It is bundled as data (`('assets', 'assets')`) rather than only compiled into
the exe's resources, because pywebview and NiceGUI both load it from disk at
runtime, and `main.ICON_PATH` resolves it through the same `BUNDLE_DIR` the Web
View assets use (ADR-0012).
