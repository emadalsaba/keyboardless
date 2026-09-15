# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: Keyboardless (بدون كيبورد) — نسخة ويندوز المثبَّتة.

One executable carries both faces:

* double-clicked / shortcut  -> the settings window and the tray icon
* ``Keyboardless.exe --cli …`` -> the same engine from a terminal (support work,
  ``--mic-level``, ``--wav``, ``--about``)

The recogniser models are deliberately **not** bundled (288-666 MB each). The
installer downloads the Arabic model into ``%LOCALAPPDATA%\\Keyboardless\\models``
afterwards, which is what keeps this archive small.

Build it on Windows only:

    .venv\\Scripts\\python.exe -m PyInstaller app\\packaging\\keyboardless.spec --noconfirm
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

APP = Path(SPECPATH).parent.parent / "app"       # noqa: F821  (SPECPATH is injected)
ICON = APP / "packaging" / "keyboardless.ico"

# vosk ships libvosk.dll as package data and sounddevice ships the PortAudio
# binaries: without collecting both, the frozen app starts and then dies on the
# first import of the recogniser.
datas, binaries, hiddenimports = [], [], []
for package in ("vosk", "sounddevice"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# pynput picks its backend at runtime, so the Windows backend is invisible to the
# static analysis and would be missing from the bundle
hiddenimports += ["pynput.keyboard._win32", "pynput.mouse._win32", "keyboard"]

# the shipped default settings travel inside the bundle: a first run copies them
# to %LOCALAPPDATA%\Keyboardless\config.json
datas += [(str(APP / "config.json"), ".")]

# the icon set (four states x eight sizes) travels inside the bundle: without it
# the window and the tray would fall back to the drawn mark and Emad's artwork
# would only exist in the repository
datas += [(str(APP / "assets"), "assets")]


def _unused_qt_file(source: str) -> bool:
    """Qt ships a lot the window never loads: dropping it saves ~25 MB.

    Measured on the first build: ``opengl32sw.dll`` (19.7 MB, the software
    OpenGL fallback -- Qt Widgets does not use it) and the Qt translation
    catalogue. Both would be paid for by every user downloading the installer.
    """
    low = str(source).lower().replace("\\", "/")
    if "opengl32sw" in low:
        return True
    if "/translations/" in low and "pyside6" in low:
        return True
    return low.endswith((".pdb", ".lib", ".exp", ".a"))


datas = [(src, dst) for src, dst in datas if not _unused_qt_file(src)]
binaries = [(src, dst) for src, dst in binaries if not _unused_qt_file(src)]

a = Analysis(                                     # noqa: F821
    [str(APP / "gui.py")],
    pathex=[str(APP)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        # nothing here is used by the app, and every one of them costs size
        "tkinter", "matplotlib", "pandas", "scipy", "PIL", "IPython",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
        "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets", "PySide6.QtQuick", "PySide6.QtQml",
        "PySide6.QtQuick3D", "PySide6.QtTest", "PySide6.QtSql", "PySide6.QtSensors",
        "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtPdf", "PySide6.QtNetwork",
    ],
    noarchive=False,
)
# Qt's DLLs and data files arrive through PyInstaller's PySide6 hook *inside* the
# Analysis, so filtering the collection lists above is not enough (measured: the
# first attempt changed nothing). Drop the unused ones here, where they are real.
# the entries are 2- or 3-tuples depending on the PyInstaller version, so keep the
# tuples whole and only look at the source path (a 2-tuple unpack crashed a build)
a.binaries = [entry for entry in a.binaries if not _unused_qt_file(entry[0])]
a.datas = [entry for entry in a.datas if not _unused_qt_file(entry[0])]

pyz = PYZ(a.pure)                                 # noqa: F821

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="Keyboardless",
    console=False,              # the window and the tray icon are the interface
    icon=str(ICON) if ICON.exists() else None,
    upx=False,                  # UPX breaks Qt's DLL signatures
    version=None,
)
coll = COLLECT(                                   # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="Keyboardless",
    upx=False,
)
