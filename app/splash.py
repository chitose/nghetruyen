"""A small startup window, shown while the App boots.

The App has nothing on screen until pywebview starts, and that only happens
once the NiceGUI server is serving -- so a launch looked like nothing happening
at all, and the Sidecar's status (whose slow parts are building `sidecar/venv`
and downloading the voice model) only appeared once the Controls strip was
already up. This window fills that gap: it is the first thing `main.py` does,
it carries the same status the strip does, and it closes when the reader window
appears. See docs/adr/0013-sidecar-startup-status.md.

Two implementations, chosen by `make_splash`: `Splash` is Win32 through ctypes
rather than tkinter -- one small window is not worth the whole Tcl/Tk runtime
in the onefile exe (ADR-0012 counts what it carries) -- and `TkSplash` is
tkinter, for Linux, where tkinter is already on disk and ctypes has no user32
to call (ADR-0017). Both are best-effort: if the window cannot be created it
reports that through `on_warning` and the App starts exactly as it did before.
"""
import ctypes
import queue
import threading
import time
from ctypes import wintypes

import platform_paths
from sidecar_manager import READY as SIDECAR_READY

WINDOW_TITLE = "Nghe Truyện"
# Layout at 96 DPI; everything is scaled by the screen's actual DPI.
WIDTH = 460
HEIGHT = 180
ICON_SIZE = 64
# A splash that has somehow outlived the launch is worse than none: the reader
# window's `shown` event is what normally takes it down, this is the backstop.
MAX_SECONDS = 60.0
POLL_MS = 80

CLASS_NAME = "NgheTruyenSplash"


def _colorref(red: int, green: int, blue: int) -> int:
    """COLORREF is 0x00BBGGRR, which is not the order anyone writes colours in."""
    return red | (green << 8) | (blue << 16)


BACKGROUND = _colorref(0x1B, 0x1B, 0x1F)
TITLE_COLOUR = _colorref(0xF2, 0xF2, 0xF2)
STATUS_COLOUR = _colorref(0xA8, 0xB0, 0xBF)


def status_line(state: str, message: str = "") -> str:
    """What the window says.

    The Sidecar's own words while it works ("Setting up sidecar/venv…",
    "Downloading the voice model…", or why it failed), and a short "Ready."
    once it answers -- the Controls strip takes over from there, so this never
    has anything to say about the Chapter.
    """
    if message:
        return message
    if state == SIDECAR_READY:
        return "Ready."
    return "Starting up…"


