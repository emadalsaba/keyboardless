"""نافذة الإعدادات والأيقونة الجانبية لتطبيق الإملاء العربي.

The window is deliberately a thin layer: every control writes straight into the
engine's config and hands it to ``Dictation.apply_settings`` -- the exact same
settings the command-line tool reads. Nothing here re-implements dictation, so a
UI bug cannot turn into "the app silently stopped working".

Run it with::

    keyboardless-gui.cmd                   (double-click, no console window)

Verification modes used by the test suite::

    gui.py --selftest        drive every control, print a report, exit
    gui.py --shot out.png    render the window to a PNG (offscreen) and exit
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal  # noqa: E402
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFont, QIcon,  # noqa: E402
                           QKeyEvent, QKeySequence, QPainter, QPen, QPixmap,
                           QShortcut)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,  # noqa: E402
                               QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QMenu, QPlainTextEdit, QProgressBar,
                               QPushButton, QSlider, QSystemTrayIcon, QTabWidget,
                               QVBoxLayout, QWidget)

import app_icons  # noqa: E402
import app_theme  # noqa: E402
import ar_dictate  # noqa: E402
import branding  # noqa: E402
from ar_dictate import (DEFAULT_CONFIG, Dictation, combo_list,  # noqa: E402
                        hotkey_claim, load_config, update_config_keys)
from inject_win import make_injector  # noqa: E402

APP_NAME = branding.PRODUCT_EN
TR = {
    "ready": "جاهز",
    "loading": "يحمّل نموذج الصوت…",
    "listening": "يستمع — تكلّم الآن",
    "stopped": "متوقف",
}
# the sensitivity slider maps to the auto-gain target: a lower target means more
# amplification, so "more sensitive" moves the slider to the right
SENS_MAX_TARGET = 0.60
SENS_MIN_TARGET = 0.05


class _Tee(io.TextIOBase):
    """Write to the console *and* to a buffer (a windowed exe may have neither)."""

    def __init__(self, primary, buffer: io.StringIO):
        self._primary = primary
        self._buffer = buffer

    def write(self, text: str) -> int:
        self._buffer.write(text)
        if self._primary is not None:
            try:
                self._primary.write(text)
                self._primary.flush()
            except (OSError, ValueError):
                pass
        return len(text)

    def flush(self) -> None:
        if self._primary is not None:
            try:
                self._primary.flush()
            except (OSError, ValueError):
                pass


def _attach_console() -> None:
    """Give a windowed executable somewhere to print.

    PyInstaller builds the window without a console, so ``sys.stdout`` is None
    and ``print`` fails. ``Keyboardless.exe --cli …`` is a supported way to use
    the engine, so the parent console is attached when there is one.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        import ctypes

        if ctypes.windll.kernel32.AttachConsole(-1):      # ATTACH_PARENT_PROCESS
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
            sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
    except Exception:  # noqa: BLE001
        pass


def _cli_log_path() -> Path:
    """Where a command-line run keeps its output for the next support request."""
    from ar_dictate import user_data_dir

    try:
        folder = user_data_dir()
    except Exception:  # noqa: BLE001
        folder = Path(tempfile.gettempdir())
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        folder = Path(tempfile.gettempdir())
    return folder / "cli-last.txt"


def run_cli(arguments: list[str]) -> int:
    """Run the engine from the packaged executable.

    Three things this has to survive, all measured on the built exe:

    * no console (a windowed build) -- so ``print`` has nowhere to go,
    * an exception reaching the bootloader -- it shows a **modal** error dialog
      that nobody can see over SSH, and the process then hangs forever holding
      its output pipe (the first frozen ``--cli --about`` did exactly that),
    * a support request with nothing to read -- so every line is kept in
      ``cli-last.txt`` beside the settings.
    """
    _attach_console()
    buffer = io.StringIO()
    code = 1
    try:
        with contextlib.redirect_stdout(_Tee(sys.stdout, buffer)), \
                contextlib.redirect_stderr(_Tee(sys.stderr, buffer)):
            code = ar_dictate.main(arguments)
    except SystemExit as stop:
        code = int(stop.code or 0)
    except BaseException:  # noqa: BLE001 -- never hand this to the bootloader
        code = 1
        buffer.write(traceback.format_exc())
        if sys.stderr is not None:
            traceback.print_exc()
    finally:
        try:
            _cli_log_path().write_text(buffer.getvalue(), encoding="utf-8")
        except OSError:
            pass
    return code


def app_icon(state: str = "ready") -> QIcon:
    """أيقونة التطبيق من تصميم عماد، مع رسم احتياطي لا يُترك بلا أيقونة.

    ``app_icons`` decides *which* state fits the moment; this only turns a file
    into a QIcon, and falls back to the drawn mark if the artwork is missing.
    """
    path = app_icons.icon_path(state, app_icons.DISPLAY_SIZE)
    if path is not None:
        icon = QIcon(str(path))
        if not icon.isNull():
            return icon
    return _drawn_icon()


def _drawn_icon(active: bool = False) -> QIcon:
    """Fallback: draw the mark in code so a missing asset cannot break the app."""
    size = 64
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#0f9d58" if active else "#2f6feb"))
    painter.drawRoundedRect(3, 3, size - 6, size - 6, 16, 16)
    painter.setBrush(QColor("#ffffff"))
    painter.drawRoundedRect(23, 13, 18, 25, 9, 9)
    painter.setPen(QPen(QColor("#ffffff"), 4))
    painter.drawArc(17, 22, 30, 24, 200 * 16, 140 * 16)
    painter.drawLine(32, 46, 32, 52)
    painter.drawLine(23, 52, 41, 52)
    painter.end()
    return QIcon(pix)


def apply_theme(app: QApplication, appearance: str) -> str:
    """يُطبّق المظهر المختار على التطبيق كله ويعيد الوضع الفعلي."""
    theme = app_theme.resolve(appearance, app_icons.system_prefers_dark())
    app.setStyleSheet(app_theme.stylesheet(appearance, app_icons.system_prefers_dark()))
    return theme


def sensitivity_to_target(value: int) -> float:
    span = SENS_MAX_TARGET - SENS_MIN_TARGET
    return round(SENS_MAX_TARGET - span * (value / 100.0), 3)


def target_to_sensitivity(target: float) -> int:
    span = SENS_MAX_TARGET - SENS_MIN_TARGET
    return max(0, min(100, int(round((SENS_MAX_TARGET - float(target)) / span * 100))))


