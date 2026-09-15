"""هوية المنتج: الاسم Keyboardless (بدون كيبورد) في كل واجهة يراها المستخدم.

The product was renamed after the engine was already wired into a launcher, a
window, a tray icon and a page of documentation. A name that lives in five
places drifts, so this test pins the identity to :mod:`branding` and fails when
a surface keeps an old string.
"""

import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
ROOT = APP.parent
sys.path.insert(0, str(APP))

import branding  # noqa: E402
import model_store  # noqa: E402


class TestBrandStrings(unittest.TestCase):
    def test_the_product_is_named_once(self):
        self.assertEqual(branding.PRODUCT_EN, "Keyboardless")
        self.assertEqual(branding.PRODUCT_AR, "بدون كيبورد")
        self.assertIn(branding.PRODUCT_EN, branding.TITLE)
        self.assertIn(branding.PRODUCT_AR, branding.TITLE)
        self.assertIn(branding.PRODUCT_EN, branding.WINDOW_TITLE)
        self.assertIn(branding.TAGLINE, branding.WINDOW_TITLE)

    def test_version_line_names_the_product(self):
        self.assertIn(branding.PRODUCT_EN, branding.version_line())
        self.assertIn(branding.VERSION, branding.version_line())

    def test_launcher_names_follow_the_slug(self):
        for name in (branding.LAUNCHER, branding.LAUNCHER_GUI, branding.CHECKER):
            self.assertTrue(name.startswith(branding.SLUG), name)
            self.assertTrue((ROOT / name).is_file(), f"{name} must exist at the root")

    def test_the_data_folder_is_branded(self):
        self.assertEqual(branding.DATA_DIR.lower(), branding.SLUG)

    def test_the_version_tracks_the_visible_content(self):
        """1.0.2 added the dedication: the version moves with the About box."""
        self.assertEqual(branding.VERSION, "1.0.2")

    def test_the_dedication_is_written_as_asked(self):
        """عماد asked for it in his own words: صدقة عني وعن والديّ وأهلي."""
        text = branding.DEDICATION_AR
        for piece in ("صدقة", "عني", "والديّ", "أهلي", "أحتسبه"):
            self.assertIn(piece, text, piece)
        self.assertIn(branding.DEDICATION_AR, branding.about_text())

    def test_the_dedication_reaches_every_surface(self):
        gui = (APP / "gui.py").read_text(encoding="utf-8")
        self.assertIn("branding.DEDICATION_AR", gui)
        iss = (APP / "packaging" / "keyboardless.iss").read_text(encoding="utf-8")
        self.assertIn("Dedication", iss)
        readme = (APP / "README.md").read_text(encoding="utf-8")
        self.assertIn(branding.DEDICATION_AR, readme)

    def test_the_author_is_named_with_his_role(self):
        self.assertEqual(branding.AUTHOR_AR, "عماد السبع")
        self.assertEqual(branding.AUTHOR_ROLE_AR, "المبرمج")
        self.assertIn(branding.AUTHOR_AR, branding.AUTHOR_LINE_AR)
        self.assertIn(branding.AUTHOR_ROLE_AR, branding.AUTHOR_LINE_AR)

    def test_the_linkedin_address_is_a_full_https_url(self):
        self.assertTrue(branding.LINKEDIN.startswith("https://"))
        self.assertIn("linkedin.com/in/", branding.LINKEDIN)
        self.assertNotIn(" ", branding.LINKEDIN)

    def test_about_text_carries_everything_the_user_asked_for(self):
        text = branding.about_text()
        for piece in (branding.PRODUCT_EN, branding.PRODUCT_AR, branding.VERSION,
                      branding.AUTHOR_AR, branding.LINKEDIN):
            self.assertIn(piece, text)

    def test_the_log_name_is_deliberately_unchanged(self):
        """config.json owns the log path; renaming it orphans the existing logs."""
        self.assertEqual(branding.LOG_NAME, "dictate.log")


class TestBrandSurfaces(unittest.TestCase):
    """No user-visible surface may still print the old product name."""

    def _read(self, *parts: str) -> str:
        return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")

    def test_the_window_uses_the_brand(self):
        gui = self._read("app", "gui.py")
        self.assertIn("branding.WINDOW_TITLE", gui)
        self.assertIn("branding.PRODUCT_EN", gui)
        self.assertNotIn('APP_NAME = "ar-dictate"', gui)

    def test_the_window_has_an_about_box_reachable_from_the_tray(self):
        gui = self._read("app", "gui.py")
        self.assertIn("class AboutDialog", gui)
        self.assertIn("branding.AUTHOR_LINE_AR", gui)
        self.assertIn("branding.LINKEDIN", gui)
        self.assertIn("about_action", gui, "the tray menu must reach About too")

    def test_the_engine_uses_the_brand(self):
        engine = self._read("app", "ar_dictate.py")
        self.assertIn("import branding", engine)
        self.assertIn("branding.PRODUCT_EN", engine)
        self.assertNotIn('d.log("ar-dictate ready', engine)

    def test_the_console_launcher_prints_the_brand(self):
        launcher = self._read(branding.LAUNCHER)
        self.assertIn(branding.PRODUCT_EN, launcher)
        self.assertIn(branding.PRODUCT_AR, launcher)

    def test_the_readme_is_titled_with_the_brand(self):
        readme = self._read("app", "README.md")
        self.assertIn(branding.PRODUCT_EN, readme.splitlines()[0])
        self.assertNotIn("ar-dictate.cmd", readme,
                         "documentation must name the current launchers")

    def test_the_model_folder_and_user_agent_are_branded(self):
        store = self._read("app", "model_store.py")
        self.assertIn("branding.DATA_DIR", store)
        self.assertIn("branding.SLUG", store)

    def test_the_installer_ships_the_new_launchers(self):
        ps = self._read("app", "install_windows.ps1")
        for name in (branding.LAUNCHER, branding.LAUNCHER_GUI, branding.CHECKER):
            self.assertIn(name, ps)


class TestCliBranding(unittest.TestCase):
    def test_version_flag_prints_the_product(self):
        proc = subprocess.run([sys.executable, str(APP / "ar_dictate.py"), "--version"],
                              capture_output=True, text=True, encoding="utf-8",
                              cwd=str(ROOT))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(branding.PRODUCT_EN, proc.stdout + proc.stderr)
        self.assertIn(branding.VERSION, proc.stdout + proc.stderr)

    def test_the_log_line_at_startup_names_the_product(self):
        source = (APP / "ar_dictate.py").read_text(encoding="utf-8")
        self.assertIn("branding.VERSION} ready", source)


if __name__ == "__main__":
    unittest.main()