class Splash:
    """The startup window.

    `start()`, `set_status()` and `close()` are safe to call from any thread and
    in any order, including before the window exists: updates queue up and the
    window is taken down as soon as it can be.
    """

    def __init__(self, icon_path=None, status="Starting up…", on_warning=None,
                 seconds: float = MAX_SECONDS):
        self._icon_path = str(icon_path) if icon_path else None
        self._status = status  # what the window draws (written by its thread)
        self._wanted = status  # what the App last asked for
        self._on_warning = on_warning
        self._seconds = seconds
        self._updates = queue.Queue()
        self._closed = False
        self._warned = False
        self._thread = None

    def start(self) -> None:
        """Show the window. Does nothing off Windows, or twice."""
        if not platform_paths.is_windows() or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="splash", daemon=True)
        self._thread.start()

    def set_status(self, state: str, message: str = "") -> None:
        """The Sidecar reported something (see `sidecar_manager.SidecarStartup`)."""
        text = status_line(state, message)
        if text != self._wanted:
            self._wanted = text
            self._updates.put(text)

    def close(self) -> None:
        """Take it down; the App's own windows are up, or on their way."""
        if self._closed:
            return
        self._closed = True
        self._updates.put(None)

    # --- the window's thread ------------------------------------------------

    def _run(self) -> None:
        try:
            self._show_window()
        except Exception as err:  # noqa: BLE001 -- never take the App down with it
            self._warn_once(f"Warning: the startup window could not be shown ({err}).")

    def _warn(self, message: str) -> None:
        if self._on_warning is not None:
            self._on_warning(message)

    def _warn_once(self, message: str) -> None:
        """One line per launch, however many times Windows asks us to repaint."""
        if not self._warned:
            self._warned = True
            self._warn(message)

    def _show_window(self) -> None:
        _win32_types()
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _declare(user32, gdi32, kernel32)

        scale = _screen_scale(user32, gdi32)
        width, height = int(WIDTH * scale), int(HEIGHT * scale)
        self._gdi32 = gdi32
        self._user32 = user32
        self._fonts = _title_and_status_fonts(gdi32, scale)
        self._icon = _load_icon(user32, self._icon_path, int(ICON_SIZE * scale))
        self._brush = gdi32.CreateSolidBrush(BACKGROUND)
        self._deadline = time.monotonic() + self._seconds
        # The WNDPROC must outlive the window, hence a reference on self.
        self._wndproc = WNDPROC(self._on_message)

        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.hCursor = user32.LoadCursorW(None, wintypes.LPCWSTR(32512))  # IDC_ARROW
        wc.hbrBackground = self._brush
        wc.lpszClassName = CLASS_NAME
        if not user32.RegisterClassExW(ctypes.byref(wc)) and ctypes.get_last_error() != 1410:
            raise ctypes.WinError(ctypes.get_last_error())  # 1410: already registered

        screen_width = user32.GetSystemMetrics(0)
        screen_height = user32.GetSystemMetrics(1)
        x = (screen_width - width) // 2
        y = max(0, (screen_height - height) // 2 - int(60 * scale))
        hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW,  # above, and no taskbar button
            CLASS_NAME, WINDOW_TITLE, WS_POPUP,
            x, y, width, height, None, None, wc.hInstance, None,
        )
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        self._hwnd = hwnd
        if self._closed:  # closed before it was up: never show it at all
            user32.DestroyWindow(hwnd)
            return

        user32.SetTimer(hwnd, 1, POLL_MS, None)
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        user32.UpdateWindow(hwnd)

        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

    def _on_message(self, hwnd, message, wparam, lparam):
        try:
            return self._handle_message(hwnd, message, wparam, lparam)
        except Exception as err:  # noqa: BLE001 -- a splash must not wedge or spam
            # ctypes would otherwise print the same traceback for every message
            # this window gets. Say it once, drop the window, start the App.
            self._warn_once(f"Warning: the startup window failed ({err}).")
            try:
                self._user32.DestroyWindow(hwnd)
            except Exception:
                pass
            return 0

    def _handle_message(self, hwnd, message, wparam, lparam):
        if message == WM_PAINT:
            self._paint(hwnd)
            return 0
        if message == WM_TIMER:
            self._poll(hwnd)
            return 0
        if message == WM_CLOSE:
            self._user32.DestroyWindow(hwnd)
            return 0
        if message == WM_DESTROY:
            self._release()
            self._user32.PostQuitMessage(0)
            return 0
        return self._user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _poll(self, hwnd) -> None:
        """Called on the window's timer: apply queued status updates, and take
        the window down once the App no longer needs it."""
        redraw = False
        while True:
            try:
                text = self._updates.get_nowait()
            except queue.Empty:
                break
            if text is None:  # close()
                self._user32.DestroyWindow(hwnd)
                return
            self._status = text
            redraw = True
        if redraw:
            self._user32.InvalidateRect(hwnd, None, True)
        if self._closed or time.monotonic() > self._deadline:
            self._user32.DestroyWindow(hwnd)

    def _paint(self, hwnd) -> None:
        user32, gdi32 = self._user32, self._gdi32
        paint = PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(paint))
        try:
            rect = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rect))
            width, height = rect.right, rect.bottom
            scale = height / HEIGHT
            user32.FillRect(hdc, ctypes.byref(rect), self._brush)
            gdi32.SetBkMode(hdc, TRANSPARENT)

            top = int(58 * scale)
            if self._icon:
                size = int(ICON_SIZE * scale)
                user32.DrawIconEx(hdc, (width - size) // 2, int(24 * scale),
                                  self._icon, size, size, 0, None, DI_NORMAL)
                top = int(98 * scale)

            title_font, status_font = self._fonts
            gdi32.SetTextColor(hdc, TITLE_COLOUR)
            old_font = gdi32.SelectObject(hdc, title_font)
            title = wintypes.RECT(int(10 * scale), top, width - int(10 * scale), top + int(28 * scale))
            user32.DrawTextW(hdc, WINDOW_TITLE, -1, ctypes.byref(title),
                             DT_CENTER | DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX)

            gdi32.SetTextColor(hdc, STATUS_COLOUR)
            gdi32.SelectObject(hdc, status_font)
            status_top = top + int(30 * scale)
            status = wintypes.RECT(int(20 * scale), status_top, width - int(20 * scale),
                                   status_top + int(46 * scale))
            user32.DrawTextW(hdc, self._status, -1, ctypes.byref(status),
                             DT_CENTER | DT_WORDBREAK | DT_NOPREFIX)
            gdi32.SelectObject(hdc, old_font)
        finally:
            user32.EndPaint(hwnd, ctypes.byref(paint))

    def _release(self) -> None:
        for handle in (*self._fonts, self._icon, self._brush):
            if handle:
                self._gdi32.DeleteObject(handle)
        self._fonts = (None, None)
        self._icon = None
        self._brush = None
        self._hwnd = None