class HotkeyEdit(QLineEdit):
    """A field that captures a key combination instead of accepting typing."""

    changed = Signal(str)

    MODIFIERS = {Qt.Key_Control: "ctrl", Qt.Key_Alt: "alt", Qt.Key_Shift: "shift",
                 Qt.Key_Meta: "win"}
    NAMES = {Qt.Key_Space: "space", Qt.Key_Tab: "tab", Qt.Key_Return: "enter",
             Qt.Key_Backspace: "backspace", Qt.Key_Delete: "delete",
             Qt.Key_Insert: "insert", Qt.Key_Home: "home", Qt.Key_End: "end",
             Qt.Key_PageUp: "pageup", Qt.Key_PageDown: "pagedown"}

    def __init__(self, value: str = ""):
        super().__init__(value)
        self.setReadOnly(True)
        self.setPlaceholderText("انقر ثم اضغط الاختصار")
        self.setToolTip("انقر داخل الحقل ثم اضغط المفاتيح. Esc للتراجع.")
        self._before = value

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt API)
        key = event.key()
        if key == Qt.Key_Escape:
            self.setText(self._before)
            self.clearFocus()
            return
        parts: list[str] = []
        mods = event.modifiers()
        for flag, name in ((Qt.ControlModifier, "ctrl"), (Qt.AltModifier, "alt"),
                           (Qt.ShiftModifier, "shift"), (Qt.MetaModifier, "win")):
            if mods & flag:
                parts.append(name)
        if key in self.MODIFIERS:          # only a modifier so far: keep waiting
            return
        if key in self.NAMES:
            parts.append(self.NAMES[key])
        elif Qt.Key_F1 <= key <= Qt.Key_F24:
            parts.append(f"f{key - Qt.Key_F1 + 1}")
        else:
            text = event.text().strip().lower()
            if not text or not text.isprintable():
                return
            parts.append(text)
        if not any(p in ("ctrl", "alt", "shift", "win") for p in parts):
            # a bare letter would swallow ordinary typing everywhere in Windows
            self.setText(self._before)
            self.setToolTip("لازم مفتاح مساعد واحد على الأقل (Ctrl أو Alt أو Shift أو Win)")
            return
        combo = "+".join(parts)
        self._before = combo
        self.setText(combo)
        self.changed.emit(combo)
        self.clearFocus()


class ModelLoader(QThread):
    """Vosk model loading takes 10-30 s: never on the UI thread."""

    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self) -> None:  # noqa: D102
        try:
            import time as _t

            from vosk import Model

            started = _t.perf_counter()
            model = Model(self.path)
            self.loaded.emit((model, _t.perf_counter() - started))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class ModelDownloader(QThread):
    """تنزيل نموذج صوتي من داخل النافذة، بتقدّم ظاهر.

    The installer downloads the default model automatically; this is the safety
    net for when that download failed (no internet during setup, a proxy, a
    device that has no model yet) and for users who want a different Arabic model.
    """

    progress = Signal(str, int, int, str)   # name, done, total, phase
    finished_ok = Signal(str, str)          # name, path
    failed = Signal(str, str)               # name, message

    def __init__(self, name: str, directory: Path):
        super().__init__()
        self.name = name
        self.directory = directory

    def run(self) -> None:  # noqa: D102
        import model_store

        try:
            path = model_store.download(
                self.name, self.directory,
                lambda name, done, total, phase: self.progress.emit(name, done, total, phase))
            self.finished_ok.emit(self.name, str(path))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(self.name, str(exc))


class MicTester(QThread):
    """Record a few seconds and report the level, so 'nothing is typed' is visible."""

    done = Signal(float, float, str)

    def __init__(self, device, seconds: float):
        super().__init__()
        self.device = device
        self.seconds = seconds

    def run(self) -> None:  # noqa: D102
        try:
            import sounddevice as sd

            from ar_dictate import AutoGain, audio_peak

            rate, chunk = 16000, 1600
            agc = AutoGain()
            peaks: list[float] = []
            with sd.RawInputStream(samplerate=rate, blocksize=chunk, device=self.device,
                                   dtype="int16", channels=1) as stream:
                for _ in range(int(self.seconds * 10)):
                    data, _overflow = stream.read(chunk)
                    raw = bytes(data)
                    peaks.append(audio_peak(raw))
                    agc.apply(raw)
            top = max(peaks) if peaks else 0.0
            self.done.emit(top, agc.gain, "")
        except Exception as exc:  # noqa: BLE001
            self.done.emit(0.0, 1.0, str(exc))


class AboutDialog(QDialog):
    """نافذة «حول البرنامج»: الاسم والإصدار والمؤلف ورابط لينكدإن.

    The labels are kept on the instance so the self-test can read them back --
    "the About box says the right version" is a testable claim, not a hope.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"حول {branding.PRODUCT_EN}")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowIcon(app_icon())
        self.setMinimumWidth(440)

        box = QVBoxLayout(self)
        box.setContentsMargins(24, 20, 24, 18)
        box.setSpacing(9)

        mark = QLabel()
        mark.setPixmap(app_icon().pixmap(64, 64))
        mark.setAlignment(Qt.AlignCenter)
        box.addWidget(mark)

        name = QLabel(f"<b style='font-size:19px'>{branding.PRODUCT_EN}</b>"
                      f" — {branding.PRODUCT_AR}")
        name.setAlignment(Qt.AlignCenter)
        box.addWidget(name)

        self.version_label = QLabel(f"الإصدار {branding.VERSION}")
        self.version_label.setAlignment(Qt.AlignCenter)
        self.version_label.setStyleSheet("color:#2f6feb;font-size:15px;font-weight:600;")
        self.version_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.addWidget(self.version_label)

        self.author_label = QLabel(branding.AUTHOR_LINE_AR)
        self.author_label.setAlignment(Qt.AlignCenter)
        self.author_label.setStyleSheet("font-size:14px;")
        box.addWidget(self.author_label)

        # الإهداء: البرنامج صدقة — سطر ظاهر لأجل صاحبه لا للعرض
        self.dedication_label = QLabel(branding.DEDICATION_AR)
        self.dedication_label.setAlignment(Qt.AlignCenter)
        self.dedication_label.setWordWrap(True)
        # the dark green of the palette disappears on a dark background: take the
        # colour from the theme that is actually in effect
        dedication_colour = app_theme.colors(
            getattr(parent, "cfg", {}).get("appearance", "system")
            if parent is not None else "system",
            app_icons.system_prefers_dark())["dedication"]
        self.dedication_label.setStyleSheet(
            f"color:{dedication_colour};font-size:13px;font-style:italic;padding:2px 0;")
        box.addWidget(self.dedication_label)

        self.link_label = QLabel(f"<a href='{branding.LINKEDIN}'>{branding.LINKEDIN_LABEL}</a>")
        self.link_label.setAlignment(Qt.AlignCenter)
        self.link_label.setOpenExternalLinks(True)
        self.link_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        box.addWidget(self.link_label)

        self.linkedin_button = QPushButton("فتح صفحتي في لينكدإن")
        self.linkedin_button.clicked.connect(self.open_linkedin)
        box.addWidget(self.linkedin_button)

        note = QLabel(branding.ABOUT_NOTE)
        note.setWordWrap(True)
        note.setStyleSheet("color:#5b6472;")
        box.addWidget(note)

        copyright_label = QLabel(branding.COPYRIGHT)
        copyright_label.setAlignment(Qt.AlignCenter)
        copyright_label.setStyleSheet("color:#8a93a3;")
        box.addWidget(copyright_label)

        close = QPushButton("إغلاق")
        close.clicked.connect(self.accept)
        box.addWidget(close)

    def open_linkedin(self) -> None:
        """Open the author's LinkedIn page in the default browser."""
        QDesktopServices.openUrl(QUrl(branding.LINKEDIN))


