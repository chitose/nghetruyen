# The Controls strip is the primary window; the reader docks above it

The strip was frameless (ADR-0010): no native title bar, no resize border,
sized to match the reader's width and however tall the reader last dragged
its grip to. That made it fully dependent on the reader for both dimensions,
and gave it no native way to resize at all -- only a custom JS-driven grip
for height, and a custom JS-driven titlebar drag for position while
"floating" free of the reader.

Now the strip is a normal window: `frameless` and `easy_drag` are gone from
its `webview.create_window()` call, so it gets a real title bar, native
move, and native resize on every edge, for free. The reader docks above it
instead (`docking.py`), matching the strip's x and width; its own height is
still its own, whatever it was last resized to. This is the same
relationship ADR-0010 had, mirrored: previously the reader moved/resized and
the strip followed below; now the strip moves/resizes and the reader follows
above. The `_floating` escape hatch the old strip needed (so dragging it by
hand did not get yanked back to the reader the moment the reader moved) is
gone too -- the reader now has full native window controls of its own, so
there is nothing to escape from: dragging it by hand still gets corrected
back into place the next time the strip moves or the reader itself resizes,
same as the strip used to.

Two consequences of `docking.Dock` no longer owning a height:

- `session.json`'s `dockHeight` is gone; `controlsBounds` (`[x, y, width,
  height]`) takes its place, tracked the same way `readerBounds` already
  was. `readerBounds`'s own `width` and `x`/`y` stop mattering (docking.py
  computes them from the strip on every launch) but its `height` still
  seeds the reader's own size, same as before.
- The chrome's drag-titlebar row and resize grip (`DOCK_DRAG_JS`,
  `.dock-titlebar`, `.dock-grip`, and the `dock_move`/`dock_resize` events
  behind them) are dead code, removed along with the `Controller` methods
  that fielded them (`set_dock_height`, `begin_dock_move`, `move_dock`,
  `end_dock_move`). The strip's own native title bar shows its name and
  version (`f"Nghe Truyện {APP_VERSION}"` instead of a `ui.label` in the
  page), and the close button on it is now the OS's own -- there is nothing
  left for a custom one to do.

**The reader's own close button hides it instead of quitting the App.**
Before, closing either window quit the App -- there was no other way to
close the reader once it had a native frame, and a frame is what "fully
resizable" needs. Its `closing` event now runs `Controller.toggle_window()`
(the same thing Hide page's button does) and returns `False`, which
pywebview's `Event.set()` reads as "cancel this close" (a handler's `False`
specifically, not falsiness in general -- see `webview/event.py`) rather
than letting the native close destroy the window. The strip is unaffected:
its own `closing` is left unbound, so closing it still ends the App exactly
as before, and it is still the one window a hidden reader cannot take down
with it.

`Controller.attach_dock` survives for one reason: `show_window` calls
`dock.reposition()` directly rather than trusting pywebview's `shown` event
to fire again just because `.show()` was called after `.hide()` -- that is
backend-specific and not worth relying on, so Show page re-syncs the reader
above the strip itself, immediately, every time.

**Moving the strip while the reader is hidden used to bring it back.**
pywebview's Windows backend implements `window.move()` and `window.resize()`
with `SetWindowPos(..., SWP_SHOWWINDOW)` -- it un-hides the window as a side
effect, regardless of who called it or why. Since the strip driving the dock
means every strip move calls `reposition()`, which calls `move()`/`resize()`
on the reader, dragging the strip around while Hide page had the reader
tucked away silently showed it again. `dock()`/`Dock` now take a
`page_visible` callable, checked at the top of `reposition()`; main.py passes
`lambda: controller.window_visible`. Nothing is lost by skipping it while
hidden -- the reader is already wherever it needs to be by the time Show
page calls `reposition()` itself, per the paragraph above.