class TkSplash:
    """The startup window on Linux, with tkinter instead of user32.

    Same three safe-from-any-thread calls as `Splash` and the same job: cover
    the launch with the Sidecar's status. A first Linux run provisions a
    ~700 MB venv and downloads a ~1.3 GB voice model before anything else can
    say so, so on Linux this window is the only feedback there is for minutes.

    Everything is best-effort, like the Win32 one: no tkinter, no display (an
    SSH session, a bare tty), or any Tk failure ends in one warning and a
    no-op, never in a broken launch.
    """

    def __init__(self, icon_path=None, status="Starting up…", on_warning=None,
                 seconds: float = MAX_SECONDS):
        self._icon_path = str(icon_path) if icon_path else None
        self._status = status  # what the window draws (written by its thread)
        self._wanted = status  # what the App last asked for
        self._on_warning = on_warning
        self._seconds = seconds
        self._updates = queue.Queue()
        self._closed = False
        self._warned = False
        self._thread = None

    def start(self) -> None:
        """Show the window. Does nothing twice."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="splash", daemon=True)
        self._thread.start()

    def set_status(self, state: str, message: str = "") -> None:
        """The Sidecar reported something (see `sidecar_manager.SidecarStartup`)."""
        text = status_line(state, message)
        if text != self._wanted:
            self._wanted = text
            self._updates.put(text)

    def close(self) -> None:
        """Take it down; the App's own windows are up, or on their way."""
        if self._closed:
            return
        self._closed = True
        self._updates.put(None)

    def _run(self) -> None:
        # Imported here rather than at module scope: splash.py is imported by
        # main.py on Windows too, where Tk is never used, and a missing tkinter
        # must not stop the App importing its own startup window.
        try:
            import tkinter as tk
        except Exception as err:  # noqa: BLE001 -- no tkinter is a warning, not a crash
            self._warn_once(
                f"Warning: no startup window (tkinter is not available: {err})."
            )
            return
        try:
            self._show(tk)
        except Exception as err:  # noqa: BLE001 -- never take the App down with it
            self._warn_once(f"Warning: the startup window could not be shown ({err}).")

    def _show(self, tk) -> None:
        root = tk.Tk()
        try:
            root.title(WINDOW_TITLE)
            root.overrideredirect(True)  # the strip look the Win32 one has
            root.attributes("-topmost", True)
            root.configure(bg=_TK_BACKGROUND)
            self._set_icon(tk, root)

            frame = tk.Frame(root, bg=_TK_BACKGROUND, padx=24, pady=18)
            frame.pack(fill="both", expand=True)
            if self._icon is not None:  # a PhotoImage, or None when unreadable
                label = tk.Label(frame, image=self._icon, bg=_TK_BACKGROUND)
                label.pack()
            tk.Label(
                frame, text=WINDOW_TITLE, bg=_TK_BACKGROUND, fg=_TK_TITLE,
                font=("Sans", 13, "bold"),
            ).pack(pady=(10, 4))
            status = tk.Label(
                frame, text=self._status, bg=_TK_BACKGROUND, fg=_TK_STATUS,
                font=("Sans", 10), wraplength=int(WIDTH * 0.82), justify="center",
            )
            status.pack()

            root.update_idletasks()
            self._centre(root)
            root.deiconify()
            self._pump(tk, root, status)
        finally:
            try:
                root.destroy()
            except Exception:
                pass

    def _set_icon(self, tk, root) -> None:
        self._icon = None
        if not self._icon_path:
            return
        try:
            # PNG, not the Windows .ico: see icon.py. Kept as an attribute so
            # Tk does not garbage-collect the image out from under the label.
            image = tk.PhotoImage(file=self._icon_path)
            if image.width() > ICON_SIZE:  # the 256px asset is the only one there is
                image = image.subsample(max(1, round(image.width() / ICON_SIZE)))
            self._icon = image
            root.iconphoto(True, image)
        except Exception:
            self._icon = None  # an icon is not worth failing the window for

    def _centre(self, root) -> None:
        try:
            width, height = root.winfo_reqwidth(), root.winfo_reqheight()
            x = (root.winfo_screenwidth() - width) // 2
            y = max(0, (root.winfo_screenheight() - height) // 2 - 60)
            root.geometry(f"+{max(0, x)}+{y}")
        except Exception:
            pass  # a window at the default position still does the job

    def _pump(self, tk, root, status) -> None:
        """Tk's own loop, driven by `after` so the update queue is drained
        without a second thread touching Tk (which is not thread-safe)."""
        deadline = time.monotonic() + self._seconds

        def tick():
            redraw = False
            while True:
                try:
                    text = self._updates.get_nowait()
                except queue.Empty:
                    break
                if text is None:  # close()
                    root.destroy()
                    return
                self._status = text
                redraw = True
            if redraw:
                status.configure(text=self._status)
            if self._closed or time.monotonic() > deadline:
                root.destroy()
                return
            root.after(POLL_MS, tick)

        root.after(POLL_MS, tick)
        try:
            root.mainloop()
        except Exception:
            pass  # torn down underneath us; the App is unaffected either way

    def _warn(self, message: str) -> None:
        if self._on_warning is not None:
            self._on_warning(message)

    def _warn_once(self, message: str) -> None:
        if not self._warned:
            self._warned = True
            self._warn(message)


def make_splash(icon_path=None, on_warning=None):
    """The startup window for this platform, or a no-op stand-in.

    `main.py` does not care which: it calls `start()`, `set_status()` and
    `close()` on whatever comes back, in any order and from any thread.
    """
    if platform_paths.is_windows():
        return Splash(icon_path=icon_path, on_warning=on_warning)
    return TkSplash(icon_path=icon_path, on_warning=on_warning)


# The tkinter window's colours, from the same palette as the Win32 window's
# COLORREFs (which are 0x00BBGGRR and so not written the same way round).
_TK_BACKGROUND = "#1B1B1F"
_TK_TITLE = "#F2F2F2"
_TK_STATUS = "#A8B0BF"


def _screen_scale(user32, gdi32) -> float:
    """How much bigger than 96 DPI this process's screen really is.

    Read from the screen DC rather than GetDpiForSystem, because it accounts
    for the process being DPI-unaware: Windows then scales the whole window for
    us, and scaling again here would make it twice the size it should be.
    """
    dc = user32.GetDC(None)
    try:
        return (gdi32.GetDeviceCaps(dc, LOGPIXELSX) or 96) / 96.0
    finally:
        user32.ReleaseDC(None, dc)


def _title_and_status_fonts(gdi32, scale: float):
    return (
        _font(gdi32, -int(21 * scale), FW_SEMIBOLD),
        _font(gdi32, -int(15 * scale), FW_NORMAL),
    )


def _font(gdi32, height: int, weight: int):
    return gdi32.CreateFontW(
        height, 0, 0, 0, weight, 0, 0, 0,
        DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
        CLEARTYPE_QUALITY, DEFAULT_PITCH, "Segoe UI",
    )


def _load_icon(user32, path, size: int):
    """The App's own icon, or None if it cannot be read (the window is still
    worth showing) -- main.py hands over the same assets/ file the windows use."""
    if not path:
        return None
    return user32.LoadImageW(None, path, IMAGE_ICON, size, size, LR_LOADFROMFILE) or None


# --- Win32 ------------------------------------------------------------------

LRESULT = ctypes.c_ssize_t


def _win32_types() -> None:
    """Define the Win32 ctypes types, the first time a splash is created.

    Deliberately not at import time. `ctypes.WINFUNCTYPE` and `ctypes.WinDLL`
    do not exist off Windows, and this module is imported by `main.py` on
    every platform because `make_splash` lives here -- so defining WNDPROC at
    module scope made `import splash` itself fail on Linux (ADR-0017). Nothing
    in this function runs unless a Win32 splash is actually being shown.
    """
    global WNDPROC, WNDCLASSEXW, PAINTSTRUCT
    if "WNDPROC" in globals():
        return
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM)

    WNDCLASSEXW = type("WNDCLASSEXW", (ctypes.Structure,), {"_fields_": [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]})

    # ctypes.wintypes has RECT and MSG but not this one.
    PAINTSTRUCT = type("PAINTSTRUCT", (ctypes.Structure,), {"_fields_": [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]})


