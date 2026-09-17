"""Makes the App's two OS windows read as one to the shell.

The Controls strip is a normal window; the reader is a second one docked
above it (ADR-0010). Two native windows, but only one of them should be a
window as far as the shell is concerned: the reader is marked as a tool
window, which takes away its taskbar button and its Alt-Tab entry, so the App
shows up once -- and stays reachable through the strip even when Hide page
has tucked the reader away (it would otherwise take the App's only taskbar
entry with it).

Deliberately *not* done: giving either window the other as its owner.
Ownership would also keep it above its owner and destroy it with it, but
Windows then disposes of an owned window itself -- without raising the event
pywebview deregisters windows by (`del BrowserView.instances[uid]`), and
pywebview's loop only ends once that dict is empty
(`len(BrowserView.instances) == 0`). The App then closed its windows and
stayed alive. Closing the owned window first from the owner's `closing` event
fixes the hang, but the exit still took 12-16s, because pywebview's property
setters wait 15s on a destroyed window's `shown` event while the dock is
still repositioning it. Three moving parts, kept in step by hand, to avoid
one window's edge occasionally covering the other's; not worth it. See
docs/adr/0010-nicegui-chrome.md.

Two implementations, because the shell is a different shell: Win32 ex-styles
through ctypes (`user32`) on Windows, and the EWMH `_NET_WM_STATE_SKIP_TASKBAR`
/`_SKIP_PAGER` hints through `libX11` on Linux (ADR-0017). Neither pywebview
nor GTK exposes window styles, so both are ctypes for the same reason: pywebview
has no API for this. Everything here is best-effort -- if it cannot be applied,
the App starts exactly as it did before with one line in nghetruyen.log. On
Linux a Wayland session is the ordinary case where it cannot be applied: the
GTK window is not an X11 window there, so the reader simply gets its own
taskbar entry and both windows are listed separately.
"""
import ctypes
import ctypes.util

import platform_paths

WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

GWL_EXSTYLE = -20

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

# EWMH, as X11 atom names. A window manager that honours these gives the window
# no taskbar button and no pager entry -- the same two things the Windows
# WS_EX_TOOLWINDOW bit takes away.
NET_WM_STATE = "_NET_WM_STATE"
NET_WM_STATE_SKIP_TASKBAR = "_NET_WM_STATE_SKIP_TASKBAR"
NET_WM_STATE_SKIP_PAGER = "_NET_WM_STATE_SKIP_PAGER"
XA_ATOM = 4

_USER32 = None


def _user32():
    """user32 with the prototypes this module needs.

    Without them ctypes assumes 32-bit `int`s, which is wrong for these: the
    style word comes back through a pointer-sized getter, and
    `SetWindowLongPtrW` both takes and returns one.
    """
    global _USER32
    if _USER32 is None:
        from ctypes import wintypes  # Windows-only types, imported where used

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
    """A window's ex-style as a tool window: no taskbar button, no Alt-Tab entry.

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
        from ctypes import wintypes

        return _user32().GetWindowLongPtrW(wintypes.HWND(hwnd), GWL_EXSTYLE)

    def set_ex_style(self, hwnd: int, style: int) -> None:
        from ctypes import wintypes

        _user32().SetWindowLongPtrW(wintypes.HWND(hwnd), GWL_EXSTYLE, style)

    def refresh(self, hwnd: int) -> None:
        """A style change needs this before the window itself obeys it."""
        from ctypes import wintypes

        _user32().SetWindowPos(
            wintypes.HWND(hwnd), None, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )


class X11:
    """The calls the Linux path needs, in one object so tests can fake it.

    `xid()` is the platform-specific half, and it is why this is best-effort
    rather than a guarantee: the GTK backend's native object is a Gtk.Window,
    and a Gtk.Window only has an X11 window ID when GDK is running on X11. On
    a Wayland session there is nothing to ask for, so this says so and the
    caller keeps its taskbar entry.
    """

    def xid(self, window):
        """A pywebview window's X11 window ID, or None when it has none."""
        native = getattr(window, "native", None)
        if native is None:
            return None
        # GTK3 exposes the X11 window through the GDK window; GTK4 and
        # Wayland do not, and `get_xid` is absent there.
        gdk_window = getattr(native, "get_window", None)
        gdk_window = gdk_window() if callable(gdk_window) else None
        get_xid = getattr(gdk_window, "get_xid", None)
        if not callable(get_xid):
            return None
        return int(get_xid())

    def set_skip_hints(self, xid: int) -> None:
        _set_skip_hints(xid)


