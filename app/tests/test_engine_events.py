"""The engine side of the desktop window: events, settings, pause separator.

Everything the settings window touches lives here, so the window itself stays a
thin layer over a tested engine -- a GUI bug must never be able to mean "the
dictation silently stopped working".
"""

import copy
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))

import ar_dictate  # noqa: E402
from ar_dictate import Dictation, DEFAULT_CONFIG, load_config  # noqa: E402
import inject_win  # noqa: E402
from inject_win import BaseInjector  # noqa: E402


class RecordingInjector(BaseInjector):
    """Keeps every call, so a test can say exactly what reached the field."""

    name = "recording"

    def __init__(self):
        self.typed: list[str] = []
        self.backspaces: list[int] = []
        self.enters = 0

    def type_text(self, text: str) -> None:
        self.typed.append(text)

    def press_backspace(self, count: int = 1) -> None:
        self.backspaces.append(count)

    def press_enter(self) -> None:
        self.enters += 1

    @property
    def text(self) -> str:
        return "".join(self.typed)


def make_dictation(**overrides) -> tuple[Dictation, RecordingInjector, list[tuple]]:
    """A Dictation wired to a recording injector and a captured event stream."""
    cfg = copy.deepcopy(load_config(DEFAULT_CONFIG))
    cfg.update({"log": str(Path(tempfile.mkdtemp()) / "test.log"), "verbose": False})
    cfg.update(overrides)
    injector = RecordingInjector()
    d = Dictation(cfg, injector)
    events: list[tuple] = []
    d.on_event = lambda kind, payload: events.append((kind, payload))
    return d, injector, events


def kinds(events) -> list[str]:
    return [kind for kind, _ in events]


def dictate(d: Dictation, text: str, times: int = 2) -> None:
    """Feed one hypothesis until it is committed (LocalAgreement-2 needs two)."""
    for _ in range(times):
        d.handle_hypothesis(text)


class TestEventStream(unittest.TestCase):
    """The window follows the engine; stdout is not an interface."""

    def test_start_and_stop_report_state(self):
        d, _, events = make_dictation()
        d.active = True  # start() is exercised through the real keys elsewhere
        d.emit("state", active=True, mode=d.mode)
        d.active = False
        d.emit("state", active=False, mode=d.mode)
        payloads = [p for k, p in events if k == "state"]
        self.assertEqual([p["active"] for p in payloads], [True, False])

    def test_typed_text_is_reported_for_the_transcript_box(self):
        d, injector, events = make_dictation()
        d.active = True
        dictate(d, "مرحبا بك")
        self.assertIn("typed", kinds(events))
        self.assertIn("مرحبا", "".join(p["text"] for k, p in events if k == "typed"))

    def test_log_lines_reach_the_window(self):
        d, _, events = make_dictation()
        events.clear()
        d.log("hello")
        self.assertEqual(kinds(events), ["log"])
        self.assertIn("hello", events[0][1]["line"])

    def test_a_broken_ui_cannot_kill_dictation(self):
        d, injector, _ = make_dictation()

        def explode(kind, payload):
            raise RuntimeError("the window died")

        d.on_event = explode
        d.log("still alive")          # must not raise
        d.emit("whatever", x=1)       # must not raise
        self.assertTrue(d.log_path.exists())


