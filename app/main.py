# app/main.py
"""Entry point.

The App is two windows. The NiceGUI chrome (address bar + Player Bar +
Options) is served on localhost by `run_ui` and shown in the Controls
window, the App's primary, fully resizable window; the native Web View
renders the Chapter and docks above it, matching its width (docking.py, see
ADR-0020). Both talk to the one Controller, which owns playback state -- see
docs/adr/0010-nicegui-chrome.md.

Where the App was last time (the Page, the reader's and the strip's bounds,
and whether the reader was hidden behind the strip) is read from
session.json on launch and written back on shutdown -- see
docs/adr/0011-restore-session-on-launch.md. `SidecarStartup` provisions the
Sidecar's venv when it is missing and spawns it, reporting progress to the
startup window and then to the chrome, so startup is neither silent nor a
manual setup step -- see docs/adr/0013-sidecar-startup-status.md and
docs/adr/0016-app-provisions-the-sidecar-environment.md.

None of this is Windows-specific any more: the settings folder, the icon's
file format, and the startup window each come from the one module that knows
the platform (`platform_paths`, `icon`, `splash.make_splash`), and the two
places that genuinely were Win32 -- the tool-window style and the startup
window -- degrade to "fewer desktop refinements" rather than to a failure.
See docs/adr/0017-linux-launcher.md.
"""
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import webview

import platform_paths
from api import Api
from audio_player import AudioPlayer
from config import Config
from controller import Controller
from docking import dock
from icon import app_icon_path
from media_hotkeys import start as start_media_hotkeys
from playback import PlaybackEngine
from session import Session, restore_bounds, restore_hidden
from sidecar_client import SidecarClient
from sidecar_env import extract_bundled_sidecar, find_sidecar_dir, venv_python
from sidecar_manager import SidecarManager, SidecarStartup
from splash import make_splash
from ui import UI_HOST, UI_PORT, create_pages, run_ui
from version import app_version
from visualizer import Visualizer
from window_group import as_tool_window

def _frozen() -> bool:
    """True inside a PyInstaller build -- the standalone NgheTruyen.exe."""
    return bool(getattr(sys, "frozen", False))


if _frozen():
    # The App's own modules and web assets are bundled into the exe, so nothing
    # of ours sits on disk next to it.
    APP_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
else:
    APP_DIR = Path(__file__).parent
    BUNDLE_DIR = APP_DIR

WEB_DIR = BUNDLE_DIR / "web"
# Both windows' title bars and the taskbar icon, in the format this platform
# reads (see icon.py). Bundled like web/ so the standalone exe has it too, and
# a real file on disk because both pywebview and NiceGUI load it by path rather
# than from the bundle.
ICON_PATH = app_icon_path(BUNDLE_DIR)
# Written by build.bat/release.yml right before the exe is built; "dev" for a
# source checkout, which never has one. See version.py.
APP_VERSION = app_version(BUNDLE_DIR)
# The data folder keeps its original name on Windows: config.json and
# session.json live there, and renaming it would strand an existing install's
# settings. On Linux there is no such install, so this is the XDG location
# instead -- see platform_paths.data_dir and ADR-0017.
DATA_DIR = platform_paths.data_dir()
CONFIG_PATH = DATA_DIR / "config.json"
SESSION_PATH = DATA_DIR / "session.json"
LOG_PATH = DATA_DIR / "nghetruyen.log"

READERABLE_JS = (WEB_DIR / "readerable.js").read_text(encoding="utf-8")
CONTENT_JS = (WEB_DIR / "content.js").read_text(encoding="utf-8")

# Hardware Play/Pause, Next, and Previous Track keys reach the reader window as
# ordinary keydown events with these `code` values (Chromium translates them
# from the OS) whenever it has focus -- no native hotkey plumbing needed. Guarded
# by a flag on `window` because `inject_content_script` runs again on every
# navigation and would otherwise stack up duplicate listeners.
MEDIA_KEYS_JS = """
if (!window.__ngheTruyenMediaKeys) {
  window.__ngheTruyenMediaKeys = true;
  window.addEventListener('keydown', function (e) {
    if (e.repeat) return;
    if (e.code === 'MediaPlayPause') window.pywebview.api.play_pause();
    else if (e.code === 'MediaTrackNext') window.pywebview.api.skip(1);
    else if (e.code === 'MediaTrackPrevious') window.pywebview.api.skip(-1);
  });
}
"""


