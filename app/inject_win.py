"""Text injection into whatever Windows application currently has focus.

Three interchangeable backends, chosen in config.json:

``sendinput``  Types Unicode characters directly with the SendInput API (the
               same call a real keyboard driver ends in). Fastest and works with
               every classic Win32/WPF/Qt control, and it does not disturb the
               clipboard. It cannot reach windows owned by a *higher* integrity
               level than this process (an app running as Administrator, or the
               UAC prompt / lock screen) -- Windows blocks that by design
               (UIPI). Run this app elevated if you need to dictate into
               elevated windows.
``clipboard``  Sets the clipboard and sends Ctrl+V. Slower and it overwrites
               the clipboard, but it survives some exotic controls (Chromium
               rich-text editors, remote sessions) where raw key injection
               drops characters. The previous clipboard content is restored.
``stdout``     Prints instead of typing -- used for testing without a desktop
               session (e.g. over SSH) and for the ``--wav`` self test.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import time

IS_WINDOWS = sys.platform == "win32"

# --------------------------------------------------------------------- SendInput
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_BACK = 0x08
VK_CONTROL = 0x11
VK_V = 0x56
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

if IS_WINDOWS:
    ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wt.WORD),
            ("wScan", wt.WORD),
            ("dwFlags", wt.DWORD),
            ("time", wt.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
            ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


def _key_event(vk: int = 0, scan: int = 0, flags: int = 0) -> "INPUT":
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return inp


def _send(inputs: list) -> None:
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    sent = ctypes.windll.user32.SendInput(n, arr, ctypes.sizeof(INPUT))
    if sent != n:
        raise ctypes.WinError(ctypes.get_last_error())


def foreground_info() -> str:
    """Describe the window that will receive typed text (for the log).

    When "the hotkey works but nothing appears" the first question is *where*
    the characters went: a different window, or a window owned by an elevated
    process (UIPI blocks SendInput into it). This makes that visible.
    """
    if not IS_WINDOWS:
        return "not-windows"
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "no foreground window"
        n = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, title, n + 1)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        return f"hwnd={hwnd} class={cls.value} title={title.value!r}"
    except Exception as exc:  # noqa: BLE001
        return f"unknown ({exc})"


class BaseInjector:
    name = "base"

    def type_text(self, text: str) -> None:
        raise NotImplementedError

    def press_backspace(self, count: int = 1) -> None:
        """Delete ``count`` characters (not words -- callers convert)."""
        raise NotImplementedError

    def press_enter(self) -> None:
        raise NotImplementedError

    def target_info(self) -> str:
        """Where the next character will land -- reported in the log."""
        return "stdout"

    def close(self) -> None:
        pass


class StdoutInjector(BaseInjector):
    """Writes to stdout so the pipeline can be tested without a desktop."""

    name = "stdout"

    def type_text(self, text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    def press_backspace(self, count: int = 1) -> None:
        sys.stdout.write("\b" * count)
        sys.stdout.flush()

    def press_enter(self) -> None:
        sys.stdout.write("\n")
        sys.stdout.flush()


class SendInputInjector(BaseInjector):
    name = "sendinput"

    def type_text(self, text: str) -> None:
        if not IS_WINDOWS or not text:
            return
        # A raw U+000A in the unicode stream is ignored by Chrome and most
        # editors, so a configured newline separator is sent as a real Enter.
        while "\n" in text:
            head, text = text.split("\n", 1)
            if head:
                self.type_text(head)
            self.press_enter()
        if not text:
            return
        events = []
        for ch in text:
            # smashing emoji/surrogate pairs into UTF-16 happens naturally here
            for unit in ch.encode("utf-16-le").decode("utf-16-le"):
                code = ord(unit)
                events.append(_key_event(scan=code, flags=KEYEVENTF_UNICODE))
                events.append(_key_event(scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        _send(events)

    def press_backspace(self, count: int = 1) -> None:
        if not IS_WINDOWS or count <= 0:
            return
        events = []
        for _ in range(count):
            events.append(_key_event(vk=VK_BACK))
            events.append(_key_event(vk=VK_BACK, flags=KEYEVENTF_KEYUP))
        _send(events)

    def press_enter(self) -> None:
        if IS_WINDOWS:
            _send([_key_event(vk=0x0D), _key_event(vk=0x0D, flags=KEYEVENTF_KEYUP)])


    def target_info(self) -> str:
        return foreground_info()


class ClipboardInjector(BaseInjector):
    """Clipboard + Ctrl+V, restoring whatever the user had copied before."""

    name = "clipboard"

    def __init__(self, restore_clipboard: bool = True):
        self.restore_clipboard = restore_clipboard
        self._saved: str | None = None
        if IS_WINDOWS and restore_clipboard:
            self._saved = self._get_clipboard()

    # -- clipboard helpers -------------------------------------------------
    @staticmethod
    def _get_clipboard() -> str | None:
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        if not u32.OpenClipboard(None):
            return None
        try:
            if not u32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return None
            handle = u32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return None
            ptr = k32.GlobalLock(handle)
            try:
                return ctypes.wstring_at(ptr)
            finally:
                k32.GlobalUnlock(handle)
        finally:
            u32.CloseClipboard()

    @staticmethod
    def _set_clipboard(text: str) -> bool:
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        if not u32.OpenClipboard(None):
            return False
        try:
            u32.EmptyClipboard()
            buf = ctypes.create_unicode_buffer(text)
            size = ctypes.sizeof(buf)
            handle = k32.GlobalAlloc(GMEM_MOVEABLE, size)
            ptr = k32.GlobalLock(handle)
            ctypes.memmove(ptr, buf, size)
            k32.GlobalUnlock(handle)
            u32.SetClipboardData(CF_UNICODETEXT, handle)
            return True
        finally:
            u32.CloseClipboard()

    def type_text(self, text: str) -> None:
        if not IS_WINDOWS or not text:
            return
        before = self._get_clipboard()
        if not self._set_clipboard(text):
            return
        time.sleep(0.02)
        _send([
            _key_event(vk=VK_CONTROL), _key_event(vk=VK_V),
            _key_event(vk=VK_V, flags=KEYEVENTF_KEYUP), _key_event(vk=VK_CONTROL, flags=KEYEVENTF_KEYUP),
        ])
        time.sleep(0.03)
        if self.restore_clipboard and before is not None:
            self._set_clipboard(before)

    def press_backspace(self, count: int = 1) -> None:
        if not IS_WINDOWS or count <= 0:
            return
        _send([_key_event(vk=VK_BACK), _key_event(vk=VK_BACK, flags=KEYEVENTF_KEYUP)] * count)

    def press_enter(self) -> None:
        if IS_WINDOWS:
            _send([_key_event(vk=0x0D), _key_event(vk=0x0D, flags=KEYEVENTF_KEYUP)])


    def target_info(self) -> str:
        return foreground_info()


def make_injector(kind: str, **kwargs) -> BaseInjector:
    if kind == "stdout" or not IS_WINDOWS:
        return StdoutInjector()
    if kind == "clipboard":
        return ClipboardInjector(restore_clipboard=kwargs.get("restore_clipboard", True))
    if kind == "sendinput":
        return SendInputInjector()
    raise ValueError(f"unknown injector {kind!r}")
