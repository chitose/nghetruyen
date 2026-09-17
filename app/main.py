# app/main.py
"""Entry point.

The App is two windows. The NiceGUI chrome (address bar + Player Bar +
Options) is served on localhost by `run_ui` and shown in a frameless Controls
window docked under the reader; the native Web View renders the Chapter and
runs content.js for extraction. Both talk to the one Controller, which owns
playback state -- see docs/adr/0010-nicegui-chrome.md.

Where the App was last time (the Page, the reader's bounds, the dock height,
and whether the reader was hidden behind the strip) is read from session.json
on launch and written back on shutdown -- see
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

from api import Api
from audio_player import AudioPlayer
from config import Config
from controller import Controller
from docking import CONTROLS_HEIGHT, dock
from icon import app_icon_path
from playback import PlaybackEngine
from platform_paths import data_dir
from session import Session, restore_bounds, restore_dock_height, restore_hidden
from sidecar_client import SidecarClient
from sidecar_env import find_sidecar_dir, venv_python
from sidecar_manager import SidecarManager, SidecarStartup
from splash import make_splash
from ui import UI_HOST, UI_PORT, create_pages, run_ui
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
# The data folder keeps its original name on Windows: config.json and
# session.json live there, and renaming it would strand an existing install's
# settings. On Linux there is no such install, so this is the XDG location
# instead -- see platform_paths.data_dir and ADR-0017.
DATA_DIR = data_dir()
CONFIG_PATH = DATA_DIR / "config.json"
SESSION_PATH = DATA_DIR / "session.json"
LOG_PATH = DATA_DIR / "nghetruyen.log"

READERABLE_JS = (WEB_DIR / "readerable.js").read_text(encoding="utf-8")
CONTENT_JS = (WEB_DIR / "content.js").read_text(encoding="utf-8")


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

CHROME_BASE_URL = f"http://{UI_HOST}:{UI_PORT}/"


def inject_content_script(window) -> None:
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


def initial_layout():
    """Reader (x, y, width, height), sized so the docked Controls window fits."""
    screen = _primary_screen()
    if screen is None:
        return 80, 40, CONTENT_WIDTH, CONTENT_HEIGHT
    width = min(CONTENT_WIDTH, max(MIN_CONTENT_WIDTH, screen.width - 40))
    height = min(CONTENT_HEIGHT, max(MIN_CONTENT_HEIGHT, screen.height - CONTROLS_HEIGHT - 80))
    x = screen.x + (screen.width - width) // 2
    y = screen.y + max(20, (screen.height - (height + CONTROLS_HEIGHT)) // 2)
    return x, y, width, height


if __name__ == "__main__":
    # First thing, because the exe unpacks and the chrome takes a moment to
    # serve: this window covers that gap with the Sidecar's status, then hands
    # over to the Controls strip. See docs/adr/0013-sidecar-startup-status.md.
    splash = make_splash(icon_path=ICON_PATH, on_warning=warn)
    splash.start()

    config = Config(CONFIG_PATH)
    session = Session(SESSION_PATH)

    sidecar_dir = find_sidecar_dir(APP_DIR)
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
    controller = Controller(config, playback, sidecar_client)
    controller.attach_visualizer(Visualizer(audio_player))

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

    content_x, content_y, content_width, content_height = (
        restore_bounds(
            session.get("readerBounds"), _screen_rects(),
            min_width=MIN_CONTENT_WIDTH, min_height=MIN_CONTENT_HEIGHT,
        ) or initial_layout()
    )
    start_url = controller.start_url
    if controller.restore_last_page:
        start_url = session.get("lastUrl") or start_url

    # Hide page is remembered too, so a session spent listening with the reader
    # tucked away comes back that way. pywebview creates the window hidden
    # rather than showing and hiding it, which would flash it on screen first;
    # `hidden=True` still runs the window's `shown` handlers, so the dock, the
    # bounds tracking, and the startup window all behave as usual.
    reader_hidden = restore_hidden(session.get("readerHidden"))

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

    # Frameless and not draggable: it reads as part of the reader window, and
    # docking.dock() keeps it glued under the reader from here on.
    dock_height = restore_dock_height(session.get("dockHeight"), CONTROLS_HEIGHT)
    controls_window = webview.create_window(
        "Nghe Truyện",
        url=f"http://{UI_HOST}:{UI_PORT}/",
        x=content_x, y=content_y + content_height, width=content_width, height=dock_height,
        frameless=True, easy_drag=False,
    )
    dock_state = dock(content_window, controls_window, find_screen, height=dock_height)
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

    # Geometry is tracked as it changes, because by shutdown the window may
    # already be gone and reading it there would be too late.
    stored_bounds = session.get("readerBounds")
    bounds = {"value": list(stored_bounds) if isinstance(stored_bounds, (list, tuple)) else None}

    def track_bounds(*_args):
        try:
            bounds["value"] = [
                content_window.x, content_window.y,
                content_window.width, content_window.height,
            ]
        except Exception:
            pass

    content_window.events.shown += track_bounds
    # The startup window has done its job the moment the reader is on screen:
    # from here the Controls strip is the status line.
    content_window.events.shown += lambda *_args: splash.close()
    content_window.events.moved += track_bounds
    content_window.events.resized += track_bounds

    shutting_down = {"done": False}

    def save_session():
        session.update(
            lastUrl=controller.current_url or session.get("lastUrl") or "",
            readerBounds=bounds["value"],
            dockHeight=dock_state.height,
            readerHidden=not controller.window_visible,
        )
        try:
            session.save()
        except OSError as err:
            warn(f"Warning: could not save the session ({err}).")

    def on_closed():
        # Closing either window quits the App -- the reader can be hidden from
        # the chrome, so the Controls window is the only way out at that point.
        if shutting_down["done"]:
            return
        shutting_down["done"] = True
        playback.stop()  # silence first: shutting the Sidecar down can take seconds
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
    controller.attach_quit(on_closed)  # the chrome's close button

    # One icon for both windows: pywebview applies it to every window it opens,
    # so the Controls window gets it too. See app/make_icon.py for the mark.
    webview.start(icon=str(ICON_PATH))
