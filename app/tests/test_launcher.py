"""Guard: Windows launchers must keep CRLF line endings.

cmd.exe mis-parses a .cmd file that only has LF endings: multi-line blocks such
as `if not exist (...)(\n ... \n)` swallow the following lines, so the launcher
exits silently and the app never starts. Authoring the file on Linux strips CRLF,
so the regression is easy to reintroduce -- this test fails loudly instead.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAUNCHERS = ("keyboardless.cmd", "keyboardless-gui.cmd", "keyboardless-check.cmd")
#: the pre-rename names still exist so an older shortcut keeps working
FORWARDERS = ("ar-dictate.cmd", "ar-dictate-gui.cmd", "ar-dictate-check.cmd")


class TestLauncherLineEndings(unittest.TestCase):
    def test_cmd_launchers_use_crlf(self):
        for name in LAUNCHERS:
            with self.subTest(launcher=name):
                launcher = ROOT / name
                self.assertTrue(launcher.is_file(), f"missing launcher: {launcher}")
                raw = launcher.read_bytes()
                crlf = raw.count(b"\r\n")
                lone_lf = raw.count(b"\n") - crlf
                self.assertEqual(
                    lone_lf,
                    0,
                    f"{name} has {lone_lf} lone LF line ending(s); cmd.exe needs CRLF",
                )
                self.assertGreater(crlf, 0, f"{name} has no CRLF line endings at all")

    def test_launcher_runs_the_app_and_has_no_stray_path_prefix(self):
        text = (ROOT / "keyboardless.cmd").read_text(encoding="utf-8").replace("\r\n", "\n")
        # the launcher cd's to its own folder, so paths are relative to the repo root
        self.assertIn('"app\\ar_dictate.py"', text)
        self.assertNotIn("app\\app\\", text)

    def test_the_settings_window_launcher_uses_pythonw(self):
        """A console box behind the window would look like a broken app."""
        text = (ROOT / "keyboardless-gui.cmd").read_text(encoding="utf-8")
        self.assertIn("pythonw.exe", text)

    def test_the_old_names_still_work(self):
        """A rename must not break a shortcut the user already made."""
        for name in FORWARDERS:
            with self.subTest(forwarder=name):
                path = ROOT / name
                self.assertTrue(path.is_file(), f"missing forwarder: {name}")
                raw = path.read_bytes()
                self.assertEqual(raw.count(b"\n") - raw.count(b"\r\n"), 0)
                text = raw.decode("utf-8")
                target = name.replace("ar-dictate", "keyboardless")
                self.assertIn(target, text, "the forwarder must name its replacement")
                self.assertIn("call", text.lower(), "the forwarder must chain to it")

    def test_installer_normalizes_line_endings_and_verifies(self):
        """The installer must not regenerate a dead LF launcher (it reads the
        .cmd from a Linux checkout)."""
        ps = (ROOT / "app" / "install_windows.ps1").read_text(encoding="utf-8")
        self.assertIn('$text -replace "`r?`n", "`r`n"', ps)
        self.assertIn("LF-only line ending", ps)
        for name in LAUNCHERS:
            self.assertIn(name, ps, f"installer does not install {name}")


if __name__ == "__main__":
    unittest.main()
