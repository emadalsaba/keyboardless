"""Logging must never kill the app -- even on a console that cannot print Arabic.

Real failure on a Windows PC: `python ar_dictate.py --wav ...` under Windows
PowerShell inherited code page cp1256, and the first char-count log line
("typed 103 chars -> ...") raised UnicodeEncodeError from inside
Dictation.log(), which propagated out of feed_wav() and killed the run before
any text was typed. The .cmd launcher sets `chcp 65001`, but a plain console
does not, and an Arabic/dialect transcript can hit the same wall at any time.
"""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

import ar_dictate  # noqa: E402


class TestLogSurvivesANonUtf8Console(unittest.TestCase):
    def _dictation(self, log_path: Path):
        # the constructor only stores the injector; cfg needs "mode" and "log"
        cfg = {"mode": "msa", "agc": False, "log": str(log_path)}
        return ar_dictate.Dictation(cfg, injector=None)

    def test_log_uses_a_replacement_console_but_keeps_the_utf8_file(self):
        with tempfile.TemporaryDirectory() as td:
            log_path = Path(td) / "dictate.log"
            d = self._dictation(log_path)
            real = sys.stdout
            # a console that can do Latin-1 only: Arabic and "->" cannot be encoded
            sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1256", errors="strict")
            try:
                d.log("typed 103 chars \u2192 'أعلنت وزارة' @ notepad")
            except UnicodeEncodeError as exc:  # pragma: no cover - the regression
                self.fail(f"log() raised through to the caller: {exc}")
            finally:
                sys.stdout = real
            text = log_path.read_text(encoding="utf-8")
            self.assertIn("103 chars", text)
            self.assertIn("أعلنت", text, "the UTF-8 log file lost the Arabic text")


if __name__ == "__main__":
    unittest.main()