def warn(message: str) -> None:
    """Warnings have to survive a windowed exe, which has no console."""
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass

CONTENT_WIDTH = 1200
CONTENT_HEIGHT = 760
MIN_CONTENT_WIDTH = 640
MIN_CONTENT_HEIGHT = 400
# The Controls strip's own defaults, now that it is a normal, fully resizable
# window rather than one sized to match the reader. Its minimum width is the
# reader's: docking.py always matches them, and letting the strip go narrower
# than the reader can would either desync the two or fight the reader's own
# min_size.
CONTROLS_HEIGHT = 176
MIN_CONTROLS_WIDTH = MIN_CONTENT_WIDTH
MIN_CONTROLS_HEIGHT = 120

CHROME_BASE_URL = f"http://{UI_HOST}:{UI_PORT}/"


def inject_content_script(window) -> None:
    # Media keys work here too, Options included -- cheap, and harmless where
    # they don't apply.
    window.evaluate_js(MEDIA_KEYS_JS)

    # Options is served by the chrome server and loaded in this same window
    # (see Controller.open_options); there is nothing to extract there, and
    # reporting it would clobber the address bar and the remembered Page.
    url = window.evaluate_js("location.href") or ""
    if url.startswith(CHROME_BASE_URL):
        return
    # readerable.js must run first -- content.js's genericExtract() calls
    # isProbablyReaderable() at call time and expects it already defined.
    window.evaluate_js(READERABLE_JS)
    window.evaluate_js(CONTENT_JS)


def wait_for_ui(port: int, timeout: float = 20.0) -> bool:
    """The Controls window points at NiceGUI, so the server has to be listening
    before webview.start() opens it -- otherwise the window shows a dead page."""
    deadline = time.monotonic() + timeout
    url = f"http://{UI_HOST}:{port}/"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except Exception:
            time.sleep(0.1)
    return False


def _screens() -> list:
    try:
        return list(webview.screens or [])
    except Exception:
        return []


def _primary_screen():
    screens = _screens()
    if not screens:
        return None
    return next((s for s in screens if s.x == 0 and s.y == 0), screens[0])


def _screen_rects() -> list:
    return [(screen.x, screen.y, screen.width, screen.height) for screen in _screens()]


def find_screen(x: int, y: int):
    """The (x, y, width, height) of the screen the reader is on, or None."""
    for screen_x, screen_y, width, height in _screen_rects():
        if screen_x <= x < screen_x + width and screen_y <= y < screen_y + height:
            return screen_x, screen_y, width, height
    primary = _primary_screen()
    return (primary.x, primary.y, primary.width, primary.height) if primary else None


def watch_bounds(window, stored) -> dict:
    """A window's last known (x, y, width, height), updated live: by shutdown
    the window may already be gone, and reading it then would be too late.
    `stored` seeds it from session.json until the window's own events report
    in (a `dict` rather than a plain value so the closure below can write to
    it without a `nonlocal`)."""
    state = {"value": list(stored) if isinstance(stored, (list, tuple)) else None}

    def track(*_args) -> None:
        try:
            state["value"] = [window.x, window.y, window.width, window.height]
        except Exception:
            pass

    window.events.shown += track
    window.events.moved += track
    window.events.resized += track
    return state


