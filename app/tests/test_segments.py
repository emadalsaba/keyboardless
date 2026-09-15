"""Pausing must continue the text, never replace it.

The bug this file pins down (reported by the user on his own PC, 2026-09):
say a full sentence, pause, say the next one -- the first sentence was erased
and replaced by the second.

Cause: Vosk reports a pause by *closing the utterance*, so the next partial it
emits contains only the new words. The commit engine compared those words with
the words of the previous segment, found no common prefix, and emitted
backspaces for everything it had already typed. Two things were missing:
the endpoint was not treated as the end of a segment, and nothing sealed the
engine afterwards (see CommitEngine.seal_segment).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from streaming import CommitEngine  # noqa: E402
from postprocess import postprocess  # noqa: E402
import ar_dictate  # noqa: E402

SEG_A = "أعلنت وزارة الموارد البشرية"
SEG_B = "نصاب جديد للمنشآت"


class FakeInjector:
    """Screen buffer + keystroke log, like the one in test_pipeline."""

    def __init__(self):
        self.screen = ""
        self.backs = 0

    def type_text(self, text):
        self.screen += text

    def press_backspace(self, count=1):
        self.backs += count
        self.screen = self.screen[:max(0, len(self.screen) - count)]

    def close(self):
        pass


class TestPauseDoesNotErase(unittest.TestCase):
    def test_engine_appends_after_a_sealed_segment(self):
        eng = CommitEngine(min_agree=2, hold_back=1)
        eng.update(SEG_A)
        eng.update(SEG_A, final=True)
        self.assertEqual(eng.committed, SEG_A.split())
        eng.seal_segment()
        edit, _ = eng.update(SEG_B)
        self.assertEqual(edit.delete_words, 0,
                         "the previous sentence must not be backspaced away")
        # nothing is committed from a single hypothesis (hold_back), but whatever
        # gets committed later must be the *new* words
        eng.update(SEG_B)
        eng.update(SEG_B, final=True)
        self.assertEqual(eng.committed, SEG_B.split())

    def test_without_sealing_the_bug_would_come_back(self):
        """The old behaviour, kept as a witness: no seal -> delete everything."""
        eng = CommitEngine(min_agree=2, hold_back=1)
        eng.update(SEG_A, final=True)
        edit, _ = eng.update(SEG_B)
        self.assertEqual(edit.delete_words, len(SEG_A.split()))

    def test_empty_final_does_not_clear_the_line(self):
        eng = CommitEngine(min_agree=2, hold_back=1)
        eng.update(SEG_A, final=True)
        eng.update("", final=True)          # Vosk endpointe on noise
        self.assertEqual(eng.committed, SEG_A.split())
        self.assertEqual(eng.update("")[0].delete_words, 0)


class TestTwoSegmentsThroughTheApp(unittest.TestCase):
    """The whole path: hypotheses -> commit -> keystrokes in the target window."""

    def setUp(self):
        cfg = ar_dictate.load_config(Path(__file__).resolve().parent.parent / "config.json")
        cfg["space_before"] = False
        cfg["log_injection"] = False
        self.d = ar_dictate.Dictation(cfg, FakeInjector())

    def _segment(self, text):
        """What the recognizer does: partials while speaking, then the endpoint."""
        words = text.split()
        for i in range(1, len(words) + 1):
            self.d.handle_hypothesis(" ".join(words[:i]))
        self.d.handle_hypothesis(text, final=True, closing=self.d.cfg.get("auto_sep", "،"))

    def test_second_sentence_is_appended_after_a_comma(self):
        self._segment(SEG_A)
        self._segment(SEG_B)
        screen = self.d.injector.screen
        self.assertIn(SEG_A.split()[0], screen, "the first sentence was erased")
        self.assertIn("البشرية،", screen, "the pause must close the first sentence")
        self.assertIn(SEG_B.split()[-1], screen)
        self.assertEqual(self.d.injector.backs, 0, "a pause must not backspace anything")
        self.assertLess(screen.index("البشرية"), screen.index("نصاب"),
                        "the new sentence belongs after the old one")

    def test_stop_ends_with_a_full_stop_not_a_comma(self):
        self._segment(SEG_A)
        self.d.handle_hypothesis(SEG_B, final=True, closing=".")
        self.assertTrue(self.d.injector.screen.strip().endswith("."))

    def test_spoken_punctuation_is_not_doubled(self):
        self.d.handle_hypothesis("انتهى الكلام نقطة", final=True, closing="،")
        self.assertIn("الكلام.", self.d.injector.screen)
        self.assertNotIn("الكلام.،", self.d.injector.screen)

    def test_closing_glyph_hugs_the_word_when_nothing_new_was_inserted(self):
        # commit the words, then close the segment with the same text: the edit
        # is empty, yet the pause still has to leave its mark
        self.d.handle_hypothesis("كلمة")
        self.d.handle_hypothesis("كلمة", final=True, closing="،")
        self.assertNotIn(" ،", self.d.injector.screen)


class TestClosingSeparator(unittest.TestCase):
    def test_closing_is_added_only_when_nothing_punctuates_yet(self):
        self.assertTrue(postprocess("نص", mode="msa", closing="،").endswith("نص،"))
        self.assertEqual(postprocess("نص.", mode="msa", closing="،"), "نص.")

    def test_closing_wins_over_auto_period(self):
        self.assertTrue(postprocess("نص", mode="msa", closing="،", auto_period=True).endswith("،"))

    def test_no_closing_leaves_auto_period_alone(self):
        self.assertTrue(postprocess("نص", mode="msa", auto_period=True).endswith("."))
        self.assertFalse(postprocess("نص", mode="msa", auto_period=False).endswith("."))


class TestLivePathWiring(unittest.TestCase):
    """The bug lived in the *call site*, so guard the wiring, not just the engine.

    Both recognizer loops (live microphone and the offline replay) must hand
    Vosk's endpoint to handle_hypothesis as a closed segment with the configured
    separator. Missing either one silently brings the erase back, and the engine
    tests would stay green while the app eats sentences.
    """

    SRC = (APP / "ar_dictate.py").read_text(encoding="utf-8")

    def test_both_loops_close_the_segment_on_an_endpoint(self):
        self.assertEqual(self.SRC.count('closing=self.cfg.get("auto_sep", "،")'), 2,
                         "feed_mic and feed_wav must both treat the endpoint as a pause")
        self.assertEqual(self.SRC.count("rec.AcceptWaveform(data)"), 2)
        self.assertEqual(self.SRC.count("final=bool(text.strip())"), 2)

    def test_stop_flushes_with_a_full_stop(self):
        self.assertIn('closing="." if self.cfg.get("auto_period", True) else ""', self.SRC)


if __name__ == "__main__":
    unittest.main()