def _libx11():
    """libX11 with the prototypes this module needs, or None when absent.

    `ctypes.util.find_library` is what makes this work on both a merged-/usr
    distro (where the library has no path of its own) and one without it.
    """
    name = ctypes.util.find_library("X11")
    if not name:
        return None
    x11 = ctypes.CDLL(name)
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.restype = ctypes.c_int
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XChangeProperty.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
        ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int,
    ]
    x11.XChangeProperty.restype = ctypes.c_int
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XFlush.restype = ctypes.c_int
    return x11


def x11_skip_taskbar_hints(x11, display, xid: int,
                           net_wm_state: int, atoms: list) -> None:
    """Set `_NET_WM_STATE` to `atoms` -- the EWMH skip hints.

    `_NET_WM_STATE` is a list of ATOM values, so each hint is interned and the
    whole list is written in one `XChangeProperty`; a window manager that
    implements EWMH then drops the window's taskbar button and pager entry.
    """
    values = (ctypes.c_ulong * len(atoms))(*atoms)
    x11.XChangeProperty(
        display, xid, net_wm_state, XA_ATOM, 32, 0, values, len(atoms),
    )
    x11.XFlush(display)


def _set_skip_hints(xid: int) -> None:
    x11 = _libx11()
    if x11 is None:
        raise OSError("libX11 was not found")
    display = x11.XOpenDisplay(None)
    if not display:
        raise OSError("no X display")
    try:
        net_wm_state = x11.XInternAtom(display, NET_WM_STATE.encode(), 0)
        atoms = [
            x11.XInternAtom(display, NET_WM_STATE_SKIP_TASKBAR.encode(), 0),
            x11.XInternAtom(display, NET_WM_STATE_SKIP_PAGER.encode(), 0),
        ]
        x11_skip_taskbar_hints(x11, display, xid, net_wm_state, atoms)
    finally:
        x11.XCloseDisplay(display)


def _warn_once(on_warning):
    """One line per launch, whatever the shell refused to do."""
    warned = []

    def warn(message: str) -> None:
        if not warned:
            warned.append(message)
            if on_warning is not None:
                on_warning(message)

    return warn


def as_tool_window(window, on_warning=None, api=None) -> bool:
    """Mark `window` as a tool window. True when applied.

    Called once the window exists (its `shown` event); a window that is not
    there yet, a pywebview that stops exposing a native handle, a Wayland
    session, or any failure in the platform call all end in `False` and one
    warning -- the App is unaffected either way.
    """
    warn = _warn_once(on_warning)

    if platform_paths.is_windows():
        return _as_tool_window_win32(window, warn, api)
    return _as_tool_window_x11(window, warn, api)


def _as_tool_window_win32(window, warn, api=None) -> bool:
    api = api or Win32()
    try:
        hwnd = api.hwnd(window)
        if not hwnd:
            warn(
                "Warning: could not get the window's native handle; "
                "it will keep its own taskbar button."
            )
            return False
        api.set_ex_style(hwnd, tool_window_style(api.ex_style(hwnd)))
        api.refresh(hwnd)
        return True
    except Exception as err:  # noqa: BLE001 -- never take the App down with it
        warn(f"Warning: could not make the window a tool window ({err}).")
        return False


def _as_tool_window_x11(window, warn, api=None) -> bool:
    api = api or X11()
    try:
        xid = api.xid(window)
        if not xid:
            warn(
                "Warning: the window has no X11 window ID (a Wayland "
                "session), so it will keep its own taskbar button."
            )
            return False
        api.set_skip_hints(xid)
        return True
    except Exception as err:  # noqa: BLE001 -- never take the App down with it
        warn(f"Warning: could not make the window a tool window ({err}).")
        return False
