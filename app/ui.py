"""The App's chrome, built with NiceGUI: the address bar, the Player Bar, and
the Options page. NiceGUI serves it on localhost and it is shown in its own
pywebview window, while the Chapter itself renders in a separate native Web
View window. See docs/adr/0010-nicegui-chrome.md.

Everything here reads from and calls into Controller; NiceGUI only owns how it
looks. Blocking work (playback, navigation) is pushed to a thread so the
NiceGUI event loop -- and therefore the chrome -- stays responsive.
"""
import asyncio
import json
import threading

from nicegui import ui

from config import DEFAULT_SHORT_PARAGRAPH_WORDS

UI_HOST = "127.0.0.1"
UI_PORT = 8935
PLAY_GLYPHS = {"playing": "⏸", "buffering": "⏳"}

# Dragging for the docked Controls window. It is frameless -- no native title
# bar and no resize border -- so both affordances are drawn in the page:
#   .dock-titlebar -> 'dock_move_start' / 'dock_move' / 'dock_move_end'
#   .dock-grip     -> 'dock_resize' with the new height in pixels
# They matter most when the reader window is hidden and the strip is alone.
DOCK_DRAG_JS = """
<script>
document.addEventListener('DOMContentLoaded', function () {
  if (window.__dockDragInstalled) return;
  window.__dockDragInstalled = true;
  const INTERACTIVE = '.q-btn, button, input, select, textarea, a, .no-drag';
  const emit = function (name, ...args) {
    if (typeof emitEvent === 'function') emitEvent(name, ...args);
  };
  let resizing = false, startY = 0, startHeight = 0, lastHeight = 0;
  let moving = false, startX = 0, moveY = 0, lastX = 0, lastY = 0;

  document.addEventListener('mousedown', function (event) {
    const target = event.target;
    if (!target || !target.closest) return;
    if (target.closest('.dock-grip')) {
      resizing = true;
      startY = event.screenY;
      startHeight = window.innerHeight;
      lastHeight = 0;
      event.preventDefault();
      return;
    }
    if (target.closest('.dock-titlebar') && !target.closest(INTERACTIVE)) {
      moving = true;
      startX = lastX = event.screenX;
      moveY = lastY = event.screenY;
      emit('dock_move_start');
      event.preventDefault();
    }
  });

  document.addEventListener('mousemove', function (event) {
    if (resizing) {
      const next = Math.round(startHeight + (event.screenY - startY));
      if (Math.abs(next - lastHeight) < 4) return;
      lastHeight = next;
      emit('dock_resize', next);
    } else if (moving) {
      if (Math.abs(event.screenX - lastX) < 2 && Math.abs(event.screenY - lastY) < 2) return;
      lastX = event.screenX;
      lastY = event.screenY;
      emit('dock_move', event.screenX - startX, event.screenY - moveY);
    }
  });

  document.addEventListener('mouseup', function () {
    if (moving) emit('dock_move_end');
    resizing = false;
    moving = false;
  });
});
</script>
"""