def _declare(user32, gdi32, kernel32) -> None:
    """Prototypes for every call below.

    Without them ctypes assumes `int` for arguments and return values, which
    breaks on the 64-bit side of the ABI: a window style above INT_MAX raises
    OverflowError (`WS_POPUP` is 0x80000000), and HANDLEs come back mangled.
    """
    user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    user32.RegisterClassExW.restype = wintypes.ATOM

    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND

    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT

    user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
    user32.LoadCursorW.restype = wintypes.HANDLE

    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.LoadImageW.restype = wintypes.HANDLE

    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int

    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int

    user32.SetTimer.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.LPVOID]
    user32.SetTimer.restype = wintypes.UINT

    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.UpdateWindow.argtypes = [wintypes.HWND]
    user32.UpdateWindow.restype = wintypes.BOOL
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT), wintypes.BOOL]
    user32.InvalidateRect.restype = wintypes.BOOL
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = wintypes.BOOL

    user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.BeginPaint.restype = wintypes.HDC
    user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.EndPaint.restype = wintypes.BOOL
    user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
    user32.FillRect.restype = ctypes.c_int
    user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int,
                                 ctypes.POINTER(wintypes.RECT), wintypes.UINT]
    user32.DrawTextW.restype = ctypes.c_int
    user32.DrawIconEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HANDLE,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.HBRUSH,
                                  wintypes.UINT]
    user32.DrawIconEx.restype = wintypes.BOOL

    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                   wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = ctypes.c_int
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = LRESULT
    user32.PostQuitMessage.argtypes = [ctypes.c_int]

    gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
    gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
    gdi32.CreateFontW.argtypes = [
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPCWSTR,
    ]
    gdi32.CreateFontW.restype = wintypes.HFONT
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.SetBkMode.restype = ctypes.c_int
    gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
    gdi32.SetTextColor.restype = wintypes.COLORREF
    gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.GetDeviceCaps.restype = ctypes.c_int

    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE


WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_PAINT = 0x000F
WM_TIMER = 0x0113
WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
SW_SHOWNOACTIVATE = 4
DT_CENTER = 0x0001
DT_VCENTER = 0x0004
DT_SINGLELINE = 0x0020
DT_WORDBREAK = 0x0010
DT_NOPREFIX = 0x0800
TRANSPARENT = 1
DEFAULT_CHARSET = 1
OUT_DEFAULT_PRECIS = 0
CLIP_DEFAULT_PRECIS = 0
CLEARTYPE_QUALITY = 5
DEFAULT_PITCH = 0
FW_NORMAL = 400
FW_SEMIBOLD = 600
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
DI_NORMAL = 0x0003
LOGPIXELSX = 88
