"""Probe: a pause must continue the text, never replace the previous sentence.

Replays `samples/test_two_segments.wav` -- a real utterance, 1.5 s of silence,
then a second utterance -- through the same pipeline the live microphone uses
(Vosk -> CommitEngine -> injector) and prints what would have reached the screen
plus how many characters were backspaced. Nothing is injected anywhere.

Expected: a comma right after the first utterance ("القادم،"), then the second
utterance, and no backspaces at the segment boundary.

    python tests/two_segment_replay.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from ar_dictate import Dictation, load_config  # noqa: E402
from vosk import Model, SetLogLevel  # noqa: E402


class ScreenInjector:
    """Keeps a screen buffer so backspaces are visible in the result."""

    def __init__(self):
        self.screen = ""
        self.backs = 0

    def type_text(self, t):
        self.screen += t

    def press_backspace(self, c=1):
        self.backs += c
        self.screen = self.screen[: max(0, len(self.screen) - c)]

    def target_info(self):
        return "screen"

    def close(self):
        pass


def main() -> int:
    cfg = load_config(ROOT / "app" / "config.json")
    cfg["log_injection"] = False
    SetLogLevel(-1)
    d = Dictation(cfg, ScreenInjector())
    model_dir = Path(cfg["model"])
    if not model_dir.is_absolute():
        # the app resolves relative model paths against the config's folder
        model_dir = (ROOT / "app" / model_dir).resolve()
    d.model = Model(str(model_dir))
    d.feed_wav(ROOT / "samples" / "test_two_segments.wav")
    sep = cfg.get("auto_sep", "،")
    screen = d.injector.screen.strip()
    print(f"BACKSPACES = {d.injector.backs}")
    print(f"SCREEN = {screen}")
    # both utterances must be on screen, separated by the pause glyph
    before, _, after = screen.partition(sep)
    ok = bool(before.strip()) and len(after.split()) >= 3
    print("VERDICT:", "pause continued the line" if ok else "SEGMENT WAS REPLACED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