class TestPauseSeparator(unittest.TestCase):
    """'Separator between sentences after N seconds' -- the user's setting."""

    def test_separator_is_written_once_after_the_configured_silence(self):
        d, injector, _ = make_dictation(pause_seconds=1.0, pause_sep="\n")
        d.active = True
        d.total_injected_chars = 5
        d._last_voice_ts = time.time() - 5
        d._check_pause()
        d._check_pause()
        self.assertEqual(injector.typed, ["\n"], "one separator per pause, not per tick")
        self.assertEqual(injector.enters, 0)  # the injector decides how to render it

    def test_no_separator_before_the_time_is_up(self):
        d, injector, _ = make_dictation(pause_seconds=2.0, pause_sep=".")
        d.active = True
        d.total_injected_chars = 5
        d._last_voice_ts = time.time()
        d._check_pause()
        self.assertEqual(injector.typed, [])

    def test_no_separator_while_idle_or_with_nothing_typed(self):
        d, injector, _ = make_dictation(pause_seconds=0.5, pause_sep=".")
        d.active = False
        d.total_injected_chars = 5
        d._last_voice_ts = time.time() - 5
        d._check_pause()
        d.active = True
        d.total_injected_chars = 0
        d._check_pause()
        self.assertEqual(injector.typed, [])

    def test_a_configured_zero_turns_the_feature_off(self):
        d, injector, _ = make_dictation(pause_seconds=0, pause_sep=".")
        d.active = True
        d.total_injected_chars = 5
        d._last_voice_ts = time.time() - 60
        d._check_pause()
        self.assertEqual(injector.typed, [])

    def test_speaking_again_re_arms_the_separator(self):
        d, injector, _ = make_dictation(pause_seconds=1.0, pause_sep=".")
        d.active = True
        d.total_injected_chars = 5
        d._last_voice_ts = time.time() - 5
        d._check_pause()
        self.assertTrue(d._pause_written)
        # a word reaches the screen: the pause clock restarts
        dictate(d, "كلمة جديدة")
        self.assertFalse(d._pause_written)
        d._last_voice_ts = time.time() - 5
        d._check_pause()
        self.assertEqual(injector.text.count("."), 2, "second pause writes a second separator")

    def test_a_broken_device_falls_back_to_the_system_default(self):
        """A chosen microphone that cannot open must not leave the app silent."""
        d, _, events = make_dictation(device=7)
        self.assertTrue(d._device_fallback())
        self.assertIsNone(d.cfg["device"])
        self.assertIn("device-fallback", kinds(events))
        self.assertFalse(d._device_fallback(), "nothing to fall back from any more")

    def test_separator_is_counted_for_later_rewinds(self):
        d, injector, _ = make_dictation(pause_seconds=0.5, pause_sep=".")
        d.active = True
        d.total_injected_chars = 10
        d._word_costs = [5]
        d._last_voice_ts = time.time() - 5
        d._check_pause()
        self.assertEqual(d.total_injected_chars, 11)
        self.assertEqual(d._word_costs[-1], 6, "the glyph is removable with its word")


class TestLiveSettings(unittest.TestCase):
    """The window's controls must take effect without a restart."""

    def test_device_change_reopens_the_microphone(self):
        d, _, _ = make_dictation()
        d._reload.clear()
        self.assertEqual(d.apply_settings({"device": 3}), [])
        self.assertEqual(d.cfg["device"], 3)
        self.assertTrue(d._reload.is_set(), "the audio thread must reopen the device")

    def test_same_device_does_not_disturb_the_stream(self):
        d, _, _ = make_dictation(device=2)
        d._reload.clear()
        d.apply_settings({"device": 2})
        self.assertFalse(d._reload.is_set())

    def test_sensitivity_and_auto_gain_are_live(self):
        d, _, _ = make_dictation()
        d.apply_settings({"agc_target": 0.15})
        self.assertAlmostEqual(d.agc.target, 0.15)
        d.apply_settings({"agc": False})
        self.assertIsNone(d.agc)
        d.apply_settings({"agc": True})
        self.assertIsNotNone(d.agc)
        self.assertAlmostEqual(d.agc.target, 0.15, msg="the level survives a toggle")

    def test_model_change_is_deferred_to_the_window(self):
        d, _, _ = make_dictation()
        self.assertEqual(d.apply_settings({"model": "C:/models/other"}), ["model"])

    def test_mode_is_set_explicitly(self):
        d, _, events = make_dictation(mode="msa")
        d.set_mode("dialect")
        self.assertEqual(d.mode, "dialect")
        self.assertIn("state", kinds(events))
        d.set_mode("dialect")          # no-op, no duplicate log
        self.assertEqual(len([k for k in kinds(events) if k == "state"]), 1)


@unittest.skipUnless(inject_win.IS_WINDOWS, "Windows key injection only")
class TestNewlineSeparatorInjection(unittest.TestCase):
    """A newline separator must be an Enter key, not a U+000A character.

    Chrome and most editors ignore a raw line-feed inside injected Unicode text,
    so the configured "new line" separator would silently do nothing.
    """

    def test_newline_becomes_enter_and_the_rest_is_typed(self):
        injector = inject_win.SendInputInjector()
        seen: list[tuple] = []
        injector.press_enter = lambda: seen.append(("enter",))
        injector.type_text = lambda text: seen.append(("type", text))
        real_send = inject_win._send
        inject_win._send = lambda events: seen.append(("send", len(events)))
        try:
            inject_win.SendInputInjector.type_text(injector, "أول\nثاني")
        finally:
            inject_win._send = real_send
        # the part before the newline goes out as its own call, then Enter, then
        # the remainder is typed by the same call (one _send for 4 characters)
        self.assertEqual([s[0] for s in seen], ["type", "enter", "send"])
        self.assertEqual(seen[0][1], "أول")
        self.assertEqual(seen[2][1], 8, "4 arabic chars = press+release each")
