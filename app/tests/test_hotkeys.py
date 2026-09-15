"""Tests for the global-hotkey plumbing. Run:  python -m unittest discover -s tests

Regression guard: config.json uses the plain ``keyboard``-style form
("ctrl+alt+space"), but pynput's GlobalHotKeys only accepts the angle-bracket
form. Feeding the raw string raises ``ValueError: ctrl`` at startup, so the
app must translate before binding.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ar_dictate import pynput_combo  # noqa: E402


class TestPynputCombo(unittest.TestCase):
    def test_config_hotkeys_translate(self):
        self.assertEqual(pynput_combo("ctrl+alt+space"), "<ctrl>+<alt>+<space>")
        self.assertEqual(pynput_combo("ctrl+alt+m"), "<ctrl>+<alt>+m")
        self.assertEqual(pynput_combo("ctrl+alt+q"), "<ctrl>+<alt>+q")

    def test_raw_string_would_break_pynput(self):
        """The un-translated form is exactly what pynput rejects."""
        self.assertNotEqual(pynput_combo("ctrl+alt+space"), "ctrl+alt+space")
        self.assertTrue(pynput_combo("ctrl+alt+space").startswith("<"))

    def test_case_and_spacing_tolerated(self):
        self.assertEqual(pynput_combo(" Ctrl + Alt + Space "), "<ctrl>+<alt>+<space>")
        self.assertEqual(pynput_combo("CTRL+ALT+M"), "<ctrl>+<alt>+m")

    def test_aliases(self):
        self.assertEqual(pynput_combo("win+shift+s"), "<cmd>+<shift>+s")
        self.assertEqual(pynput_combo("control+f9"), "<ctrl>+<f9>")
        self.assertEqual(pynput_combo("escape"), "<esc>")
        self.assertEqual(pynput_combo("return"), "<enter>")

    def test_single_key(self):
        self.assertEqual(pynput_combo("space"), "<space>")
        self.assertEqual(pynput_combo("f9"), "<f9>")

    def test_named_keys_bracketed_chars_bare(self):
        """pynput 1.7.7: '<m>' is rejected, a bare 'm' is a char key."""
        combo = pynput_combo("ctrl+alt+m")
        self.assertIn("<ctrl>", combo)
        self.assertTrue(combo.endswith("+m"))

    def test_empty_rejected(self):
        for bad in ("", "   ", "+", " + "):
            with self.assertRaises(ValueError):
                pynput_combo(bad)

class TestHotkeyFields(unittest.TestCase):
    """The dictate key lives in config.json only -- nothing may hardcode it.

    Claude Desktop claims ctrl+alt+space machine-wide, so that combination must
    never come back as our default, and the launcher/check tools must read the
    key from the config instead of repeating a literal that then drifts.
    """

    ROOT = Path(__file__).resolve().parents[2]  # repo root: <repo>/app/tests/x.py
    CONFIG = ROOT / "app" / "config.json"

    def test_fallbacks_and_comma_form(self):
        from ar_dictate import combo_list, split_specs

        self.assertEqual(split_specs("ctrl+alt+d"), ["ctrl+alt+d"])
        self.assertEqual(split_specs(["ctrl+alt+d", "win+alt+space"]),
                         ["ctrl+alt+d", "win+alt+space"])
        self.assertEqual(split_specs("ctrl+alt+d, win+alt+space"),
                         ["ctrl+alt+d", "win+alt+space"])
        self.assertEqual(split_specs("ctrl+alt+d,ctrl+alt+d"), ["ctrl+alt+d"])
        self.assertEqual(combo_list(["ctrl+alt+d", "win+alt+space"]),
                         ["<ctrl>+<alt>+d", "<cmd>+<alt>+<space>"])
        with self.assertRaises(ValueError):
            split_specs(["", "  "])

    def test_shipped_config_avoids_the_claude_key(self):
        from ar_dictate import combo_list, load_config, split_specs

        cfg = load_config(self.CONFIG)
        specs = split_specs(cfg["hotkey"])
        self.assertNotIn("ctrl+alt+space", [s.lower() for s in specs],
                         "ctrl+alt+space is claimed by Claude Desktop")
        for combo in combo_list(cfg["hotkey"]):
            self.assertNotEqual(combo, "ctrl+alt+space")
        # the mode/quit keys still have to be usable too
        self.assertTrue(cfg["mode_key"] and cfg["quit_key"])

    def test_set_hotkey_round_trip_keeps_the_rest(self):
        import json
        import subprocess
        import tempfile

        from ar_dictate import combo_list, update_config_keys

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"hotkey": "ctrl+alt+space",
                                        "model": "../models/x", "mode": "msa"}),
                            encoding="utf-8")
            update_config_keys(path, {"hotkey": "ctrl+alt+j"})
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["hotkey"], "ctrl+alt+j")
            self.assertEqual(data["model"], "../models/x")  # untouched
            update_config_keys(path, {"hotkey": "ctrl+alt+j,win+alt+space"})
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["hotkey"], ["ctrl+alt+j", "win+alt+space"])
            self.assertEqual(combo_list(data["hotkey"]),
                             ["<ctrl>+<alt>+j", "<cmd>+<alt>+<space>"])

            # a typo must be refused before it reaches the app
            with self.assertRaises(ValueError):
                update_config_keys(path, {"hotkey": "  "})

            # and the same path through the real CLI
            out = subprocess.run(
                [sys.executable, str(self.ROOT / "app" / "ar_dictate.py"),
                 "--config", str(path), "--set-hotkey", "ctrl+alt+k"],
                capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["hotkey"],
                             "ctrl+alt+k")

    def test_no_tool_hardcodes_the_dictate_key(self):
        # by product name, not by row: the launchers were renamed to Keyboardless
        launcher = (self.ROOT / "keyboardless.cmd").read_text(encoding="utf-8")
        check = (self.ROOT / "keyboardless-check.cmd").read_text(encoding="utf-8")
        hook = (self.ROOT / "app" / "tests" / "hook_test.py").read_text(encoding="utf-8")
        # the launcher asks the app instead of repeating the combination
        self.assertIn("--print-hotkeys", launcher)
        self.assertNotIn("ctrl+alt+space", launcher.lower())
        # the capture test must follow config.json, not a literal default
        self.assertNotIn('default="ctrl+alt', hook.lower())
        self.assertNotIn("--combo", check.lower())
        self.assertIn("hook_test.py", check)
        # the installer's "next steps" text and the state probe ask the app too:
        # install_windows.ps1 printed ctrl+alt+space long after config.json moved
        # to ctrl+alt+d, which sends the user straight to a key that does nothing
        for name, rel in (("install_windows.ps1", ("app", "install_windows.ps1")),
                          ("work_device_state.ps1", ("app", "tests", "work_device_state.ps1"))):
            text = self.ROOT.joinpath(*rel).read_text(encoding="utf-8")
            self.assertIn("--print-hotkeys", text, name)
            self.assertIsNone(re.search(r"ctrl\+alt\+[a-z]", text, re.I),
                              f"{name} hardcodes a dictate combination")

class TestHotkeyClaim(unittest.TestCase):
    """vk_code / hotkey_claim -- the Windows answer to "who owns this key?"."""

    def test_vk_codes(self):
        import ar_dictate as ad
        cases = {"d": 0x44, "space": 0x20, "win": 0x5B, "cmd": 0x5B,
                 "f9": 0x78, "f12": 0x7B, "tab": 0x09, "ctrl": 0x11, "alt": 0x12}
        for name, expected in cases.items():
            self.assertEqual(ad.vk_code(name), expected, name)

    def test_vk_code_unknown(self):
        import ar_dictate as ad
        self.assertEqual(ad.vk_code("nonsense-key"), -1)

    def test_claim_is_n_a_off_windows(self):
        import os
        import ar_dictate as ad
        result = ad.hotkey_claim("ctrl+alt+d")
        if os.name == "nt":
            self.assertIn(result.split()[0], ("free", "TAKEN", "unknown"))
        else:
            self.assertEqual(result, "n/a")

    def test_stop_combo_comes_from_config(self):
        # the probe must never hardcode the combination again
        root = Path(__file__).resolve().parents[2]
        probe = (root / "app" / "tests" / "run_live_probe.ps1").read_text(encoding="utf-8")
        self.assertIn("config.json", probe)
        self.assertIn("Get-ComboKeys", probe)
        self.assertNotIn("$CTRL = 0x11", probe)


class TestVirtualKeyMatching(unittest.TestCase):
    """Letter shortcuts must be matched by virtual-key code, not by character.

    Measured on the user's machine (Arabic 101 layout): with ctrl+alt held the
    'd' key arrives as KeyCode(vk=68, char=None) -- pynput's character-based
    HotKey matching never fired, which looked exactly like "the shortcut does
    nothing". Only <space> worked, because space is a named key.
    """

    def test_parse_combo(self):
        from ar_dictate import parse_combo

        self.assertEqual(parse_combo("ctrl+alt+d"), (frozenset({"ctrl", "alt"}), "d"))
        self.assertEqual(parse_combo("Ctrl + Alt + D"), (frozenset({"ctrl", "alt"}), "d"))
        self.assertEqual(parse_combo("win+shift+f9"), (frozenset({"win", "shift"}), "f9"))
        self.assertEqual(parse_combo("cmd+f9"), (frozenset({"win"}), "f9"))
        # the pynput preview form must parse too, or the binder breaks on it
        self.assertEqual(parse_combo("<ctrl>+<alt>+d"), (frozenset({"ctrl", "alt"}), "d"))
        for bad in ("d", "ctrl+alt", "ctrl+alt+d+j"):
            with self.assertRaises(ValueError, msg=bad):
                parse_combo(bad)

    def test_matches_the_real_arabic_layout_event(self):
        from ar_dictate import combo_matches

        self.assertTrue(combo_matches("d", vk=68, char=None, name=None))
        self.assertTrue(combo_matches("space", vk=None, char=None, name="space"))
        self.assertTrue(combo_matches("f9", vk=0x78, char=None, name=None))
        self.assertTrue(combo_matches("q", vk=81, char="q", name=None))
        self.assertFalse(combo_matches("d", vk=70, char="h", name=None))
        self.assertFalse(combo_matches("j", vk=None, char=None, name="space"))

    def test_binder_does_not_go_back_to_character_matching(self):
        src = (Path(__file__).resolve().parents[2] / "app" / "ar_dictate.py").read_text(encoding="utf-8")
        self.assertNotIn("pk.GlobalHotKeys", src)
        self.assertIn("combo_matches", src)


if __name__ == "__main__":
    unittest.main()
