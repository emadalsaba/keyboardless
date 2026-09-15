"""Cross-module contract: a half-deployed tree must fail loudly, not at runtime.

This has really happened (2026-09-15): ``ar_dictate.py`` grew ``closing=`` for
``postprocess()`` and ``CommitEngine.seal_segment()``, but the machine still had
the previous ``postprocess.py``/``streaming.py``. Nothing complained until the
first *committed word*, where the app died with a TypeError -- which the user
sees as "the program stopped working".

The lesson is a test: the engine's modules are deployed as a set, and every
call the engine makes across a module boundary is checked here.
"""

import inspect
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))

import ar_dictate  # noqa: E402
import inject_win  # noqa: E402
import postprocess  # noqa: E402
import streaming  # noqa: E402


class TestEngineContract(unittest.TestCase):
    def test_postprocess_accepts_the_segment_closing_glyph(self):
        sig = inspect.signature(postprocess.postprocess)
        self.assertIn("closing", sig.parameters,
                      "postprocess.py is older than ar_dictate.py: a committed "
                      "word would raise TypeError")
        self.assertIn("auto_period", sig.parameters)

    def test_commit_engine_can_seal_a_segment(self):
        self.assertTrue(hasattr(streaming.CommitEngine, "seal_segment"),
                        "streaming.py is older than ar_dictate.py: a pause would "
                        "erase the sentence that came before it")

    def test_commit_engine_update_takes_final(self):
        sig = inspect.signature(streaming.CommitEngine.update)
        self.assertIn("final", sig.parameters)

    def test_injector_interface_is_complete(self):
        for name in ("type_text", "press_backspace", "press_enter", "target_info"):
            self.assertTrue(hasattr(inject_win.BaseInjector, name), name)
        self.assertTrue(callable(getattr(inject_win, "make_injector", None)),
                        "inject_win.make_injector is used by the window and the CLI")

    def test_engine_only_calls_what_exists(self):
        """The names ar_dictate imports from its neighbours must all be there."""
        source = (APP / "ar_dictate.py").read_text(encoding="utf-8")
        for needed in ("from postprocess import", "from streaming import",
                       "from inject_win import"):
            self.assertIn(needed, source)
        self.assertTrue(hasattr(postprocess, "postprocess"))
        self.assertTrue(hasattr(postprocess, "HUG_GLYPHS"))
        self.assertTrue(hasattr(streaming, "CommitEngine"))

    def test_dictation_events_the_window_depends_on(self):
        """The window subscribes to these kinds; keep them documented in code."""
        source = (APP / "gui.py").read_text(encoding="utf-8")
        for kind in ("state", "typed", "partial", "meter", "log", "error", "listening"):
            self.assertIn(f'"{kind}"', source, f"the window handles '{kind}'")
        engine = (APP / "ar_dictate.py").read_text(encoding="utf-8")
        for kind in ('emit("state"', 'emit("typed"', 'emit("partial"', 'emit("meter"',
                     'emit("log"', 'emit("listening"'):
            self.assertIn(kind, engine, f"the engine emits {kind}")


if __name__ == "__main__":
    unittest.main()
