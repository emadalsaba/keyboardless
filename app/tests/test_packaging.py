"""التغليف: مسارات النسخة المثبَّتة، النموذج غير المضمّن، ونقطة الدخول الموحّدة.

A packaged app is a different environment from a source checkout: it cannot write
inside its own folder, it has no ``app/config.json`` until one is created, and its
command line is the only way to reach the engine. Each of those is pinned here so
a regression shows up in the suite instead of on the user's machine.
"""

import contextlib
import io
import json
import os
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
ROOT = APP.parent
sys.path.insert(0, str(APP))

import ar_dictate  # noqa: E402
import branding  # noqa: E402

PACKAGING = APP / "packaging"


class TestUserDataDir(unittest.TestCase):
    def test_source_checkout_keeps_files_beside_the_project(self):
        os.environ.pop("AR_DICTATE_USER_DIR", None)
        self.assertEqual(ar_dictate.user_data_dir(), APP.parent)

    def test_packaged_app_gets_a_writable_folder(self):
        with self.subTest("explicit folder wins"):
            os.environ["AR_DICTATE_USER_DIR"] = str(ROOT / "tmp-user-dir")
            try:
                self.assertEqual(ar_dictate.user_data_dir(), ROOT / "tmp-user-dir")
            finally:
                os.environ.pop("AR_DICTATE_USER_DIR", None)

    def test_the_default_config_follows_the_environment(self):
        self.assertIsInstance(ar_dictate.DEFAULT_CONFIG, Path)
        self.assertTrue(str(ar_dictate.DEFAULT_CONFIG).endswith("config.json"))


class TestFirstRunConfig(unittest.TestCase):
    """A fresh install has no config: it must be created, once."""

    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.user_dir = Path(self.tmp.name)
        os.environ["AR_DICTATE_USER_DIR"] = str(self.user_dir)
        self.addCleanup(os.environ.pop, "AR_DICTATE_USER_DIR", None)

    def test_creates_a_config_with_absolute_paths_for_the_user(self):
        target = self.user_dir / "config.json"
        self.assertTrue(ar_dictate.ensure_user_config(target))
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertTrue(Path(data["model"]).is_absolute())
        self.assertEqual(Path(data["model"]).parent, self.user_dir / "models")
        self.assertEqual(Path(data["log"]).parent, self.user_dir)
        self.assertEqual(Path(data["log"]).name, branding.LOG_NAME)
        # the settings the user actually cares about survive the copy
        for key in ("hotkey", "mode_key", "quit_key", "pause_seconds", "pause_sep"):
            self.assertIn(key, data)

    def test_never_overwrites_an_existing_config(self):
        target = self.user_dir / "config.json"
        target.write_text('{"mode": "dialect"}', encoding="utf-8")
        self.assertFalse(ar_dictate.ensure_user_config(target))
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["mode"], "dialect")

    def test_the_created_config_is_readable_by_the_engine(self):
        target = self.user_dir / "config.json"
        ar_dictate.ensure_user_config(target)
        cfg = ar_dictate.load_config(target)
        self.assertTrue(Path(cfg["model"]).is_absolute())
        self.assertEqual(cfg["sample_rate"], 16000)


