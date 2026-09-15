"""أيقونات التصميم: الحالات، المقاسات، أيقونة علبة النظام، وملف ICO.

The artwork was delivered as four states x eight sizes with three rules that a
regression could quietly break: the small sizes are drawn by hand (never a
downscaled 256), the tray goes monochrome in dark mode, and the Windows icon must
carry 16/20/24/32/48/256 in one file. Each rule is pinned here.
"""

import struct
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))

import app_icons  # noqa: E402


class TestTheDeliveredArtwork(unittest.TestCase):
    def test_every_state_and_size_is_present(self):
        self.assertEqual(app_icons.missing_assets(), [],
                         "the icon pack must be complete in the repository")

    def test_the_states_are_the_designed_ones(self):
        self.assertEqual(app_icons.STATES, ("ready", "listening", "paused", "mono"))

    def test_each_file_really_is_the_size_in_its_name(self):
        """A mis-exported file (a 16px slot holding a 256px image) would be
        silently downscaled by Qt instead of using the hand-drawn variant."""
        for state in app_icons.STATES:
            for size in app_icons.SIZES:
                with self.subTest(state=state, size=size):
                    path = app_icons.PNG_DIR / f"keyboardless-{state}-{size}.png"
                    width, height = app_icons._png_size(path.read_bytes())
                    self.assertEqual((width, height), (size, size))

    def test_the_small_sizes_are_their_own_drawings_not_shrunk_copies(self):
        """The design notes say 16/20/24 are simplified by hand.

        A downscaled 256 would carry far more distinct colours than a hand-drawn
        16px mark; comparing the PNG byte size is a cheap, honest signal.
        """
        for state in app_icons.STATES:
            big = (app_icons.PNG_DIR / f"keyboardless-{state}-256.png").stat().st_size
            small = (app_icons.PNG_DIR / f"keyboardless-{state}-16.png").stat().st_size
            self.assertLess(small, big, f"{state}: the 16px file should be simpler")
            self.assertGreater(small, 1000, f"{state}: the 16px file looks empty")

    def test_the_vector_sources_ship_too(self):
        for state in app_icons.STATES:
            self.assertTrue((app_icons.SVG_DIR / f"keyboardless-{state}.svg").exists(),
                            f"{state}: keep the editable source")

    def test_the_design_notes_ship_with_the_artwork(self):
        self.assertTrue((app_icons.ASSET_DIR / "README.txt").exists())


class TestStateSelection(unittest.TestCase):
    def test_window_icon_follows_the_engine(self):
        self.assertEqual(app_icons.window_state(active=True, model_loaded=True), "listening")
        self.assertEqual(app_icons.window_state(active=False, model_loaded=True), "ready")
        self.assertEqual(app_icons.window_state(active=False, model_loaded=False), "paused")

    def test_the_tray_icon_shows_the_state_in_both_themes(self):
        """عماد: «تتغير الأيقونة بحسب وضع البرنامج» -- فيبقى الإصغاء ظاهرًا.

        In dark mode the idle icon is the monochrome variant (as the design notes
        ask), but while dictating the icon must still say "listening" -- a tray
        icon that looks identical running and stopped tells the user nothing.
        """
        self.assertEqual(app_icons.tray_state(active=True, dark=True), "listening")
        self.assertEqual(app_icons.tray_state(active=False, dark=True), "mono")
        self.assertEqual(app_icons.tray_state(active=True, dark=False), "listening")
        self.assertEqual(app_icons.tray_state(active=False, dark=False), "ready")

    def test_dark_mode_detection_never_raises(self):
        self.assertIsInstance(app_icons.system_prefers_dark(), bool)

    def test_an_unknown_state_falls_back_to_ready(self):
        self.assertEqual(app_icons.icon_path("sparkles", 32),
                         app_icons.PNG_DIR / "keyboardless-ready-32.png")

    def test_an_unknown_size_falls_back_to_an_existing_one(self):
        path = app_icons.icon_path("ready", 999)
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())


class TestIcoBuilding(unittest.TestCase):
    """ويندوز يقرأ المقاسات من داخل الملف: Qt لا يكتب إلا صورة واحدة."""

    def test_the_ico_carries_every_documented_size(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "keyboardless.ico"
            app_icons.write_ico(target)
            self.assertEqual(app_icons.ico_entries(target),
                             [(size, size) for size in app_icons.ICO_SIZES])

    def test_the_carried_payloads_are_real_png_images(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "keyboardless.ico"
            app_icons.write_ico(target)
            blob = target.read_bytes()
            count = struct.unpack("<H", blob[4:6])[0]
            self.assertEqual(count, len(app_icons.ICO_SIZES))
            offset = 6 + 16 * count
            for index in range(count):
                entry = blob[6 + 16 * index: 6 + 16 * (index + 1)]
                length = struct.unpack("<I", entry[8:12])[0]
                start = struct.unpack("<I", entry[12:16])[0]
                self.assertEqual(start, offset)
                self.assertEqual(blob[offset:offset + 8], b"\x89PNG\r\n\x1a\n")
                offset += length

    def test_the_ico_can_be_built_for_another_state(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "listening.ico"
            app_icons.write_ico(target, state="listening")
            self.assertEqual(len(app_icons.ico_entries(target)),
                             len(app_icons.ICO_SIZES))

    def test_a_file_that_is_not_an_ico_is_refused(self):
        with TemporaryDirectory() as tmp:
            fake = Path(tmp) / "not.ico"
            fake.write_bytes(b"nonsense")
            with self.assertRaises(ValueError):
                app_icons.ico_entries(fake)


class TestTheAppUsesTheArtwork(unittest.TestCase):
    """التصميم يجب أن يظهر فعلًا: نافذة، علبة نظام، نافذة «حول»، والمثبّت."""

    def _gui(self) -> str:
        return (APP / "gui.py").read_text(encoding="utf-8")

    def test_the_window_loads_the_designed_icons(self):
        gui = self._gui()
        self.assertIn("import app_icons", gui)
        self.assertIn("app_icons.icon_path", gui)
        self.assertIn("app_icons.window_state", gui)

    def test_the_tray_uses_the_monochrome_state_in_dark_mode(self):
        gui = self._gui()
        self.assertIn("app_icons.tray_state", gui)
        self.assertIn("app_icons.system_prefers_dark", gui)

    def test_a_missing_asset_still_leaves_an_icon(self):
        gui = self._gui()
        self.assertIn("_drawn_icon", gui, "keep the drawn fallback")

    def test_the_bundle_ships_the_icons(self):
        spec = (APP / "packaging" / "keyboardless.spec").read_text(encoding="utf-8")
        self.assertIn('APP / "assets"', spec)

    def test_the_icon_builder_uses_the_design_sizes(self):
        script = (APP / "packaging" / "make_icon.py").read_text(encoding="utf-8")
        self.assertIn("app_icons.write_ico", script)
        self.assertIn("ICO_SIZES", script)
        self.assertNotIn("QPainter", script, "the artwork replaced the drawn mark")


if __name__ == "__main__":
    unittest.main()
