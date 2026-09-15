"""مظهر البرنامج: الاختيار، الوضع الفعلي، والألوان.

عماد asked for a choice: dark, or the normal Windows colours -- following Windows
when he has not decided. The palette is taken from the icon design notes, so the
window and the artwork agree on the same greens and amber.
"""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))

import app_theme  # noqa: E402


class TestTheChoice(unittest.TestCase):
    def test_the_three_options_the_user_asked_for(self):
        self.assertEqual(app_theme.APPEARANCES, ("system", "dark", "light"))
        values = [value for _label, value in app_theme.labels()]
        self.assertEqual(values, ["system", "dark", "light"])
        self.assertTrue(all(label for label, _ in app_theme.labels()))

    def test_system_follows_windows(self):
        self.assertEqual(app_theme.resolve("system", system_dark=True), "dark")
        self.assertEqual(app_theme.resolve("system", system_dark=False), "light")

    def test_an_explicit_choice_wins_over_windows(self):
        self.assertEqual(app_theme.resolve("light", system_dark=True), "light")
        self.assertEqual(app_theme.resolve("dark", system_dark=False), "dark")

    def test_an_unknown_value_falls_back_to_system(self):
        self.assertEqual(app_theme.resolve("neon", system_dark=True), "dark")
        self.assertEqual(app_theme.resolve("", system_dark=False), "light")


class TestColours(unittest.TestCase):
    def test_both_themes_define_every_key(self):
        keys = set(app_theme.PALETTES["dark"])
        self.assertEqual(set(app_theme.PALETTES["light"]), keys)
        for theme, palette in app_theme.PALETTES.items():
            for key, value in palette.items():
                self.assertRegex(value, r"^#[0-9A-Fa-f]{6}$", f"{theme}.{key}")

    def test_the_dark_theme_is_the_design_dark(self):
        """#1B241F is the designer's dark, and it is what the user called «أسود»."""
        self.assertEqual(app_theme.PALETTES["dark"]["bg"].upper(), "#1B241F")
        self.assertEqual(app_theme.PALETTES["light"]["bg"].upper(), "#F7F9F8")

    def test_the_dedication_colour_reads_on_both_themes(self):
        for theme in ("dark", "light"):
            dedication = app_theme.PALETTES[theme]["dedication"]
            background = app_theme.PALETTES[theme]["bg"]
            self.assertNotEqual(dedication.lower(), background.lower())
            # a light text on a dark background and vice versa
            def luminance(colour: str) -> float:
                red, green, blue = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
                return (0.299 * red + 0.587 * green + 0.114 * blue) / 255
            difference = abs(luminance(dedication) - luminance(background))
            self.assertGreater(difference, 0.35,
                               f"{theme}: contrast too low for the dedication line")


class TestStylesheet(unittest.TestCase):
    def test_the_sheet_carries_the_theme_background(self):
        self.assertIn("#1B241F", app_theme.stylesheet("dark"))
        self.assertIn("#F7F9F8", app_theme.stylesheet("light"))

    def test_the_sheet_styles_the_widgets_that_matter(self):
        sheet = app_theme.stylesheet("dark")
        for selector in ("QWidget", "QPushButton", "QLineEdit", "QComboBox",
                         "QPlainTextEdit", "QGroupBox", "QMenu", "QTabBar::tab"):
            self.assertIn(selector, sheet, selector)

    def test_the_sheet_follows_the_system_when_asked(self):
        self.assertIn("#1B241F", app_theme.stylesheet("system", system_dark=True))
        self.assertIn("#F7F9F8", app_theme.stylesheet("system", system_dark=False))


class TestTheWindowUsesIt(unittest.TestCase):
    def test_the_window_applies_the_saved_appearance(self):
        gui = (APP / "gui.py").read_text(encoding="utf-8")
        self.assertIn("import app_theme", gui)
        self.assertIn("apply_theme", gui)
        self.assertIn('cfg.get("appearance", "system")', gui)
        self.assertIn("app_theme.labels()", gui, "the choice must be in the window")

    def test_the_appearance_is_saved_like_any_other_setting(self):
        """It goes through update_config_keys, which only validates hotkey fields."""
        source = (APP / "ar_dictate.py").read_text(encoding="utf-8")
        self.assertIn('HOTKEY_FIELDS = ("hotkey", "mode_key", "quit_key")', source)


if __name__ == "__main__":
    unittest.main()