class TestSingleEntryPoint(unittest.TestCase):
    """Keyboardless.exe carries both the window and the engine."""

    def test_the_engine_cli_accepts_an_explicit_argv(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = ar_dictate.main(["--about"])
        self.assertEqual(code, 0)
        printed = buffer.getvalue()
        self.assertIn(branding.PRODUCT_EN, printed)
        self.assertIn(branding.VERSION, printed)
        self.assertIn(branding.AUTHOR_AR, printed)
        self.assertIn(branding.LINKEDIN, printed)

    def test_the_window_forwards_cli_arguments_to_the_engine(self):
        gui = (APP / "gui.py").read_text(encoding="utf-8")
        self.assertIn('"--cli"', gui)
        # the forward goes through run_cli, which exists because a windowed build
        # has no stdout and an unhandled exception would hang on a modal dialog
        self.assertIn("run_cli(unknown)", gui)
        self.assertIn("ar_dictate.main(arguments)", gui)

    def test_the_packaged_exe_can_fetch_its_own_model(self):
        """The installer runs on machines without Python: the exe does the work.

        ``Keyboardless.exe --cli --ensure-model`` is what the installer calls, so
        the download logic must be reachable from the frozen engine, not only
        from a source checkout.
        """
        source = (APP / "ar_dictate.py").read_text(encoding="utf-8")
        self.assertIn('"--ensure-model"', source)
        self.assertIn('"--models"', source)
        self.assertIn("import model_store", source)

    def test_listing_models_works_through_the_engine_cli(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = ar_dictate.main(["--models"])
        self.assertEqual(code, 0)
        printed = buffer.getvalue()
        self.assertIn("vosk-model-small-ar-0.3", printed)
        self.assertIn("مثبَّت", printed)

    def test_version_flag_still_works_through_the_engine(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            with self.assertRaises(SystemExit) as caught:
                ar_dictate.main(["--version"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn(branding.VERSION, buffer.getvalue())


def _import_gui_or_skip():
    """The window module needs a Qt platform plugin: skip where it cannot load.

    On this Linux server PySide6 has no libEGL, so the window itself cannot be
    imported; on the Windows target (and in CI there) these tests run for real.
    """
    try:
        import gui  # noqa: PLC0415

        return gui
    except Exception as exc:  # noqa: BLE001
        raise unittest.SkipTest(f"Qt platform unavailable: {exc}") from exc


class TestCommandLineFromThePackagedExe(unittest.TestCase):
    """``Keyboardless.exe --cli …``: no console, and never a modal error box.

    The first frozen run hung forever: an exception reached PyInstaller's
    bootloader, which showed a dialog nobody can see over SSH, and the process
    waited on it while holding its output pipe. These tests pin the three
    behaviours that make the CLI safe in a windowed build.
    """

    def setUp(self):
        self.gui = _import_gui_or_skip()
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        os.environ["AR_DICTATE_USER_DIR"] = self.tmp.name
        self.addCleanup(os.environ.pop, "AR_DICTATE_USER_DIR", None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_normal_run_prints_and_keeps_a_copy_for_support(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = self.gui.run_cli(["--about"])
        self.assertEqual(code, 0)
        self.assertIn(branding.PRODUCT_EN, buffer.getvalue())
        saved = Path(self.tmp.name) / "cli-last.txt"
        self.assertTrue(saved.exists(), "a support request needs something to read")
        self.assertIn(branding.VERSION, saved.read_text(encoding="utf-8"))

    def test_a_bad_argument_returns_an_exit_code_instead_of_raising(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            code = self.gui.run_cli(["--not-a-real-flag"])
        self.assertEqual(code, 2, "argparse's usage error becomes an exit code")

    def test_an_internal_crash_is_captured_not_shown_as_a_dialog(self):
        def explode(_arguments):
            raise RuntimeError("engine died")

        original = ar_dictate.main
        ar_dictate.main = explode
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                code = self.gui.run_cli(["--about"])
        finally:
            ar_dictate.main = original
        self.assertEqual(code, 1)
        saved = (Path(self.tmp.name) / "cli-last.txt").read_text(encoding="utf-8")
        self.assertIn("engine died", saved, "the traceback must survive for support")

    def test_the_tee_survives_a_missing_console(self):
        buffer = io.StringIO()
        tee = self.gui._Tee(None, buffer)
        tee.write("hello")
        self.assertEqual(buffer.getvalue(), "hello")


class TestPackagingFiles(unittest.TestCase):
    def test_the_spec_builds_one_named_executable(self):
        spec = (PACKAGING / "keyboardless.spec").read_text(encoding="utf-8")
        self.assertIn('name="Keyboardless"', spec)
        self.assertIn("console=False", spec, "the window needs no console box")
        self.assertIn("collect_all", spec)
        for package in ("vosk", "sounddevice"):
            self.assertIn(f'"{package}"', spec, "its data files must be collected")

    def test_the_models_are_not_bundled(self):
        """Bundling them would turn a small app into a 300-700 MB download.

        The check looks at the *code* lines: prose may mention the models folder
        (it explains where they are downloaded to), but no ``datas``/``binaries``
        entry may point at one.
        """
        spec = (PACKAGING / "keyboardless.spec").read_text(encoding="utf-8")
        for line in spec.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("*"):
                continue
            if "datas" in line or "binaries" in line:
                self.assertNotIn("models", line, f"models are bundled here: {stripped}")
        self.assertIn("config.json", spec, "the default settings do ship")

    def test_the_build_script_runs_pyinstaller_and_reports_sizes(self):
        script = (PACKAGING / "build_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("PyInstaller", script)
        self.assertIn("Keyboardless.exe", script)
        self.assertIn("--cli --about", script, "the built exe must be smoke-tested")

    def test_scripts_with_arabic_start_with_a_bom(self):
        """Windows PowerShell 5.1 reads a .ps1 as ANSI without a BOM.

        That turns the Arabic text into garbage and can break the parser
        outright -- it broke the build script with "the string is missing the
        terminator", which looks like a code error and is really an encoding one.
        """
        offenders = []
        for path in sorted(ROOT.glob("app/**/*.ps1")):
            raw = path.read_bytes()
            body = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
            if any(byte > 127 for byte in body) and not raw.startswith(b"\xef\xbb\xbf"):
                offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [], f"add a UTF-8 BOM to: {offenders}")

    def test_the_installer_script_asks_nothing_and_downloads_the_model(self):
        """The user asked for one thing: no questions, automatic model download.

        So: no directory page, no program-group page, and a single [Run] entry
        that fetches the Arabic model into the app's own folder — skipped when the
        model is already there, so a reinstall does not re-download 100 MB.
        """
        iss = (PACKAGING / "keyboardless.iss").read_text(encoding="utf-8")
        self.assertIn("DisableDirPage=yes", iss)
        self.assertIn("DisableProgramGroupPage=yes", iss)
        self.assertIn("PrivilegesRequired=lowest", iss, "no UAC prompt for the user")
        self.assertIn("--cli --ensure-model", iss)
        self.assertIn("Check: ModelMissing", iss)
        self.assertIn("function ModelMissing", iss)
        self.assertIn("runhidden waituntilterminated", iss)

    def test_the_installer_version_matches_the_app_version(self):
        """The file name said 1.0.1 while the About box said 1.0.2.

        Inno cannot read Python, so the number is written twice -- this test is
        what keeps the two from drifting apart.
        """
        import branding

        iss = (PACKAGING / "keyboardless.iss").read_text(encoding="utf-8")
        match = re.search(r'#define AppVersion "([^"]+)"', iss)
        self.assertIsNotNone(match, "AppVersion must be defined")
        self.assertEqual(match.group(1), branding.VERSION,
                         "installer name and About box must agree")

    def test_the_installer_carries_the_dedication(self):
        iss = (PACKAGING / "keyboardless.iss").read_text(encoding="utf-8")
        self.assertIn('#define Dedication', iss)
        self.assertIn("{#Dedication}", iss, "the welcome page must show it")

    def test_no_pascal_expression_starts_a_line_with_a_hash(self):
        """ISPP reads a leading '#' as a preprocessor directive.

        ``#13#10`` on its own line aborted the compiler with "Unknown
        preprocessor directive" -- an error that looks like Inno being broken and
        is really a line-continuation mistake.
        """
        iss = (PACKAGING / "keyboardless.iss").read_text(encoding="utf-8")
        allowed = ("#define", "#if", "#else", "#elif", "#endif", "#include",
                   "#pragma", "#error", "#undef", "#emit", "#for", "#sub", "#dim",
                   "#expr", "#insert", "#append", "#file")
        for number, line in enumerate(iss.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                self.assertTrue(stripped.startswith(allowed),
                                f"line {number}: {stripped[:40]!r} is not a directive")

    def test_the_installer_app_id_is_a_real_guid(self):
        """A GUID with a mnemonic in it (K3YB0ARD…) is rejected by the compiler."""
        iss = (PACKAGING / "keyboardless.iss").read_text(encoding="utf-8")
        # Inno escapes a literal brace by doubling it, so it is "{{GUID}":
        # opening two, closing one
        match = re.search(r"AppId=\{\{([0-9A-Fa-f-]+)\}", iss)
        self.assertIsNotNone(match, "AppId must be a GUID in double braces")
        self.assertRegex(match.group(1),
                         r"^[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$")

    def test_uninstalling_removes_the_downloaded_model(self):
        iss = (PACKAGING / "keyboardless.iss").read_text(encoding="utf-8")
        self.assertIn("[UninstallDelete]", iss)
        self.assertIn("Keyboardless\\models", iss,
                      "287 MB must not stay behind after an uninstall")

    def test_the_build_script_can_compile_the_installer(self):
        script = (PACKAGING / "build_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("-Installer", script)
        self.assertIn("ISCC.exe", script)
        self.assertIn("Inno Setup 6", script)

    def test_the_icon_generator_builds_a_multi_size_ico(self):
        """The designer asked for 16/20/24/32/48/256 inside one .ico file.

        The drawing moved to Emad's artwork, so the generator no longer paints:
        it assembles his exported PNGs (see test_icons for the detailed rules).
        """
        script = (PACKAGING / "make_icon.py").read_text(encoding="utf-8")
        self.assertIn("app_icons.write_ico", script)
        self.assertIn("ICO_SIZES", script)
        self.assertIn("ico_entries", script, "verify what was written, do not assume")


if __name__ == "__main__":
    unittest.main()