class MainWindow(QMainWindow):
    """The settings window and everything it drives."""

    # engine events arrive on the audio/hotkey threads; this signal is what
    # moves them onto the UI thread before any widget is touched
    event_received = Signal(str, dict)

    def __init__(self, cfg: dict, config_path: Path, headless_tray: bool = False,
                 injector: str | None = None, render_only: bool = False):
        super().__init__()
        self.cfg = cfg
        self.config_path = config_path
        self.setWindowTitle(branding.WINDOW_TITLE)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowIcon(app_icon())
        self.resize(720, 620)
        self._quitting = False
        self._model = None
        self._mic_thread: threading.Thread | None = None
        self._loader: ModelLoader | None = None
        self._mic_test: MicTester | None = None
        self._level_value = 0.0
        self._tray_available = False
        # widgets call their own change handlers while they are created; nothing
        # may be saved or applied to the engine before the window is finished
        self._ready = False

        if injector:
            self.cfg["injector"] = injector
        self.injector = make_injector(self.cfg.get("injector", "sendinput"))
        self.engine = Dictation(self.cfg, self.injector)
        self.engine.on_event = self._on_engine_event

        self._build_ui()
        self._ready = True
        if not headless_tray:
            self._build_tray()
        if render_only:
            # used by --shot: draw the window, nothing else (no hotkey hook, no
            # recogniser thread -- a QThread still running at exit aborts)
            self.model_status.setText("عرض فقط")
        else:
            ar_dictate.bind_hotkeys(self.engine, self.cfg)
            self.engine.on_quit = self.quit_app
            self._load_model(self.cfg["model"])

    # --------------------------------------------------------------- interface
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        root.addWidget(self._status_row())
        root.addWidget(self._meter_row())
        tabs = QTabWidget()
        self.tabs = tabs              # --shot-tab picks one for the screenshots
        tabs.addTab(self._tab_hotkeys(), "الاختصارات")
        tabs.addTab(self._tab_audio(), "الصوت")
        tabs.addTab(self._tab_models(), "النماذج")
        tabs.addTab(self._tab_dictation(), "الإملاء")
        tabs.addTab(self._tab_log(), "السجل")
        root.addWidget(tabs, 1)
        root.addWidget(self._transcript_box())

    def _status_row(self) -> QWidget:
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet("color:#b23c17;font-size:22px;")
        self.status_label = QLabel(TR["loading"])
        self.status_label.setStyleSheet("font-size:15px;font-weight:600;")
        self.mode_label = QLabel("الفصحى")
        self.mode_label.setStyleSheet("color:#5b6472;")
        box.addWidget(self.status_dot)
        box.addWidget(self.status_label)
        box.addWidget(self.mode_label)
        box.addStretch(1)
        self.toggle_button = QPushButton("ابدأ الإملاء")
        self.toggle_button.setMinimumHeight(44)
        self.toggle_button.setMinimumWidth(190)
        self.toggle_button.setStyleSheet(
            "QPushButton{background:#2f6feb;color:white;font-size:16px;font-weight:700;"
            "border-radius:8px;}QPushButton:disabled{background:#c3c9d4;}")
        self.toggle_button.clicked.connect(self.toggle_dictation)
        box.addWidget(self.toggle_button)
        self.mode_button = QPushButton("بدّل الفصحى/اللهجة")
        self.mode_button.clicked.connect(self.switch_mode)
        box.addWidget(self.mode_button)
        self.about_button = QPushButton("حول البرنامج")
        self.about_button.clicked.connect(self.show_about)
        box.addWidget(self.about_button)
        QShortcut(QKeySequence(Qt.Key_F1), self, self.show_about)
        return row

    def _meter_row(self) -> QWidget:
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(QLabel("مستوى المايك:"))
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.meter.setFixedHeight(14)
        box.addWidget(self.meter, 1)
        self.meter_text = QLabel("—")
        self.meter_text.setMinimumWidth(150)
        box.addWidget(self.meter_text)
        return row

    def _tab_hotkeys(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.hotkey_edit = HotkeyEdit(combo_list(self.cfg["hotkey"])[0])
        self.mode_key_edit = HotkeyEdit(self.cfg["mode_key"])
        self.quit_key_edit = HotkeyEdit(self.cfg["quit_key"])
        for edit, field in ((self.hotkey_edit, "hotkey"),
                            (self.mode_key_edit, "mode_key"),
                            (self.quit_key_edit, "quit_key")):
            edit.changed.connect(lambda combo, f=field: self._hotkey_changed(f, combo))
        form.addRow("بدء/إيقاف الإملاء:", self.hotkey_edit)
        form.addRow("تبديل الفصحى/اللهجة:", self.mode_key_edit)
        form.addRow("إغلاق البرنامج:", self.quit_key_edit)
        self.hotkey_status = QLabel("")
        check = QPushButton("افحص إن كان الاختصار محجوزًا لبرنامج آخر")
        check.clicked.connect(self.check_hotkeys)
        form.addRow(check, self.hotkey_status)
        hint = QLabel("الاختصارات تُقرأ وتُحفظ في app\\config.json — وهي نفسها التي "
                      "يستعملها التشغيل من سطر الأوامر.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#5b6472;")
        form.addRow(hint)
        return page

    def _tab_audio(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(320)
        refresh = QPushButton("تحديث القائمة")
        refresh.clicked.connect(self.reload_devices)
        row = QWidget()
        row_box = QHBoxLayout(row)
        row_box.setContentsMargins(0, 0, 0, 0)
        row_box.addWidget(self.device_combo, 1)
        row_box.addWidget(refresh)
        form.addRow("مدخل المايك من النظام:", row)

        self.agc_check = QCheckBox("رفع تلقائي للصوت الهادئ (مهم للمايكات الضعيفة)")
        self.agc_check.setChecked(bool(self.cfg.get("agc", True)))
        self.agc_check.toggled.connect(lambda v: self._apply({"agc": v}))
        form.addRow(self.agc_check)

        self.sens_slider = QSlider(Qt.Horizontal)
        self.sens_slider.setRange(0, 100)
        self.sens_slider.setValue(target_to_sensitivity(self.cfg.get("agc_target", 0.3)))
        self.sens_slider.valueChanged.connect(self._sensitivity_changed)
        self.sens_label = QLabel("")
        self.sens_slider.setToolTip("كل ما زادت الحساسية، رُفع الصوت الهادئ أكثر قبل التعرف")
        sens_row = QWidget()
        sens_box = QHBoxLayout(sens_row)
        sens_box.setContentsMargins(0, 0, 0, 0)
        sens_box.addWidget(self.sens_slider, 1)
        sens_box.addWidget(self.sens_label)
        form.addRow("حساسية استماع الصوت:", sens_row)
        self._sensitivity_changed(self.sens_slider.value())

        test_row = QWidget()
        test_box = QHBoxLayout(test_row)
        test_box.setContentsMargins(0, 0, 0, 0)
        self.mic_test_button = QPushButton("اختبر المايك (3 ثوانٍ)")
        self.mic_test_button.clicked.connect(self.test_mic)
        self.mic_test_label = QLabel("—")
        test_box.addWidget(self.mic_test_button)
        test_box.addWidget(self.mic_test_label, 1)
        form.addRow(test_row)
        return page

    def _tab_models(self) -> QWidget:
        """النماذج العربية المجانية: ماذا هو مثبَّت، وتنزيل ما ينقص."""
        import model_store

        page = QWidget()
        outer = QVBoxLayout(page)
        self.models_dir_label = QLabel(f"مجلد النماذج: {model_store.models_dir()}")
        self.models_dir_label.setWordWrap(True)
        self.models_dir_label.setStyleSheet("color:#5b6472;")
        outer.addWidget(self.models_dir_label)
        outer.addWidget(QLabel("كل هذه النماذج مجانية وتعمل بلا إنترنت بعد تنزيلها."))

        self.model_rows: dict = {}
        for info in model_store.ARABIC_MODELS:
            # "title (100MB)": mixing the number into the Arabic title made the
            # RTL rendering split it as "تنزيل 100MB … — 100", which read oddly
            box = QGroupBox(f"{info.title} ({info.size_mb}MB)")
            row = QHBoxLayout(box)
            note = QLabel(info.note)
            note.setWordWrap(True)
            row.addWidget(note, 1)
            state = QLabel("")
            state.setMinimumWidth(90)
            row.addWidget(state)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(True)
            bar.setVisible(False)
            bar.setMinimumWidth(150)
            row.addWidget(bar)
            download = QPushButton("تنزيل")
            download.clicked.connect(lambda _c=False, n=info.name: self._download_model(n))
            row.addWidget(download)
            use = QPushButton("استخدم هذا النموذج")
            use.clicked.connect(lambda _c=False, n=info.name: self._use_model(n))
            row.addWidget(use)
            self.model_rows[info.name] = {"box": box, "state": state, "bar": bar,
                                          "download": download, "use": use, "info": info}
            outer.addWidget(box)
        outer.addStretch(1)
        self._refresh_model_rows()
        return page

    def _refresh_model_rows(self) -> None:
        """Update every row's badge and buttons from what is on disk."""
        import model_store

        directory = model_store.models_dir()
        for name, widgets in getattr(self, "model_rows", {}).items():
            installed = model_store.is_installed(name, directory)
            current = Path(str(self.cfg.get("model", ""))).name == name
            widgets["state"].setText("مثبَّت ✓" + (" (مُستخدَم)" if current else "")
                                     if installed else "غير مثبَّت")
            widgets["state"].setStyleSheet(
                "color:#0f9d58;font-weight:600;" if installed else "color:#5b6472;")
            widgets["download"].setEnabled(not installed)
            widgets["use"].setEnabled(installed and not current)
            if installed and not current:
                widgets["use"].setText("استخدم هذا النموذج")
            elif current:
                widgets["use"].setText("مُستخدَم الآن")

    def _download_model(self, name: str) -> None:
        import model_store

        widgets = self.model_rows.get(name)
        if widgets is None or getattr(self, "_downloader", None):
            return
        widgets["bar"].setVisible(True)
        widgets["bar"].setValue(0)
        widgets["download"].setEnabled(False)
        self._note(f"بدأ تنزيل {name} …")
        self._downloader = ModelDownloader(name, model_store.models_dir())
        self._downloader.progress.connect(self._model_download_progress)
        self._downloader.finished_ok.connect(self._model_download_done)
        self._downloader.failed.connect(self._model_download_failed)
        self._downloader.start()

    def _model_download_progress(self, name: str, done: int, total: int, phase: str) -> None:
        widgets = self.model_rows.get(name)
        if widgets is None:
            return
        percent = int(done / total * 100) if total else 0
        widgets["bar"].setValue(max(0, min(100, percent)))
        widgets["bar"].setFormat(f"{percent}%")
        if phase.startswith("retry"):
            self._note(f"{name}: {phase}")

    def _model_download_done(self, name: str, path: str) -> None:
        self._downloader = None
        self._note(f"نزل النموذج: {path}")
        self._refresh_model_rows()
        self.reload_models()
        # if the app had no usable model at all, move to the one that just arrived
        import model_store

        if not model_store.is_installed(Path(str(self.cfg.get("model", ""))).name,
                                        model_store.models_dir()):
            self._use_model(name)

    def _model_download_failed(self, name: str, message: str) -> None:
        self._downloader = None
        widgets = self.model_rows.get(name)
        if widgets is not None:
            widgets["bar"].setVisible(False)
        self._note(f"فشل تنزيل {name}: {message}")
        self._refresh_model_rows()

    def _use_model(self, name: str) -> None:
        import model_store

        path = model_store.models_dir() / name
        self._apply({"model": str(path)})
        self.reload_models()
        self._refresh_model_rows()
        self._note(f"النموذج المُستخدَم الآن: {name}")

    def _tab_dictation(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self.pause_spin = QDoubleSpinBox()
        self.pause_spin.setRange(0.0, 10.0)
        self.pause_spin.setSingleStep(0.1)
        self.pause_spin.setDecimals(1)
        self.pause_spin.setSuffix(" ثانية")
        self.pause_spin.setValue(float(self.cfg.get("pause_seconds") or 0.0))
        self.pause_spin.setToolTip("بعد هذه المدة من الصمت تُكتب الفاصلة. صفر = معطّل")
        self.pause_spin.valueChanged.connect(lambda v: self._apply({"pause_seconds": float(v)}))
        form.addRow("الصمت قبل وضع الفاصلة بين الجمل:", self.pause_spin)

        self.sep_combo = QComboBox()
        for label, value in (("سطر جديد", "\n"), ("نقطة (.)", "."), ("فاصلة (،)", "،"),
                             ("نقطتان (:)", ":"), ("بدون فاصل", "")):
            self.sep_combo.addItem(label, value)
        current = self.cfg.get("pause_sep", "\n")
        index = self.sep_combo.findData(current)
        self.sep_combo.setCurrentIndex(index if index >= 0 else 0)
        self.sep_combo.currentIndexChanged.connect(
            lambda _i: self._apply({"pause_sep": self.sep_combo.currentData()}))
        form.addRow("شكل الفاصلة:", self.sep_combo)

        self.appearance_combo = QComboBox()
        for label, value in app_theme.labels():
            self.appearance_combo.addItem(label, value)
        index = self.appearance_combo.findData(self.cfg.get("appearance", "system"))
        self.appearance_combo.setCurrentIndex(index if index >= 0 else 0)
        self.appearance_combo.setToolTip("ألوان النافذة: داكنة، أو ألوان ويندوز المعتادة")
        self.appearance_combo.currentIndexChanged.connect(lambda _i: self._appearance_changed())
        form.addRow("مظهر البرنامج:", self.appearance_combo)

        self.punct_check = QCheckBox("علامات الترقيم العربية (فاصلة، نقطة، سؤال)")
        self.punct_check.setChecked(bool(self.cfg.get("punctuation", True)))
        self.punct_check.toggled.connect(lambda v: self._apply({"punctuation": v}))
        form.addRow(self.punct_check)

        self.period_check = QCheckBox("نقطة تلقائية عند إيقاف الإملاء")
        self.period_check.setChecked(bool(self.cfg.get("auto_period", True)))
        self.period_check.toggled.connect(lambda v: self._apply({"auto_period": v}))
        form.addRow(self.period_check)

        self.injector_combo = QComboBox()
        for label, value in (("إرسال مباشر إلى النافذة (sendinput)", "sendinput"),
                             ("لصق عبر الحافظة (clipboard)", "clipboard"),
                             ("إلى سطر الأوامر فقط (stdout)", "stdout")):
            self.injector_combo.addItem(label, value)
        index = self.injector_combo.findData(self.cfg.get("injector", "sendinput"))
        self.injector_combo.setCurrentIndex(index if index >= 0 else 0)
        self.injector_combo.currentIndexChanged.connect(lambda _i: self._injector_changed())
        form.addRow("طريقة الكتابة:", self.injector_combo)

        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(320)
        browse = QPushButton("استعراض…")
        browse.clicked.connect(self.browse_model)
        model_row = QWidget()
        model_box = QHBoxLayout(model_row)
        model_box.setContentsMargins(0, 0, 0, 0)
        model_box.addWidget(self.model_combo, 1)
        model_box.addWidget(browse)
        form.addRow("نموذج التعرف (Vosk):", model_row)
        self.model_status = QLabel("")
        self.model_status.setWordWrap(True)
        form.addRow(self.model_status)
        self.reload_models()
        return page

    def _tab_log(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(400)
        box.addWidget(self.log_box)
        row = QWidget()
        row_box = QHBoxLayout(row)
        row_box.setContentsMargins(0, 0, 0, 0)
        open_log = QPushButton("افتح ملف السجل")
        open_log.clicked.connect(self.open_log_file)
        row_box.addWidget(open_log)
        row_box.addStretch(1)
        box.addWidget(row)
        self._tail_log()
        return page

    def _transcript_box(self) -> QWidget:
        box = QGroupBox("ما كتبه البرنامج في النافذة النشِطة")
        layout = QVBoxLayout(box)
        self.heard_label = QLabel("يسمع الآن: —")
        self.heard_label.setStyleSheet("color:#5b6472;font-style:italic;")
        layout.addWidget(self.heard_label)
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setMaximumHeight(96)
        self.transcript.setMaximumBlockCount(200)
        layout.addWidget(self.transcript)
        return box

    # -------------------------------------------------------------------- tray
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self._tray_icon(False), self)
        menu = QMenu()
        # طلب عماد بالنص: استماع / صمت / صفحة البرنامج / إغلاق تمامًا
        self.tray_listen = QAction("استماع", self)
        self.tray_listen.triggered.connect(self.start_dictation)
        self.tray_silence = QAction("صمت", self)
        self.tray_silence.triggered.connect(self.stop_dictation)
        self.tray_page = QAction("صفحة البرنامج", self)
        self.tray_page.triggered.connect(self.show_window)
        self.tray_mode = QAction("بدّل الفصحى/اللهجة", self)
        self.tray_mode.triggered.connect(self.switch_mode)
        about_action = QAction("حول البرنامج", self)
        about_action.triggered.connect(self.show_about)
        self.tray_quit = QAction("إغلاق تمامًا", self)
        self.tray_quit.triggered.connect(self.quit_app)
        menu.addAction(self.tray_listen)
        menu.addAction(self.tray_silence)
        menu.addSeparator()
        menu.addAction(self.tray_page)
        menu.addAction(self.tray_mode)
        menu.addAction(about_action)
        menu.addSeparator()
        menu.addAction(self.tray_quit)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip(f"{branding.TITLE} — {TR['ready']}")
        self.tray.activated.connect(self._tray_clicked)
        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        if self._tray_available:
            self.tray.show()

    def _tray_clicked(self, reason) -> None:  # noqa: ANN001
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_window()

    def _tray_icon(self, active: bool) -> QIcon:
        """علبة النظام: أحادية اللون في الوضع الداكن (حسب دليل التصميم)."""
        return app_icon(app_icons.tray_state(active, app_icons.system_prefers_dark()))

    def show_about(self) -> None:
        """حول البرنامج: الاسم، الإصدار، المؤلف ورابط لينكدإن."""
        dialog = AboutDialog(self)
        self.about_dialog = dialog      # the self-test reads it back
        dialog.exec()

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        """Closing the window keeps dictation available in the tray."""
        if self._quitting or not getattr(self, "tray", None):
            event.accept()
            return
        event.ignore()
        self.hide()
        if self._tray_available:
            self.tray.showMessage(branding.PRODUCT_AR,
                                  "البرنامج يعمل في الأيقونة الجانبية بجانب الساعة",
                                  self._tray_icon(self.engine.active), 4000)

    def quit_app(self) -> None:
        self._quitting = True
        try:
            self.engine._stop.set()
            self.engine._queue.put(None)
            self.engine.stop()
        except Exception:  # noqa: BLE001
            pass
        if getattr(self, "tray", None):
            self.tray.hide()
        QApplication.quit()

    # ------------------------------------------------------------------ engine
    def _load_model(self, path: str) -> None:
        self.model_status.setText(f"يحمّل النموذج: {Path(path).name} …")
        self.toggle_button.setEnabled(False)
        self._loader = ModelLoader(path)
        self._loader.loaded.connect(self._model_loaded)
        self._loader.failed.connect(self._model_failed)
        self._loader.start()

    def _model_loaded(self, payload) -> None:
        model, seconds = payload
        self.engine.model = model
        self._model = model
        self.model_status.setText(f"النموذج جاهز ({seconds:.1f} ثانية)")
        self.toggle_button.setEnabled(True)
        self._set_status(False)
        self._note(f"model ready in {seconds:.1f}s")

    def _model_failed(self, message: str) -> None:
        self.model_status.setText(f"فشل تحميل النموذج: {message}")
        self._set_status(False, problem=True)
        self._note(f"model failed: {message}")

    def _start_mic_thread(self) -> None:
        if self._mic_thread and self._mic_thread.is_alive():
            return
        self._mic_thread = threading.Thread(target=self.engine.feed_mic, name="mic",
                                            daemon=True)
        self._mic_thread.start()

    def start_dictation(self) -> None:
        """«استماع» — من الزر أو من قائمة الأيقونة الجانبية."""
        if self._model is None or self.engine.active:
            return
        self._start_mic_thread()
        time.sleep(0.35)              # let the stream open before the first word
        self.engine.start()

    def stop_dictation(self) -> None:
        """«صمت» — إيقاف الإملاء مع الإبقاء على البرنامج في الخلفية."""
        if self.engine.active:
            self.engine.stop()

    def toggle_dictation(self) -> None:
        self.stop_dictation() if self.engine.active else self.start_dictation()

    def switch_mode(self) -> None:
        self.engine.switch_mode()

    def _on_engine_event(self, kind: str, payload: dict) -> None:
        """Called from the audio/hotkey threads: only touch the UI via signals."""
        # a plain paint into Qt widgets from another thread is unsafe, so every
        # event is re-emitted on the UI thread through the window's signal
        self.event_received.emit(kind, payload)

    # --------------------------------------------------------------- settings
    def _apply(self, updates: dict) -> None:
        if not self._ready:
            self.cfg.update(updates)   # the engine shares this dict
            return
        deferred = self.engine.apply_settings(updates)
        saved = dict(updates)
        if "model" in deferred:
            self._load_model(str(updates["model"]))
            saved.pop("model", None)
        try:
            update_config_keys(self.config_path, saved)
        except Exception as exc:  # noqa: BLE001
            self._note(f"could not save settings: {exc}")
        if "hotkey" in saved or "mode_key" in saved or "quit_key" in saved:
            ar_dictate.bind_hotkeys(self.engine, self.cfg)

    def _note(self, message: str) -> None:
        """Say something in the log tab without assuming it exists yet."""
        box = getattr(self, "log_box", None)
        if box is not None:
            box.appendPlainText(message)

    def _hotkey_changed(self, field: str, combo: str) -> None:
        if field == "hotkey":
            self._apply({"hotkey": [combo]})
        else:
            self._apply({field: combo})
        self._note(f"{field} → {combo}")

    def _sensitivity_changed(self, value: int) -> None:
        target = sensitivity_to_target(value)
        self.sens_label.setText(f"حساسية {value}% · مستوى الهدف {target:.2f}")
        current = float(self.cfg.get("agc_target", 0.3))
        if self.agc_check.isChecked() and abs(current - target) > 1e-9:
            self._apply({"agc_target": target})

    def _appearance_changed(self) -> None:
        """يحفظ اختيار المستخدم ويطبّقه فورًا (بلا إعادة تشغيل)."""
        appearance = self.appearance_combo.currentData()
        self._apply({"appearance": appearance})
        theme = apply_theme(QApplication.instance(), appearance)
        self._note(f"المظهر: {appearance} (الوضع الفعلي: {theme})")

    def _injector_changed(self) -> None:
        kind = self.injector_combo.currentData()
        self._apply({"injector": kind})
        self.engine.injector = make_injector(kind)
        self._note(f"injector → {kind}")

    def check_hotkeys(self) -> None:
        results = []
        for label, field in (("الإملاء", "hotkey"), ("الوضع", "mode_key"),
                             ("الخروج", "quit_key")):
            specs = combo_list(self.cfg.get(field))
            verdicts = ", ".join(f"{s} → {hotkey_claim(s)}" for s in specs)
            results.append(f"{label}: {verdicts}")
        self.hotkey_status.setText(" · ".join(results))

    # ------------------------------------------------------------------ devices
    def reload_devices(self) -> None:
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItem("الافتراضي للنظام", None)
        try:
            import sounddevice as sd

            apis = sd.query_hostapis()
            unusable = 0
            for index, info in enumerate(sd.query_devices()):
                if info.get("max_input_channels", 0) > 0:
                    api = apis[info["hostapi"]]["name"] if info.get("hostapi") is not None else "?"
                    label = f"{index}: {info['name'][:40]} [{api}]"
                    # a listed device can still refuse to open (device 0 on the
                    # machine may do): say so here instead of letting the user
                    # pick it and wonder why nothing is typed
                    try:
                        sd.check_input_settings(device=index, samplerate=16000,
                                                channels=1, dtype="int16")
                    except Exception:  # noqa: BLE001
                        label += " — غير قابل للفتح"
                        unusable += 1
                    self.device_combo.addItem(label, index)
            if unusable:
                self._note(f"{unusable} مدخل صوتي غير قابل للفتح على هذا الجهاز")
        except Exception as exc:  # noqa: BLE001
            self._note(f"device list failed: {exc}")
        index = self.device_combo.findData(self.cfg.get("device"))
        self.device_combo.setCurrentIndex(index if index >= 0 else 0)
        self.device_combo.blockSignals(False)
        self.device_combo.currentIndexChanged.connect(
            lambda _i: self._apply({"device": self.device_combo.currentData()}))

    def reload_models(self) -> None:
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        models_dir = HERE.parent / "models"
        current = str(self.cfg.get("model", ""))
        if models_dir.is_dir():
            for path in sorted(models_dir.iterdir()):
                if path.is_dir() and path.name.startswith("vosk-model"):
                    self.model_combo.addItem(path.name, str(path))
        if current and self.model_combo.findData(current) < 0:
            self.model_combo.addItem(current, current)
        index = self.model_combo.findData(current)
        self.model_combo.setCurrentIndex(index if index >= 0 else 0)
        self.model_combo.blockSignals(False)
        self.model_combo.currentIndexChanged.connect(
            lambda _i: self._apply({"model": self.model_combo.currentData()}))

    def browse_model(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "اختر مجلد نموذج Vosk")
        if chosen:
            self._apply({"model": chosen})

    def test_mic(self) -> None:
        if self._mic_test and self._mic_test.isRunning():
            return
        self.mic_test_button.setEnabled(False)
        self.mic_test_label.setText("يسجّل… تكلّم الآن")
        self._mic_test = MicTester(self.cfg.get("device"), 3.0)
        self._mic_test.done.connect(self._mic_test_done)
        self._mic_test.start()

    def _mic_test_done(self, peak: float, gain: float, error: str) -> None:
        self.mic_test_button.setEnabled(True)
        if error:
            self.mic_test_label.setText(f"تعذّر فتح المايك: {error}")
            return
        if peak < 1e-4:
            self.mic_test_label.setText("لا يصل صوت! تأكد أن المايك غير مكتوم "
                                        "(إعدادات ويندوز ← الخصوصية ← الميكروفون)")
            return
        self.mic_test_label.setText(f"وصل صوت بمستوى {peak:.4f} · الرفع التلقائي ×{gain:.1f}"
                                    + ("  (صوت منخفض — ارفع الحساسية)" if peak < 0.02 else ""))

    def open_log_file(self) -> None:
        path = Path(self.cfg.get("log", ""))
        if path.exists():
            try:
                os.startfile(path)  # noqa: S606 -- Windows "open with default app"
            except OSError as exc:
                self._note(f"تعذّر فتح الملف: {exc}")
        else:
            self._note(f"لا يوجد ملف سجل بعد: {path}")

    # ------------------------------------------------------------------- status
    def _set_status(self, active: bool, problem: bool = False) -> None:
        if problem:
            self.status_dot.setStyleSheet("color:#b23c17;font-size:22px;")
            self.status_label.setText("مشكلة في تحميل النموذج")
        elif active:
            self.status_dot.setStyleSheet("color:#0f9d58;font-size:22px;")
            self.status_label.setText(TR["listening"])
        else:
            self.status_dot.setStyleSheet("color:#8a93a3;font-size:22px;")
            self.status_label.setText(TR["ready"] if self._model else TR["loading"])
        self.mode_label.setText("اللهجة السعودية" if self.engine.mode == "dialect" else "الفصحى")
        self.toggle_button.setText("أوقف الإملاء" if active else "ابدأ الإملاء")
        self.toggle_button.setStyleSheet(
            "QPushButton{background:%s;color:white;font-size:16px;font-weight:700;"
            "border-radius:8px;}QPushButton:disabled{background:#c3c9d4;}"
            % ("#b23c17" if active else "#2f6feb"))
        # the window icon answers to the engine's state, the tray to the theme
        self.setWindowIcon(app_icon(app_icons.window_state(
            active, self._model is not None)))
        if getattr(self, "tray", None):
            self.tray.setIcon(self._tray_icon(active))
            # «استماع» متاح عندما لا يعمل، و«صمت» عندما يعمل -- لا لبس في القائمة
            self.tray_listen.setEnabled(not active)
            self.tray_silence.setEnabled(active)
            self.tray.setToolTip(f"{branding.TITLE} — {'يستمع' if active else 'جاهز'}")

    def _tail_log(self) -> None:
        """Show the engine log in the window (a QTimer, not a thread)."""
        path = Path(self.cfg.get("log", ""))
        if path.exists():
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
                text = "\n".join(lines)
                if text != self.log_box.toPlainText():
                    self.log_box.setPlainText(text)
                    self.log_box.verticalScrollBar().setValue(
                        self.log_box.verticalScrollBar().maximum())
            except OSError:
                pass
        QTimer.singleShot(2000, self._tail_log)

    def on_engine_event(self, kind: str, payload: dict) -> None:
        """UI-thread side of the engine events."""
        if kind == "state":
            self._set_status(bool(payload.get("active")))
        elif kind == "partial":
            # the words the recogniser is still unsure about: the fastest way to
            # see that the microphone is working before text is committed
            self.heard_label.setText(f"يسمع الآن: {payload.get('text', '')}")
        elif kind == "typed":
            text = payload.get("text", "")
            if text:
                self.transcript.moveCursor(self.transcript.textCursor().End)
                self.transcript.insertPlainText(text)
                self.heard_label.setText("يسمع الآن: —")
            self.meter_text.setText(f"{payload.get('total', 0)} حرفًا")
        elif kind == "meter":
            gain = payload.get("gain", 1.0)
            peak = payload.get("peak", 0.0)
            self.meter.setValue(min(100, int(peak * 200)))
            self.meter_text.setText(f"ذروة {peak:.4f} · رفع ×{gain:.1f}")
        elif kind == "error":
            self._note(payload.get("message", ""))
        elif kind == "device-fallback":
            self._note("تم التحويل إلى المايك الافتراضي للنظام")
            self.device_combo.setCurrentIndex(self.device_combo.findData(None))


class App(QApplication):
    """QApplication that forwards engine events onto the UI thread."""

    def __init__(self, argv: list[str]):
        super().__init__(argv)
        self.setApplicationName(APP_NAME)
        self.setQuitOnLastWindowClosed(False)
        self.setFont(QFont("Segoe UI", 10))


def build_window(config_path: Path, injector: str | None = None,
                 tray: bool = True, render_only: bool = False) -> MainWindow:
    cfg = load_config(config_path)
    app = QApplication.instance()
    if app is not None:
        # the window must open in the user's chosen theme, not the default one
        apply_theme(app, cfg.get("appearance", "system"))
    window = MainWindow(cfg, config_path, headless_tray=not tray, injector=injector,
                        render_only=render_only)
    window.event_received.connect(window.on_engine_event)
    return window


def _selftest(config_path: Path, shot: Path | None, tray: bool, model_wait: float = 90.0) -> int:
    """Drive every control and report, so the window is verified without eyes.

    Works on a *copy* of the real config: a self-test must never change the
    settings the user is actually running with.
    """
    report: list[str] = []
    work_dir = Path(tempfile.mkdtemp(prefix=f"{branding.SLUG}-selftest-"))
    work_config = work_dir / "config.json"
    copied = json.loads(config_path.read_text(encoding="utf-8"))
    for key in ("model", "log"):
        value = copied.get(key)
        if value and not Path(str(value)).is_absolute():
            # a relative path means "next to the config file", so copying the
            # config elsewhere would lose the model: resolve it first
            copied[key] = str((config_path.parent / str(value)).resolve())
    work_config.write_text(json.dumps(copied, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")

    window = build_window(work_config, injector="stdout", tray=tray)
    window.show()
    app = QApplication.instance()
    failures = 0

    def step(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        if not ok:
            failures += 1
        report.append(f"{'PASS' if ok else 'FAIL'}  {name}{'  — ' + detail if detail else ''}")

    def info(name: str, detail: str = "") -> None:
        report.append(f"INFO  {name}{'  — ' + detail if detail else ''}")

    def wait_for(predicate, seconds: float) -> bool:
        """Pump the Qt event loop while a background thread finishes."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            app.processEvents()
            if predicate():
                return True
            time.sleep(0.05)
        app.processEvents()
        return predicate()

    step("window built right-to-left", window.layoutDirection() == Qt.RightToLeft)
    step("start button exists and is large enough to hit",
         window.toggle_button.minimumHeight() >= 40,
         f"{window.toggle_button.minimumHeight()}px")
    window.reload_devices()
    step("system microphones listed", window.device_combo.count() >= 1,
         f"{window.device_combo.count()} entries")
    step("installed models listed", window.model_combo.count() >= 1,
         f"{window.model_combo.count()} entries")
    info("tray available", f"{QSystemTrayIcon.isSystemTrayAvailable()}")

    # hotkeys: saved through the same path the field uses
    window._hotkey_changed("hotkey", "ctrl+alt+d")
    step("dictate hotkey saved", [str(x) for x in window.cfg["hotkey"]] == ["ctrl+alt+d"],
         str(window.cfg["hotkey"]))
    info("hotkey availability check runs", f"ctrl+alt+d → {hotkey_claim('ctrl+alt+d')}")

    # microphone and sensitivity
    window.sens_slider.setValue(70)
    target = sensitivity_to_target(70)
    step("sensitivity reaches the engine",
         window.engine.agc is not None and abs(window.engine.agc.target - target) < 1e-6,
         f"target={target}")
    window.agc_check.setChecked(False)
    step("auto-gain can be switched off", window.engine.agc is None)
    window.agc_check.setChecked(True)
    step("auto-gain comes back", window.engine.agc is not None)

    # pause separator: seconds + fraction, and the glyph
    window.pause_spin.setValue(2.5)
    window.sep_combo.setCurrentIndex(1)
    step("pause separator saved (2.5s + full stop)",
         abs(float(window.cfg["pause_seconds"]) - 2.5) < 1e-6 and window.cfg["pause_sep"] == ".",
         f"{window.cfg['pause_seconds']}s {window.cfg['pause_sep']!r}")

    # a device change has to reach the audio thread as a reopen request
    if window.device_combo.count() > 1:
        window.device_combo.setCurrentIndex(1)
        step("device change asks the microphone stream to reopen",
             window.cfg["device"] == window.device_combo.currentData(),
             f"device={window.cfg['device']!r} reload={window.engine._reload.is_set()}")

    on_disk = json.loads(work_config.read_text(encoding="utf-8"))
    saved_hotkey = on_disk.get("hotkey")
    saved_hotkey = [saved_hotkey] if isinstance(saved_hotkey, str) else list(saved_hotkey or [])
    step("settings written to the config file",
         on_disk.get("pause_sep") == "." and saved_hotkey == ["ctrl+alt+d"],
         f"{len(on_disk)} keys, hotkey={saved_hotkey}, pause_sep={on_disk.get('pause_sep')!r}")
    info("this run used a copy, the real config is untouched", str(config_path))

    # the model, and start/stop driven by the button (the real integration)
    if wait_for(lambda: window._model is not None, model_wait):
        step("model loaded", True, window.model_status.text())
        window.toggle_dictation()
        step("button starts dictation", wait_for(lambda: window.engine.active, 20),
             time.strftime("%H:%M:%S"))
        time.sleep(1.2)
        window.toggle_dictation()
        step("button stops dictation", wait_for(lambda: not window.engine.active, 20))
        step("status follows the engine", bool(window.status_label.text()),
             window.status_label.text())
    else:
        step("model loaded", False, f"not ready after {model_wait:.0f}s: "
                                    f"{window.model_status.text()}")

    # تبويب النماذج: شبكة الأمان إن فشل تنزيل التثبيت
    import model_store

    rows = getattr(window, "model_rows", {})
    step("models tab lists every free Arabic model",
         len(rows) == len(model_store.ARABIC_MODELS), f"{len(rows)} rows")
    default_row = rows.get(model_store.DEFAULT_MODEL)
    step("the default model has its own row", default_row is not None)
    if default_row is not None:
        installed = model_store.is_installed(model_store.DEFAULT_MODEL)
        step("a missing model offers a download button",
             default_row["download"].isEnabled() != installed,
             f"installed={installed} download_enabled={default_row['download'].isEnabled()}")
        step("rows show the folder the app actually uses",
             str(model_store.models_dir()) in window.models_dir_label.text(),
             window.models_dir_label.text())

    # قائمة الأيقونة الجانبية: البنود الأربعة التي طلبها عماد بالنص
    if getattr(window, "tray", None):
        menu_items = [action.text() for action in window.tray.contextMenu().actions()
                      if not action.isSeparator()]
        for wanted in ("استماع", "صمت", "صفحة البرنامج", "إغلاق تمامًا"):
            step(f"tray menu has «{wanted}»", wanted in menu_items,
                 " · ".join(menu_items))
        step("tray offers استماع and greys صمت while idle",
             window.tray_listen.isEnabled() and not window.tray_silence.isEnabled(),
             f"listen={window.tray_listen.isEnabled()} silence={window.tray_silence.isEnabled()}")

    # المظهر: يختاره المستخدم ويُطبَّق فورًا
    import app_theme

    appearances = [window.appearance_combo.itemData(i)
                   for i in range(window.appearance_combo.count())]
    step("appearance offers system/dark/light",
         set(appearances) == set(app_theme.APPEARANCES), str(appearances))
    window.appearance_combo.setCurrentIndex(appearances.index("dark"))
    applied = app.styleSheet()
    step("choosing a theme applies it at once", bool(applied) and "#1B241F" in applied,
         "dark sheet applied")
    window.appearance_combo.setCurrentIndex(appearances.index("light"))
    step("the light theme replaces it", "#F7F9F8" in app.styleSheet())
    step("the choice is saved to the config",
         window.cfg.get("appearance") == "light", str(window.cfg.get("appearance")))

    # «حول البرنامج»: الإصدار والمؤلف ولينكدإن كما طلبها عماد
    about = AboutDialog(window)
    texts = [about.version_label.text(), about.author_label.text(),
             about.link_label.text(), window.windowTitle()]
    step("About shows the version", branding.VERSION in about.version_label.text(),
         about.version_label.text())
    step("About names the author", branding.AUTHOR_AR in about.author_label.text(),
         about.author_label.text())
    step("About carries the dedication (صدقة)", branding.DEDICATION_AR in
         about.dedication_label.text(), about.dedication_label.text())
    step("About links to LinkedIn", branding.LINKEDIN in about.link_label.text(),
         branding.LINKEDIN_LABEL)
    step("About keeps the product name", branding.PRODUCT_EN in texts[3], texts[3])
    step("About box has a working link button", about.linkedin_button.isEnabled())
    about.close()

    if shot:
        window.resize(760, 660)
        app.processEvents()
        window.grab().save(str(shot))
        step("screenshot written", shot.exists() and shot.stat().st_size > 5000,
             f"{shot} ({shot.stat().st_size if shot.exists() else 0} bytes)")

    report.append(f"SELFTEST {'OK' if not failures else 'FAILED'} ({failures} failures)")
    print("\n".join(report), flush=True)

    window._quitting = True
    if getattr(window, "tray", None):
        window.tray.hide()
    app.quit()
    shutil.rmtree(work_dir, ignore_errors=True)
    return 1 if failures else 0



def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{branding.PRODUCT_EN} settings window")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--injector", choices=["sendinput", "clipboard", "stdout"])
    parser.add_argument("--shot", type=Path, help="render the window to a PNG and exit")
    parser.add_argument("--shot-about", type=Path,
                        help="render the About box to a PNG and exit")
    parser.add_argument("--selftest", action="store_true",
                        help="drive every control, print a report and exit")
    parser.add_argument("--no-tray", action="store_true", help="do not create a tray icon")
    parser.add_argument("--appearance", choices=list(app_theme.APPEARANCES),
                        help="override the window colours for this run only")
    parser.add_argument("--cli", action="store_true",
                        help="run the command-line engine instead of the window "
                             "(the packaged Keyboardless.exe carries both)")
    parser.add_argument("--shot-tab", type=int, default=0,
                        help="which tab to show in --shot (0=الاختصارات 2=النماذج)")
    parser.add_argument("--model-wait", type=float, default=90.0,
                        help="seconds the self-test waits for the recogniser to load")
    args, unknown = parser.parse_known_args(argv)
    if args.cli:
        # the frozen executable carries both faces: hand the rest of the command
        # line to the engine exactly as if it had been called directly
        return run_cli(unknown)

    app = App(sys.argv[:1])
    tray = not args.no_tray
    if args.selftest:
        return _selftest(args.config, args.shot, tray, model_wait=args.model_wait)
    if args.shot_about:
        dialog = AboutDialog()
        dialog.setLayoutDirection(Qt.RightToLeft)
        dialog.resize(470, 380)
        dialog.show()
        QTimer.singleShot(1200, lambda: (dialog.grab().save(str(args.shot_about)), app.quit()))
        app.exec()
        return 0
    if args.shot:
        window = build_window(args.config, injector=args.injector or "stdout", tray=False,
                              render_only=True)
        window.resize(760, 660)
        if 0 <= args.shot_tab < window.tabs.count():
            window.tabs.setCurrentIndex(args.shot_tab)
        QTimer.singleShot(1500, lambda: (window.grab().save(str(args.shot)), app.quit()))
        app.exec()
        return 0
    window = build_window(args.config, injector=args.injector, tray=tray)
    apply_theme(app, args.appearance or window.cfg.get("appearance", "system"))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
