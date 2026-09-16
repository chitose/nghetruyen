"""Makes the App's two OS windows read as one to the shell.

The reader is a normal window; the Controls strip is a second one docked under
it (ADR-0010). Two native windows, but only one of them should be a window as
far as Windows is concerned: the strip is marked as a tool window, which takes
away its taskbar button and its Alt-Tab entry, so the App shows up once.

Deliberately *not* done: giving the strip the reader as its owner. Ownership
would also keep it above the reader and destroy it with it, but Windows then
disposes of an owned window itself -- without raising the event pywebview
deregisters windows by (`del BrowserView.instances[uid]`), and pywebview's loop
only ends once that dict is empty (`len(BrowserView.instances) == 0`). The App
then closed its windows and stayed alive. Closing the strip first from the
reader's `closing` event fixes the hang, but the exit still took 12-16s, because
pywebview's property setters wait 15s on a destroyed window's `shown` event
while the dock is still repositioning it. Three moving parts, kept in step by
hand, to avoid the reader's bottom edge occasionally covering the strip's top
one; not worth it. See docs/adr/0010-nicegui-chrome.md.

Win32 through ctypes, like the startup window (`splash.py`) and for the same
reason: pywebview has no API for window styles. Everything here is best-effort
-- if it cannot be applied, the App starts exactly as it did before with one
line in nghetruyen.log.
"""
import ctypes
import sys
from ctypes import wintypes

WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

GWL_EXSTYLE = -20

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

_USER32 = None


def _user32():
    """user32 with the prototypes this module needs.

    Without them ctypes assumes 32-bit `int`s, which is wrong for these: the
    style word comes back through a pointer-sized getter, and
    `SetWindowLongPtrW` both takes and returns one.
    """
    global _USER32
    if _USER32 is None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        _USER32 = user32
    return _USER32


def tool_window_style(ex_style: int) -> int:
    """The strip's ex-style as a tool window: no taskbar button, no Alt-Tab entry.

    Clearing WS_EX_APPWINDOW matters as much as setting WS_EX_TOOLWINDOW:
    WinForms asks for the former explicitly, and the shell honours it over the
    tool-window bit. Every other bit is left alone -- pywebview sets some of
    them itself (WS_EX_NOACTIVATE, for one).
    """
    return (ex_style & ~WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW


class Win32:
    """The calls this needs, in one object so tests can hand over a fake."""

    def hwnd(self, window):
        """A pywebview window's native handle, or None before it exists.

        pywebview sets `window.native` once the GUI has created the window; the
        Windows backend's object is the WinForms view, which has `Handle`.
        """
        native = getattr(window, "native", None)
        handle = getattr(native, "Handle", None)
        return int(handle.ToInt64()) if handle is not None else None

    def ex_style(self, hwnd: int) -> int:
        return _user32().GetWindowLongPtrW(wintypes.HWND(hwnd), GWL_EXSTYLE)

    def set_ex_style(self, hwnd: int, style: int) -> None:
        _user32().SetWindowLongPtrW(wintypes.HWND(hwnd), GWL_EXSTYLE, style)

    def refresh(self, hwnd: int) -> None:
        """A style change needs this before the window itself obeys it."""
        _user32().SetWindowPos(
            wintypes.HWND(hwnd), None, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )


def as_tool_window(controls_window, on_warning=None, api=None) -> bool:
    """Mark the Controls strip as a tool window. True when applied.

    Called once the window exists (its `shown` event); a window that is not
    there yet, a pywebview that stops exposing a native handle, or any Win32
    failure all end in `False` and one warning -- the App is unaffected either
    way.
    """
    if sys.platform != "win32":
        return False
    api = api or Win32()
    warned = []

    def warn(message: str) -> None:
        if not warned:
            warned.append(message)
            if on_warning is not None:
                on_warning(message)

    try:
        hwnd = api.hwnd(controls_window)
        if not hwnd:
            warn(
                "Warning: could not get the Controls window's native handle; "
                "it will keep its own taskbar button."
            )
            return False
        api.set_ex_style(hwnd, tool_window_style(api.ex_style(hwnd)))
        api.refresh(hwnd)
        return True
    except Exception as err:  # noqa: BLE001 -- never take the App down with it
        warn(f"Warning: could not make the Controls window a tool window ({err}).")
        return False
