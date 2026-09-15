# check_injector.py -- verify which Windows injection backends actually work here.
#
#   .venv\Scripts\python.exe app\check_injector.py
#
# Reports: which modules are installed, whether we can get a foreground window,
# and whether this shell is elevated (SendInput cannot reach elevated windows
# unless we are elevated too).
import ctypes
import sys

print(f"python           : {sys.version.split()[0]} ({sys.executable})")


def elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception as exc:  # not Windows
        print(f"not windows      : {exc}")
        return False


def foreground() -> str:
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or f"<hwnd {hwnd}>"
    except Exception as exc:
        return f"<error: {exc}>"


for name in ("vosk", "sounddevice", "keyboard", "numpy"):
    try:
        mod = __import__(name)
        print(f"{name:<16} : ok {getattr(mod, '__version__', '')}".rstrip())
    except Exception as exc:
        print(f"{name:<16} : MISSING ({exc})")

if sys.platform == "win32":
    print(f"elevated         : {elevated()}")
    print(f"foreground window: {foreground()}")
    print("note: SendInput only reaches a window of equal or lower integrity level;")
    print("      if your target app runs as administrator, run ar-dictate as admin too")
    print("      (or set injector=clipboard in config.json).")
else:
    print("platform         : not Windows -- the injector must be 'stdout' or 'clipboard' here")
