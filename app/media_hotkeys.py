"""Global media-key hotkeys: Play/Pause, Next Track, Previous Track, working
even when none of the App's windows has focus.

`main.py` already handles these as ordinary keydown events while a window has
focus (see MEDIA_KEYS_JS and ui.py's `ui.keyboard`) -- this is the same three
keys, caught system-wide instead, with `RegisterHotKey`.

`RegisterHotKey` delivers `WM_HOTKEY` to a native window, so this creates one
of its own rather than subclassing pywebview's -- subclassing a WinForms
control's WNDPROC is a much larger, more fragile surface for the same result.
It relies on a Windows message queue being per-thread, not per-window: the
window is created on the main thread before `webview.start()`, so the message
loop that call runs (WinForms' `Application.Run()`) dispatches this window's
`WM_HOTKEY` too, without this module running a loop of its own. The window is
never shown -- no style, no `ShowWindow` call -- so it has no taskbar button
or Alt-Tab entry to begin with.

Windows only, and best-effort like window_group.py: a missing user32 call, a
hotkey another app already owns, or any other failure ends in one warning and
the App runs exactly as it did without this -- the in-window keys still work.
"""
import ctypes

import platform_paths

WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000  # Vista+: do not refire while the key is held down

VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3

PLAY_PAUSE_ID = 1
NEXT_ID = 2
PREV_ID = 3

ERROR_CLASS_ALREADY_EXISTS = 1410

_CLASS_NAME = "NgheTruyenMediaHotkeys"


def hotkey_vks() -> dict:
    """Hotkey id -> virtual-key code, in one place so register and unregister
    (and the tests) agree on what is bound."""
    return {
        PLAY_PAUSE_ID: VK_MEDIA_PLAY_PAUSE,
        NEXT_ID: VK_MEDIA_NEXT_TRACK,
        PREV_ID: VK_MEDIA_PREV_TRACK,
    }


class Win32:
    """The ctypes calls this needs, in one object so tests can hand over a fake."""

    def __init__(self):
        self._user32 = None
        self._wndproc = None  # kept alive here -- see create_window()

    def _dll(self):
        if self._user32 is None:
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.DefWindowProcW.restype = ctypes.c_ssize_t
            user32.DefWindowProcW.argtypes = [
                wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM,
            ]
            user32.RegisterClassW.restype = wintypes.ATOM
            user32.CreateWindowExW.restype = wintypes.HWND
            user32.RegisterHotKey.restype = wintypes.BOOL
            user32.RegisterHotKey.argtypes = [
                wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
            ]
            user32.UnregisterHotKey.restype = wintypes.BOOL
            user32.DestroyWindow.restype = wintypes.BOOL
            self._user32 = user32
        return self._user32

    def create_window(self, on_message):
        """A hidden window whose WNDPROC calls `on_message(hwnd, msg, wparam,
        lparam)`; its handle, or None on failure.

        `on_message` returning None means "not handled", same as a real
        WNDPROC would signal by falling through to `DefWindowProcW`.
        """
        from ctypes import wintypes

        user32 = self._dll()
        wndproc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM,
        )

        def wndproc(hwnd, msg, wparam, lparam):
            handled = on_message(hwnd, msg, wparam, lparam)
            return handled if handled is not None else user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        # Kept on self: ctypes does not hold a reference to a WINFUNCTYPE
        # instance handed to C, and a GC'd callback crashes the process the
        # next time Windows calls it.
        self._wndproc = wndproc_type(wndproc)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", ctypes.c_uint),
                ("lpfnWndProc", wndproc_type),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        wndclass = WNDCLASSW(lpfnWndProc=self._wndproc, lpszClassName=_CLASS_NAME)
        registered = user32.RegisterClassW(ctypes.byref(wndclass))
        if not registered and ctypes.get_last_error() != ERROR_CLASS_ALREADY_EXISTS:
            return None
        hwnd = user32.CreateWindowExW(
            0, _CLASS_NAME, _CLASS_NAME, 0, 0, 0, 0, 0, None, None, None, None,
        )
        return hwnd or None

    def register_hotkey(self, hwnd, hotkey_id: int, vk: int) -> bool:
        return bool(self._dll().RegisterHotKey(hwnd, hotkey_id, MOD_NOREPEAT, vk))

    def unregister_hotkey(self, hwnd, hotkey_id: int) -> None:
        self._dll().UnregisterHotKey(hwnd, hotkey_id)

    def destroy_window(self, hwnd) -> None:
        self._dll().DestroyWindow(hwnd)


class MediaHotkeys:
    """Owns the hidden window and dispatches its hotkeys to the three handlers."""

    def __init__(self, on_play_pause, on_next, on_previous, on_warning=None, api=None):
        self._handlers = {
            PLAY_PAUSE_ID: on_play_pause,
            NEXT_ID: on_next,
            PREV_ID: on_previous,
        }
        self._warn = on_warning or (lambda message: None)
        self._api = api or Win32()
        self._hwnd = None

    def _on_message(self, _hwnd, msg, wparam, _lparam):
        if msg != WM_HOTKEY:
            return None
        handler = self._handlers.get(wparam)
        if handler is not None:
            try:
                handler()
            except Exception:  # noqa: BLE001 -- never take the message loop down with it
                pass
        return 0

    def start(self) -> bool:
        try:
            self._hwnd = self._api.create_window(self._on_message)
            if not self._hwnd:
                self._warn(
                    "Warning: could not create the media-hotkey window; "
                    "global media keys will not work."
                )
                return False
            missing = [
                hotkey_id for hotkey_id, vk in hotkey_vks().items()
                if not self._api.register_hotkey(self._hwnd, hotkey_id, vk)
            ]
            if missing:
                self._warn(
                    "Warning: could not register global media-key hotkeys "
                    f"{missing}; another app may already own them."
                )
                return False
            return True
        except Exception as err:  # noqa: BLE001 -- never take the App down with it
            self._warn(f"Warning: could not set up global media-key hotkeys ({err}).")
            return False

    def stop(self) -> None:
        if self._hwnd is None:
            return
        try:
            for hotkey_id in hotkey_vks():
                self._api.unregister_hotkey(self._hwnd, hotkey_id)
            self._api.destroy_window(self._hwnd)
        except Exception:  # noqa: BLE001 -- shutdown must not raise
            pass
        self._hwnd = None


def start(on_play_pause, on_next, on_previous, on_warning=None, api=None):
    """Best-effort global media-key hotkeys.

    None on Linux (no RegisterHotKey equivalent wired up here) or when the
    Windows path fails -- the in-window handling still works either way.
    Call `.stop()` on the result (if not None) at shutdown.
    """
    if not platform_paths.is_windows():
        return None
    hotkeys = MediaHotkeys(on_play_pause, on_next, on_previous, on_warning=on_warning, api=api)
    return hotkeys if hotkeys.start() else None
