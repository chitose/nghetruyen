"""Checks that Windows sees the App as one window: one taskbar button, one
Alt-Tab entry.

    venv\\Scripts\\python.exe check_windows.py

Run it while the App is running. The reader is a normal window; the Controls
strip should be a *tool window* (see docs/adr/0010-nicegui-chrome.md), which is
what keeps the strip out of the taskbar and out of Alt-Tab. Window styles cannot
be asserted on from the test suite -- a test would have to open two real windows
-- so this reads them back the way the shell does: the strip must have
WS_EX_TOOLWINDOW and must not have WS_EX_APPWINDOW.

It must also have **no owner**. Ownership looks like the obvious next step (the
strip would stay above the reader and go away with it), but Windows then disposes
of the strip without raising the event pywebview deregisters windows by, so the
App closes its windows and stays alive. An owner here is therefore a problem,
not a pass -- see `window_group.py`.

The two windows are found by the titles `main.py` creates, not by process: the
App's process owns a dozen helper windows of its own (GDI+, the .NET broadcast
window, the onefile unpacker's hidden window, IME), and matching the process
would sweep all of them into the report.

Exits 1 when a problem is found (or the App is not running), so it can be used
as a smoke-test step.
"""
import ctypes
import os
import sys
from ctypes import wintypes

WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_CAPTION = 0x00C00000
GWL_STYLE = -16
GWL_EXSTYLE = -20
GW_OWNER = 4

READER_TITLE = "Nghe Truyện"
STRIP_TITLE = "Nghe Truyện -- Controls"
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _user32():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    return user32


def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def process_name(kernel32, pid: int) -> str:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return "?"
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return os.path.basename(buffer.value)
        return "?"
    finally:
        kernel32.CloseHandle(handle)


def windows_of_interest(user32, kernel32) -> dict:
    """The App's two windows, with the styles and owner the shell cares about."""
    found = {"reader": None, "strip": None}
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _lparam):
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, 512)
        if title.value not in (READER_TITLE, STRIP_TITLE):
            return True
        style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        entry = {
            "hwnd": int(hwnd),
            "title": title.value,
            "process": process_name(kernel32, pid.value),
            "visible": bool(user32.IsWindowVisible(hwnd)),
            "owner": int(user32.GetWindow(hwnd, GW_OWNER) or 0),
            "style": style,
            "ex_style": user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE),
        }
        found["strip" if title.value == STRIP_TITLE else "reader"] = entry
        return True

    user32.EnumWindows(callback_type(visit), 0)
    return found


def report(found: dict) -> int:
    reader, strip = found["reader"], found["strip"]
    if reader is None and strip is None:
        print("No App windows found -- is the App running?")
        return 1

    for label, window in (("reader", reader), ("strip", strip)):
        if window is None:
            continue
        print(
            f"{label:6} hwnd={window['hwnd']:<10} visible={str(window['visible']):<5} "
            f"owner={window['owner']:<10} title={window['title']!r} ({window['process']})"
        )
        print(
            f"       toolwindow={bool(window['ex_style'] & WS_EX_TOOLWINDOW)} "
            f"appwindow={bool(window['ex_style'] & WS_EX_APPWINDOW)} "
            f"caption={bool(window['style'] & WS_CAPTION)}"
        )

    problems = []
    if strip is None:
        problems.append("the Controls strip was not found (is the App past startup?)")
    else:
        if not strip["ex_style"] & WS_EX_TOOLWINDOW:
            problems.append("the strip is not a tool window: it takes an Alt-Tab entry")
        if strip["ex_style"] & WS_EX_APPWINDOW:
            problems.append("the strip still asks for a taskbar button (WS_EX_APPWINDOW)")
        if strip["owner"]:
            # Deliberate: an owned window is disposed by Windows without raising
            # the event pywebview deregisters windows by, which leaves the App
            # alive with no windows. See window_group.py.
            problems.append(
                "the strip is owned by another window: Windows will dispose it "
                "behind pywebview's back and the App will not exit"
            )

    if problems:
        print()
        for problem in problems:
            print(f"PROBLEM: {problem}")
        return 1

    print()
    print("OK: one taskbar button and one Alt-Tab entry -- the strip is a tool window.")
    return 0


if __name__ == "__main__":
    if sys.platform != "win32":
        print("This checks Windows window styles; nothing to do here.")
        sys.exit(0)
    sys.exit(report(windows_of_interest(_user32(), _kernel32())))