# Draws one visualizer frame onto its canvas; Python pushes a call per frame via
# ui.run_javascript, since the audio itself never reaches the browser. The
# style names must match config.VISUALIZER_STYLES.
VISUALIZER_JS = """
<script>
window.__vnViz = function (values, style) {
  const canvas = document.getElementById('vn-viz');
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 300;
  const height = canvas.clientHeight || 26;
  if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const live = !!values;
  const count = (values && values.length) || 28;
  const levels = [];
  for (let i = 0; i < count; i++) {
    levels.push(live ? Math.max(0, Math.min(1, values[i] || 0)) : 0);
  }
  const color = live ? 'rgba(120, 190, 255, 0.9)' : 'rgba(255, 255, 255, 0.18)';
  const dim = 'rgba(255, 255, 255, 0.18)';
  const gap = 2;
  const slot = width / count;
  const barWidth = Math.max(1, slot - gap);

  if (style === 'mirrored') {
    const mid = height / 2;
    for (let i = 0; i < count; i++) {
      const half = Math.max(1, levels[i] * mid);
      ctx.fillStyle = color;
      ctx.fillRect(i * slot + gap / 2, mid - half, barWidth, half * 2);
    }
    return;
  }

  if (style === 'wave') {
    const mid = height / 2;
    ctx.beginPath();
    ctx.moveTo(0, mid);
    for (let i = 0; i < count; i++) {
      ctx.lineTo((i + 0.5) * slot, mid - Math.max(1, levels[i] * mid));
    }
    for (let i = count - 1; i >= 0; i--) {
      ctx.lineTo((i + 0.5) * slot, mid + Math.max(1, levels[i] * mid));
    }
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.fill();
    return;
  }

  if (style === 'blocks') {
    const rows = 4;
    const rowHeight = height / rows;
    for (let i = 0; i < count; i++) {
      const lit = live ? Math.round(levels[i] * rows) : 0;
      for (let row = 0; row < rows; row++) {
        ctx.fillStyle = row < lit ? color : dim;
        ctx.fillRect(i * slot + gap / 2, height - (row + 1) * rowHeight + 1, barWidth, rowHeight - 2);
      }
    }
    return;
  }

  // 'bars' (the default): levels grow up from the bottom edge.
  for (let i = 0; i < count; i++) {
    const barHeight = Math.max(2, levels[i] * height);
    ctx.fillStyle = color;
    ctx.fillRect(i * slot + gap / 2, height - barHeight, barWidth, barHeight);
  }
};
</script>
"""


def create_pages(controller) -> None:
    """Register the chrome and options pages. Call once, before run_ui()."""

    @ui.page("/")
    def chrome() -> None:
        ui.page_title("Nghe Truyện -- Controls")
        _chrome(controller)

    @ui.page("/options")
    def options() -> None:
        ui.page_title("Nghe Truyện -- Options")
        _options(controller)


def run_ui(
    host: str = UI_HOST, port: int = UI_PORT, favicon: str | None = None,
) -> None:
    """Blocking; run in a background thread while pywebview owns the main one.

    `favicon` is the App's icon, which the chrome pages show in the tab and the
    taskbar thumbnail; main.py passes the bundled copy's path.
    """
    ui.run(
        host=host,
        port=port,
        title="Nghe Truyện",
        dark=True,
        reload=False,
        show=False,
        uvicorn_logging_level="warning",
        show_welcome_message=False,
        favicon=favicon,
    )


async def _in_thread(func, *args) -> None:
    await asyncio.to_thread(func, *args)


def _event_values(args, count=1):
    """ui.on hands over whatever emitEvent sent, sometimes wrapped in a list."""
    if isinstance(args, (list, tuple)):
        values = list(args)
    elif isinstance(args, dict):
        values = [args.get("height")]
    else:
        values = [args]
    values = values[:count]
    return values + [None] * (count - len(values))


def _speaker_options(controller) -> list:
    options = list(controller.known_speakers)
    if controller.speaker and controller.speaker not in options:
        options.insert(0, controller.speaker)
    return options


def status_text(controller) -> str:
    """What the status line shows, which the Sidecar's startup shares with the
    per-Paragraph position.

    A Sidecar failure outranks everything else, because nothing can play until
    it is fixed and the fix is in that message (Retry, or the log it names). A
    playback error outranks the "starting" notice, being the more specific
    thing to have just happened. The position itself only matters once the
    Sidecar is up, since that is when playback can work at all.
    """
    if controller.sidecar_failed:
        return controller.sidecar_message
    if controller.error_message:
        return controller.error_message
    if controller.sidecar_starting:
        # SidecarStartup narrates the slow parts (building sidecar/venv,
        # downloading the voice model); "Starting…" is only what to say before
        # it has said anything.
        return controller.sidecar_message or "Starting the Sidecar…"
    if controller.total_paragraphs:
        return f"{controller.paragraph_index + 1} / {controller.total_paragraphs}"
    return controller.status


SIDECAR_ICONS = {"starting": "🟡", "failed": "🔴", "ready": "🟢"}


def sidecar_icon_state(controller) -> str:
    """One of SIDECAR_ICONS's keys, so the strip has a health dot beside the
    text -- the message already carries the detail, this is glanceable."""
    if controller.sidecar_failed:
        return "failed"
    if controller.sidecar_starting:
        return "starting"
    return "ready"