def initial_layout():
    """(controls_x, controls_y, controls_width, controls_height, content_height)
    for a fresh install, with nothing in session.json to restore yet: the
    strip sized and centered so the reader, docked above it, fits on screen
    too."""
    screen = _primary_screen()
    if screen is None:
        return 80, 40 + CONTENT_HEIGHT, CONTENT_WIDTH, CONTROLS_HEIGHT, CONTENT_HEIGHT
    width = min(CONTENT_WIDTH, max(MIN_CONTROLS_WIDTH, screen.width - 40))
    content_height = min(CONTENT_HEIGHT, max(MIN_CONTENT_HEIGHT, screen.height - CONTROLS_HEIGHT - 80))
    x = screen.x + (screen.width - width) // 2
    top = screen.y + max(20, (screen.height - (content_height + CONTROLS_HEIGHT)) // 2)
    return x, top + content_height, width, CONTROLS_HEIGHT, content_height


if __name__ == "__main__":
    # First thing, because the exe unpacks and the chrome takes a moment to
    # serve: this window covers that gap with the Sidecar's status, then hands
    # over to the Controls strip. See docs/adr/0013-sidecar-startup-status.md.
    splash = make_splash(icon_path=ICON_PATH, on_warning=warn)
    splash.start()

    config = Config(CONFIG_PATH)
    session = Session(SESSION_PATH)

    sidecar_dir = find_sidecar_dir(APP_DIR)
    if _frozen() and not (sidecar_dir / "server.py").is_file():
        # A copy of the exe with no sidecar/ checked out beside it -- drop the
        # bundled server.py/requirements.txt next to the exe itself so
        # ensure_env() has something to build a venv from. See ADR-0019.
        candidate = APP_DIR / "sidecar"
        if extract_bundled_sidecar(BUNDLE_DIR / "sidecar", candidate):
            sidecar_dir = candidate
    sidecar_manager = SidecarManager(
        python_exe=str(venv_python(sidecar_dir)),
        cwd=str(sidecar_dir),
        port=urlparse(config.get("sidecarUrl")).port or 8934,
        on_warning=warn,
    )

    sidecar_client = SidecarClient(config.get("sidecarUrl"))
    audio_player = AudioPlayer(on_finished=lambda: None)  # PlaybackEngine overwrites on_finished
    playback = PlaybackEngine(
        sidecar_client, audio_player,
        notify=lambda event: controller.on_playback_event(event),
    )
    controller = Controller(config, playback, sidecar_client, version=APP_VERSION)
    controller.attach_visualizer(Visualizer(audio_player))
    controller.attach_open_sidecar_log(
        lambda: platform_paths.open_in_default_app(sidecar_manager.log_path)
    )

    # The Sidecar starts off the critical path, and how it goes is reported to
    # the chrome's status line rather than only into sidecar.log -- a Sidecar
    # that never came up used to look like an App where Play did nothing. Its
    # Retry button runs the same call again; see
    # docs/adr/0013-sidecar-startup-status.md.
    backend_model = config.get("backendModel")

    def report_sidecar(state, message=""):
        """Both surfaces want this: the startup window while the App is still
        coming up, and the strip the reader watches from then on."""
        controller.report_sidecar(state, message)
        splash.set_status(state, message)

    startup = SidecarStartup(
        sidecar_manager, on_status=report_sidecar, on_warning=warn,
    )
    startup.start(backend_model=backend_model)
    controller.attach_sidecar_retry(lambda: startup.start(backend_model=backend_model))

    # Serve the chrome first: the Controls window below loads this URL, and the
    # pages must be registered before ui.run() starts the server.
    create_pages(controller)
    threading.Thread(
        target=run_ui, kwargs={"favicon": str(ICON_PATH)}, daemon=True,
    ).start()
    if not wait_for_ui(UI_PORT):
        warn("Warning: the NiceGUI chrome did not come up; the Controls window may be blank.")

    (
        default_controls_x, default_controls_y,
        default_controls_width, default_controls_height,
        default_content_height,
    ) = initial_layout()
    controls_x, controls_y, controls_width, controls_height = (
        restore_bounds(
            session.get("controlsBounds"), _screen_rects(),
            min_width=MIN_CONTROLS_WIDTH, min_height=MIN_CONTROLS_HEIGHT,
        ) or (default_controls_x, default_controls_y, default_controls_width, default_controls_height)
    )
    # Only the reader's own height is its business now (docking.py positions
    # it above the strip, matching the strip's x and width); a restored
    # readerBounds is read just for that.
    _, _, _, content_height = (
        restore_bounds(
            session.get("readerBounds"), _screen_rects(),
            min_width=MIN_CONTENT_WIDTH, min_height=MIN_CONTENT_HEIGHT,
        ) or (0, 0, 0, default_content_height)
    )
    content_x, content_y, content_width = controls_x, controls_y - content_height, controls_width

    start_url = controller.start_url
    if controller.restore_last_page:
        start_url = session.get("lastUrl") or start_url

    # Hide page is remembered too, so a session spent listening with the reader
    # tucked away comes back that way. pywebview creates the window hidden
    # rather than showing and hiding it, which would flash it on screen first;
    # `hidden=True` still runs the window's `shown` handlers, so the dock, the
    # bounds tracking, and the startup window all behave as usual.
    reader_hidden = restore_hidden(session.get("readerHidden"))

    # The App's primary window: fully resizable and freely moved, a normal
    # window rather than the frameless strip it used to be. The reader docks
    # above it instead, matching its width (docking.py) -- see ADR-0020.
    controls_window = webview.create_window(
        f"Nghe Truyện {APP_VERSION}",
        url=f"http://{UI_HOST}:{UI_PORT}/",
        x=controls_x, y=controls_y, width=controls_width, height=controls_height,
        min_size=(MIN_CONTROLS_WIDTH, MIN_CONTROLS_HEIGHT),
    )

    content_window = webview.create_window(
        "Nghe Truyện -- Reader",
        url=start_url,
        js_api=Api(controller),
        x=content_x, y=content_y, width=content_width, height=content_height,
        min_size=(MIN_CONTENT_WIDTH, MIN_CONTENT_HEIGHT),
        hidden=reader_hidden,
    )
    controller.attach_content_window(content_window, hidden=reader_hidden)
    content_window.events.loaded += lambda: inject_content_script(content_window)

    # Moving/resizing a pywebview window on Windows un-hides it as a side
    # effect (SetWindowPos with SWP_SHOWWINDOW) -- page_visible is what stops
    # a strip move from bringing a Hide-page'd reader back. See docking.py.
    dock_state = dock(
        controls_window, content_window, find_screen,
        page_visible=lambda: controller.window_visible,
    )
    controller.attach_dock(dock_state)

    # Windows should show the pair as one window: the reader becomes a tool
    # window, so it takes no taskbar button and no Alt-Tab entry of its own --
    # the Controls strip is the one that stays reachable (in the taskbar and
    # Alt-Tab) even when Hide page has tucked the reader away. Applied once
    # its native window exists, which is what `shown` marks -- and
    # deliberately *not* by making it the strip's owned window, which breaks
    # the App's exit (see window_group). See docs/adr/0010-nicegui-chrome.md.
    content_window.events.shown += lambda *_args: as_tool_window(
        content_window, on_warning=warn
    )

    # The reader's own close button hides it instead of quitting the App --
    # the same thing Hide page already does, and returning False cancels the
    # close itself (see pywebview's Event.set()) rather than destroying the
    # window. The strip has no such handler: closing it is what actually
    # exits, same as before -- see ADR-0020.
    def on_reader_closing():
        controller.toggle_window()
        return False

    content_window.events.closing += on_reader_closing

    # Geometry is tracked as it changes, because by shutdown either window
    # may already be gone and reading it then would be too late.
    reader_bounds = watch_bounds(content_window, session.get("readerBounds"))
    controls_bounds_state = watch_bounds(controls_window, session.get("controlsBounds"))
    # The startup window has done its job the moment the reader is on screen:
    # from here the Controls strip is the status line.
    content_window.events.shown += lambda *_args: splash.close()

    shutting_down = {"done": False}

    def save_session():
        session.update(
            lastUrl=controller.current_url or session.get("lastUrl") or "",
            readerBounds=reader_bounds["value"],
            controlsBounds=controls_bounds_state["value"],
            readerHidden=not controller.window_visible,
        )
        try:
            session.save()
        except OSError as err:
            warn(f"Warning: could not save the session ({err}).")

    def on_closed():
        # Closing the strip quits the App -- the reader hides instead of
        # closing (on_reader_closing above), so the strip is the one window
        # left that can actually end things.
        if shutting_down["done"]:
            return
        shutting_down["done"] = True
        playback.stop()  # silence first: shutting the Sidecar down can take seconds
        if hotkeys is not None:
            hotkeys.stop()
        save_session()
        splash.close()  # quitting before the reader ever appeared
        for window in (controls_window, content_window):
            try:
                window.destroy()
            except Exception:
                pass
        startup.stop()  # a Retry in flight must not spawn one we won't stop
        sidecar_manager.stop()

    content_window.events.closed += on_closed
    controls_window.events.closed += on_closed

    # Play/Pause, Next, and Previous Track, system-wide -- the same three keys
    # MEDIA_KEYS_JS and ui.py's ui.keyboard already handle while a window has
    # focus. Created before webview.start() so its message loop picks up the
    # hotkey window too; see media_hotkeys.py.
    hotkeys = start_media_hotkeys(
        controller.play_pause,
        lambda: controller.skip(1),
        lambda: controller.skip(-1),
        on_warning=warn,
    )

    # One icon for both windows: pywebview applies it to every window it opens,
    # so the Controls window gets it too. See app/make_icon.py for the mark.
    webview.start(icon=str(ICON_PATH))
