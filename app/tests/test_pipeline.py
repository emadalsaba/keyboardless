"""Tests for the streaming commit engine -- the part that decides what the user
sees typed *while still speaking*. Run:  python -m unittest discover -s tests -v

The expected values here are the specification of the typing behaviour:
a word reaches the screen only once two consecutive hypotheses agree on it and
it is no longer the trailing token of the partial result.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from postprocess import postprocess, strip_diacritics  # noqa: E402
from streaming import CommitEngine, common_prefix_len  # noqa: E402


class TestCommonPrefix(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(common_prefix_len(["a", "b", "c"], ["a", "b", "d"]), 2)
        self.assertEqual(common_prefix_len([], ["a"]), 0)
        self.assertEqual(common_prefix_len(["a"], ["a"]), 1)
        self.assertEqual(common_prefix_len(["a", "b"], ["b"]), 0)


class TestCommitEngine(unittest.TestCase):
    def setUp(self):
        self.eng = CommitEngine(min_agree=2, hold_back=1)

    def test_nothing_typed_on_first_partial(self):
        edit, pending = self.eng.update("أعلنت")
        self.assertEqual(self.eng.committed, [])
        self.assertTrue(edit.is_empty())
        self.assertEqual(pending, ["أعلنت"])

    def test_word_is_typed_once_it_survives_a_second_hypothesis(self):
        self.eng.update("أعلنت")
        edit, pending = self.eng.update("أعلنت وزارة")
        # "أعلنت" has now been seen twice, the trailing "وزارة" has not
        self.assertEqual(edit.insert_text, "أعلنت")
        self.assertEqual(self.eng.committed, ["أعلنت"])
        self.assertEqual(pending, ["وزارة"])

    def test_trailing_token_is_held_back_even_when_it_repeats(self):
        self.eng.update("أعلنت وزارة")
        self.eng.update("أعلنت وزارة")
        self.assertEqual(self.eng.committed, ["أعلنت"],
                         "the trailing token must not commit while it is trailing")

    def test_typing_is_incremental_and_never_repeats(self):
        typed: list[str] = []
        for hyp in ("أعلنت", "أعلنت وزارة", "أعلنت وزارة الموارد",
                    "أعلنت وزارة الموارد البشرية", "أعلنت وزارة الموارد البشرية عن",
                    "أعلنت وزارة الموارد البشرية عن برنامج"):
            edit, _ = self.eng.update(hyp)
            typed.extend(edit.insert_text.split())
        self.assertEqual(self.eng.committed, ["أعلنت", "وزارة", "الموارد", "البشرية"])
        self.assertEqual(typed, self.eng.committed)
        self.assertEqual(typed.count("وزارة"), 1)

    def test_revision_of_typed_text_emits_backspaces(self):
        for hyp in ("برنامج", "برنامج دعم", "برنامج دعم جديد",
                    "برنامج دعم جديد آخر"):
            self.eng.update(hyp)
        self.assertEqual(self.eng.committed, ["برنامج", "دعم"])
        edit, _ = self.eng.update("برنامج ذهب جديد")
        self.assertEqual(edit.delete_words, 1, "the wrong word is on screen and must go")
        self.assertEqual(edit.insert_text, "")
        edit, _ = self.eng.update("برنامج ذهب جديد")
        self.assertEqual(edit.insert_text, "ذهب")

    def test_final_flush_commits_the_held_back_tail(self):
        self.eng.update("رصيد الإجازات")
        edit, pending = self.eng.update("رصيد الإجازات المتبقي", final=True)
        self.assertEqual(self.eng.committed, ["رصيد", "الإجازات", "المتبقي"])
        self.assertEqual(pending, [])
        self.assertIn("المتبقي", edit.insert_text)

    def test_final_rewrite_deletes_what_was_already_typed(self):
        for hyp in ("الجو حار", "الجو حار اليوم", "الجو حار اليوم جدا"):
            self.eng.update(hyp)
        self.assertEqual(self.eng.committed, ["الجو", "حار"])
        edit, _ = self.eng.update("الجد حار اليوم", final=True)
        self.assertEqual(edit.delete_words, 2)
        self.assertTrue(edit.insert_text.startswith("الجد"))

    def test_reset_clears_state(self):
        self.eng.update("كلمة شيء")
        self.eng.reset()
        self.assertEqual((self.eng.committed, self.eng.injected, self.eng.pending),
                         ([], [], []))
        self.assertTrue(self.eng.update("كلمة شيء")[0].is_empty())

    def test_injected_always_tracks_committed(self):
        """Whatever is on screen equals the committed prefix at every step."""
        hyps = [
            "أبغى أطلع إجازة", "أبغى أطلع إجازة الأسبوع",
            "أبغى أطلع إجازة الأسبوع الجاي", "أبغى أطلع إجازة الأسبوع الجاي وودي",
            "أبغى أطلع إجازة الأسبوع الجاي وودي أعرف",
            "أبغى أطلع إجازة الأسبوع الجاي أبي أعرف",
        ]
        for hyp in hyps:
            self.eng.update(hyp)
            self.assertEqual(self.eng.injected, self.eng.committed)
            self.assertEqual(self.eng.committed,
                             hyps[-1].split()[:len(self.eng.committed)])


class TestPostprocess(unittest.TestCase):
    def test_punctuation_glyph_hugs_previous_word(self):
        out = postprocess("تم إرسال الطلب فاصلة وننتظر الرد نقطة",
                          mode="msa", auto_period=False)
        self.assertEqual(out, "تم إرسال الطلب، وننتظر الرد.")

    def test_question_mark_and_newline(self):
        out = postprocess("هل تم الاعتماد علامة استفهام سطر جديد شكرا",
                          mode="msa", auto_period=False)
        self.assertIn("الاعتماد؟", out)
        self.assertIn("\n", out)

    def test_longest_command_wins(self):
        out = postprocess("الاجتماع فاصلة منقوطة الخميس", mode="msa", auto_period=False)
        self.assertIn("الاجتماع؛", out)

    def test_auto_period_only_when_asked(self):
        self.assertTrue(postprocess("نص بلا ترقيم", mode="msa").endswith("."))
        self.assertFalse(postprocess("نص بلا ترقيم", mode="msa", auto_period=False).endswith("."))
        self.assertTrue(postprocess("نص بلا ترقيم.", mode="msa").endswith("."))
        self.assertEqual(postprocess("انتهى؟", mode="msa"), "انتهى؟")

    def test_dialect_repairs_are_off_in_msa_mode(self):
        raw = "الجي وودي أعرف كم باقي عشرين أقدم الطلبة"
        self.assertEqual(postprocess(raw, mode="msa", auto_period=False), raw)

    def test_dialect_repairs_fix_the_known_offenders(self):
        fixed = postprocess("الجي وودي أعرف كم باقي عشرين أقدم الطلبة",
                            mode="dialect", auto_period=False)
        self.assertIn("الجاي", fixed)
        self.assertIn("عشان", fixed)
        self.assertIn("الطلب", fixed)
        self.assertNotIn("عشرين", fixed)

    def test_extra_fixes_are_merged_in(self):
        fixed = postprocess("مرحبا بكم في نماء البلاد", mode="dialect",
                            auto_period=False, extra_fixes={"نماء البلاد": "إنماء البلاد"})
        self.assertEqual(fixed, "مرحبا بكم في إنماء البلاد")

    def test_diacritics_and_tatweel_removed(self):
        self.assertEqual(strip_diacritics("مُحَمَّد"), "محمد")
        self.assertEqual(strip_diacritics("مـــحمد"), "محمد")

    def test_empty_input(self):
        self.assertEqual(postprocess("", mode="dialect"), "")
        self.assertEqual(postprocess("   ", mode="msa"), "")
        self.assertEqual(postprocess("نقطة", mode="msa", auto_period=False), ".")


class TestInjectionLayer(unittest.TestCase):
    """The layer that turns commit edits into keystrokes. A fake injector stands
    in for SendInput so the accounting (separators, backspace counts) is testable
    without a desktop session."""

    class FakeInjector:
        """Keeps a *screen buffer*, not just a keystroke log: what the user sees
        is type_text minus whatever the backspaces removed."""

        def __init__(self):
            self.screen = ""
            self.typed: list[str] = []
            self.backs = 0

        def type_text(self, text):
            self.typed.append(text)
            self.screen += text

        def press_backspace(self, count=1):
            self.backs += count
            self.screen = self.screen[:-count]

        def close(self):
            pass

    def setUp(self):
        from ar_dictate import Dictation, load_config
        from pathlib import Path

        self.cfg = load_config(Path(__file__).resolve().parent.parent / "config.json")
        self.d = Dictation(self.cfg, self.FakeInjector())

    def test_words_do_not_glue_together(self):
        self.cfg["space_before"] = False
        for hyp in ("أعلنت", "أعلنت وزارة", "أعلنت وزارة الموارد",
                    "أعلنت وزارة الموارد البشرية"):
            self.d.handle_hypothesis(hyp)
        self.assertEqual(self.d.injector.screen, "أعلنت وزارة ")

    def test_no_leading_space_when_configured_off(self):
        self.cfg["space_before"] = False
        self.d.handle_hypothesis("كلمة")
        self.d.handle_hypothesis("كلمة أخرى")
        self.assertFalse(self.d.injector.screen.startswith(" "))

    def test_space_before_inserts_one_separator(self):
        self.cfg["space_before"] = True
        self.d.handle_hypothesis("كلمة")
        self.d.handle_hypothesis("كلمة أخرى")
        self.assertTrue(self.d.injector.screen.startswith(" "))

    def test_rewind_backspaces_exactly_what_was_typed(self):
        for hyp in ("برنامج", "برنامج دعم", "برنامج دعم جديد",
                    "برنامج دعم جديد آخر", "برنامج ذهب جديد"):
            self.d.handle_hypothesis(hyp)
        # "دعم" was typed (6 chars + separator), so it must be removed with 7
        # backspaces -- no more, no less.
        self.assertEqual(self.d.injector.backs, len("دعم") + 1)

    def test_final_hypothesis_gets_the_full_stop(self):
        self.d.handle_hypothesis("أعلنت وزارة الموارد البشرية عن إطلاق برنامج دعم جديد",
                                 final=True)
        self.assertTrue(self.d.injector.screen.strip().endswith("."))

    def test_voice_punctuation_reaches_the_injector(self):
        for hyp in ("تم إرسال الطلب فاصلة",
                    "تم إرسال الطلب فاصلة وننتظر الرد",
                    "تم إرسال الطلب فاصلة وننتظر الرد غدا",
                    "تم إرسال الطلب فاصلة وننتظر الرد غدا إن شاء الله"):
            self.d.handle_hypothesis(hyp)
        typed = self.d.injector.screen
        # the spoken word "فاصلة" must land as a comma glued to "الطلب",
        # even though it is committed in a later keystroke batch
        self.assertIn("الطلب،", typed)
        self.assertNotIn("الطلب ،", typed)
        self.assertNotIn(" " * 2, typed)

    def test_mode_switch_changes_postprocessing(self):
        self.d.switch_mode()
        self.assertEqual(self.d.mode, "dialect")
        for hyp in ("الجي", "الجي حار"):
            self.d.handle_hypothesis(hyp)
        self.assertIn("الجاي", self.d.injector.screen)
        self.d.switch_mode()
        self.assertEqual(self.d.mode, "msa")


if __name__ == "__main__":
    unittest.main(verbosity=2)