def window_toggle_text(controller) -> str:
    """What the Hide page / Show page button says.

    It is the Controller's `window_visible` that decides, not the last click:
    a launch that restored a hidden reader (ADR-0011) has to offer "Show page"
    from its first tick, without anyone having pressed anything.
    """
    return "Hide page" if controller.window_visible else "Show page"


def _chrome(controller) -> None:
    view = {
        "url_rev": -1,
        "settings_rev": -1,
        "show_text": False,
        "viz_idle": False,
        "viz_style": None,
        "retry_shown": False,
        # Whether the Sidecar was already up when this page was built; if it was
        # not, the voice list below is the baked-in fallback and is re-fetched
        # once the startup watcher reports it ready.
        "sidecar_ready": not (controller.sidecar_starting or controller.sidecar_failed),
    }

    # Dragging the title bar moves the strip, the grip resizes it (see
    # docking.Dock); both matter most when the reader window is hidden.
    ui.on("dock_resize", lambda e: controller.set_dock_height(_event_values(e.args, 1)[0]))
    ui.on("dock_move_start", lambda e: controller.begin_dock_move())
    ui.on("dock_move", lambda e: controller.move_dock(*_event_values(e.args, 2)))
    ui.on("dock_move_end", lambda e: controller.end_dock_move())
    ui.add_body_html(DOCK_DRAG_JS)
    ui.add_body_html(VISUALIZER_JS)

    with ui.column().classes("w-full gap-1 p-2"):
        # The strip's own title bar: drag it to move the window, ✕ to quit.
        # A frameless window gets neither from the OS.
        with ui.row().classes("dock-titlebar w-full items-center").style("cursor: move"):
            ui.label("Nghe Truyện").classes("text-xs opacity-50")
            close_button = ui.label("✕").classes("no-drag ml-auto cursor-pointer px-2 text-sm opacity-70")
            close_button.on("click", lambda: _in_thread(controller.quit))

        # --- address bar ---
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.button("←", on_click=lambda: _in_thread(controller.go_back)).props("flat dense")
            ui.button("→", on_click=lambda: _in_thread(controller.go_forward)).props("flat dense")
            url_input = ui.input(value=controller.current_url or "").props("dense outlined").classes("flex-grow")

            async def go() -> None:
                await _in_thread(controller.navigate, url_input.value)

            url_input.on("keydown.enter", go)
            ui.button("Go", on_click=go).props("dense")
            # Options opens in the reader window -- the docked strip is too
            # small for that form. See Controller.open_options.
            ui.button(
                "⚙",
                on_click=lambda: _in_thread(
                    controller.open_options, f"http://{UI_HOST}:{UI_PORT}/options"
                ),
            ).props("flat dense")
            window_toggle = ui.button(
                window_toggle_text(controller),
                on_click=lambda: _in_thread(controller.toggle_window),
            ).props("flat dense")

        # --- Player Bar ---
        with ui.row().classes("w-full items-center gap-3 no-wrap"):
            ui.button("⏮", on_click=lambda: _in_thread(controller.skip, -1)).props("flat dense")
            play_button = ui.button("▶", on_click=lambda: _in_thread(controller.play_pause)).props("unelevated round")
            ui.button("⏭", on_click=lambda: _in_thread(controller.skip, 1)).props("flat dense")
            rate_slider = ui.slider(
                min=0.5, max=2.0, step=0.1, value=controller.rate,
                on_change=lambda e: controller.set_rate(e.value),
            ).classes("w-32")
            rate_label = ui.label(f"{controller.rate:.1f}x").classes("w-10 text-sm opacity-80")
            speaker_select = ui.select(
                _speaker_options(controller), value=controller.speaker,
                on_change=lambda e: controller.set_speaker(e.value),
            ).props("dense").classes("w-44")
            auto_next = ui.checkbox(
                "Auto-next", value=controller.auto_next,
                on_change=lambda e: controller.set_auto_next(e.value),
            )

        with ui.row().classes("w-full items-center gap-2"):
            # text_panel is created below but only read when this button fires.
            def toggle_text() -> None:
                view["show_text"] = not view["show_text"]
                text_panel.set_visibility(view["show_text"])
                if view["show_text"]:
                    text_panel.text = controller.paragraph_text

            ui.button("👁 Current paragraph", on_click=toggle_text).props("flat dense")
            # The visualizer fills the dead space in this row; Python pushes
            # bar heights to it (see update_visualizer below). The arrows are
            # its carousel nav -- they cycle config.VISUALIZER_STYLES.
            ui.button(
                "‹", on_click=lambda: _in_thread(controller.cycle_visualizer_style, -1)
            ).props("flat dense").tooltip("Previous visualizer")
            ui.html(
                '<canvas id="vn-viz" style="width:100%;height:26px;display:block"></canvas>',
                sanitize=False,
            ).classes("flex-grow").style("min-width:120px")
            ui.button(
                "›", on_click=lambda: _in_thread(controller.cycle_visualizer_style, 1)
            ).props("flat dense").tooltip("Next visualizer")
            style_label = ui.label(controller.visualizer_style.title()).classes(
                "viz-style text-xs opacity-60 w-20"
            )
            sidecar_icon = ui.label("").classes("text-sm")
            sidecar_icon.tooltip("Sidecar health")
            status_label = ui.label("").classes("text-sm opacity-80")
            # Only reachable while the Sidecar is down: it appears next to the
            # message saying so, and runs the startup watcher again.
            retry_button = ui.button(
                "Retry", on_click=lambda: _in_thread(controller.retry_sidecar),
            ).props("flat dense")
            retry_button.tooltip("Start the Sidecar again")
            retry_button.set_visibility(False)

        text_panel = ui.label("").classes("w-full whitespace-pre-wrap text-sm opacity-90")
        text_panel.set_visibility(False)

        # The drag handle: fixed to the very bottom edge so it costs no layout
        # height, whatever the window's current size.
        ui.element("div").classes("dock-grip").style(
            "position: fixed; left: 0; right: 0; bottom: 0; height: 8px; "
            "cursor: row-resize; z-index: 2000; "
            "background: rgba(255, 255, 255, 0.10); "
            "border-top: 1px solid rgba(255, 255, 255, 0.22);"
        )

    # Live voice list, off the event loop: the HTTP call runs in a thread and
    # the result is folded in on the next tick. Fetched again if it turns out
    # the Sidecar was not up yet (see tick), since the first attempt then only
    # got as far as the static KNOWN_SPEAKERS fallback.
    voices = {"result": None, "fetching": False}

    def fetch_voices() -> None:
        if voices["fetching"]:
            return
        voices["fetching"] = True

        def load() -> None:
            voices["result"] = controller.get_speakers()
            voices["fetching"] = False

        threading.Thread(target=load, daemon=True).start()

    fetch_voices()

    def tick() -> None:
        if controller.url_rev != view["url_rev"]:
            view["url_rev"] = controller.url_rev
            url_input.value = controller.current_url
        if controller.settings_rev != view["settings_rev"]:
            view["settings_rev"] = controller.settings_rev
            rate_slider.value = controller.rate
            speaker_select.value = controller.speaker
            auto_next.value = controller.auto_next
            style_label.text = controller.visualizer_style.title()
        if controller.sidecar_failed != view["retry_shown"]:
            view["retry_shown"] = controller.sidecar_failed
            retry_button.set_visibility(controller.sidecar_failed)
        # The Sidecar can come up after this page was built, in which case the
        # voice list above was the baked-in fallback; fetch the real one now.
        sidecar_up = not (controller.sidecar_starting or controller.sidecar_failed)
        if sidecar_up and not view["sidecar_ready"]:
            view["sidecar_ready"] = True
            fetch_voices()
        result = voices["result"]
        if result is not None:
            voices["result"] = None
            if result.get("ok"):
                speaker_select.options = list(dict.fromkeys([*result["speakers"], controller.speaker]))
                speaker_select.update()
        play_button.text = PLAY_GLYPHS.get(controller.playback_state, "▶")
        play_button.enabled = sidecar_up and controller.playback_state != "buffering"
        window_toggle.text = window_toggle_text(controller)
        rate_label.text = f"{controller.rate:.1f}x"
        if view["show_text"]:
            text_panel.text = controller.paragraph_text
        status_label.text = status_text(controller)
        sidecar_icon.text = SIDECAR_ICONS[sidecar_icon_state(controller)]

    ui.timer(0.2, tick)

    # Audio is played in Python (there is no <audio> element to analyze), so
    # Python computes the bands and pushes them to the canvas each frame.
    def update_visualizer() -> None:
        style = controller.visualizer_style
        style_changed = style != view["viz_style"]
        view["viz_style"] = style
        levels = controller.visualizer_levels()
        if levels is None:
            if view["viz_idle"] and not style_changed:
                return
            view["viz_idle"] = True
            ui.run_javascript(f"window.__vnViz && window.__vnViz(null, {style!r})")
            return
        view["viz_idle"] = False
        payload = json.dumps([round(level, 3) for level in levels])
        ui.run_javascript(f"window.__vnViz && window.__vnViz({payload}, {style!r})")

    ui.timer(0.05, update_visualizer)


def _options(controller) -> None:
    settings = controller.get_settings()

    with ui.column().classes("w-full gap-3 p-4"):
        with ui.row().classes("items-center gap-2"):
            ui.button("← Back", on_click=lambda: _in_thread(controller.leave_options)).props("flat")
            ui.label("Options").classes("text-xl")

        start_url = ui.input(
            "Start URL", value=settings["startUrl"] or "",
            placeholder="https://metruyenchu.co",
        ).classes("w-full")
        ui.label("Opens in the reader window on launch.").classes("text-xs opacity-60")
        restore_last_page = ui.checkbox(
            "Reopen the last page on launch", value=bool(settings["restoreLastPage"]),
        )
        join_short = ui.checkbox(
            "Read short paragraphs together",
            value=bool(settings["joinShortParagraphs"]),
        )
        short_words = ui.number(
            "Join paragraphs under this many words",
            value=int(settings["shortParagraphWords"]),
            min=1, max=100, step=1,
        ).classes("w-72")
        ui.label(
            "Web novels often put a line of dialogue on its own paragraph; "
            "shorter ones are read together with what follows."
        ).classes("text-xs opacity-60")
        sidecar_url = ui.input("Sidecar URL", value=settings["sidecarUrl"] or "").classes("w-full")
        speaker = ui.select(
            _speaker_options(controller), label="Default speaker",
            value=settings["speaker"], with_input=True,
        ).classes("w-full")
        rate = ui.number(
            "Default rate", value=float(settings["defaultRate"] or 1.0),
            min=0.5, max=2.0, step=0.1,
        ).classes("w-40")
        backend = ui.select(
            ["default", "v3nano"], label="Backend model",
            value=settings["backendModel"] or "default",
        ).classes("w-60")
        ui.label("Backend model takes effect after restarting the app.").classes("text-xs opacity-60")

        def save_settings() -> None:
            controller.save_settings({
                "sidecarUrl": sidecar_url.value,
                "startUrl": start_url.value,
                "restoreLastPage": bool(restore_last_page.value),
                "joinShortParagraphs": bool(join_short.value),
                "shortParagraphWords": max(
                    1, int(short_words.value or DEFAULT_SHORT_PARAGRAPH_WORDS)
                ),
                "speaker": speaker.value,
                "defaultRate": float(rate.value) if rate.value is not None else 1.0,
                "backendModel": backend.value,
            })
            ui.notify("Settings saved.")

        ui.button("Save settings", on_click=save_settings)

        ui.separator()
        ui.label("Adapters (JSON)").classes("text-xl")
        adapters = ui.textarea(
            value=json.dumps(controller.get_adapters(), ensure_ascii=False, indent=2),
        ).classes("w-full font-mono").props("rows=16")

        def save_adapters() -> None:
            try:
                parsed = json.loads(adapters.value or "")
            except ValueError as err:
                ui.notify(f"Invalid JSON: {err}", color="negative")
                return
            controller.save_adapters(parsed)
            ui.notify("Adapters saved.")

        ui.button("Save adapters", on_click=save_adapters)
