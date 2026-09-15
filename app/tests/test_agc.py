"""Quiet microphones: the level fix, and proof that it fixes the real symptom.

A known-good Arabic sample is rescaled to the level the work laptop's built-in
array actually produces (peak ~0.004). Without the gain stage the recogniser
returns nothing at all -- which the user sees as "the hotkey works but no text
appears". With it, the same recording transcribes.
"""
import array
import os
import re
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))

from ar_dictate import AutoGain, audio_peak  # noqa: E402

MODEL = APP.parent / "models" / "vosk-model-small-ar-0.3"
SAMPLE = APP.parent / "samples" / "test_msa.wav"

# every log entry starts with a timestamp; the injector writes bare text
LOG_LINE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[^\n]*")


def block_at(peak: float, samples: int = 1600) -> bytes:
    """A 16-bit mono block whose samples reach ``peak`` (full scale = 1.0)."""
    value = int(peak * 32768)
    return array.array("h", [value, -value] * (samples // 2)).tobytes()


def arabic_text(stdout: str) -> str:
    """Only the text that actually reached the field.

    Log lines carry a timestamp and the injector writes bare text, sometimes
    glued to the front of the next log line -- so dropping the timestamped part
    of every line leaves exactly what was typed.
    """
    body = LOG_LINE.sub("", stdout).replace("\b", "")
    kept = []
    for line in body.splitlines():
        stripped = line.replace("\r", "").strip()
        if stripped and all("\u0600" <= c <= "\u06ff" or c in " \t.،؛؟!…" for c in stripped):
            kept.append(stripped)
    return " ".join(kept)


class TestAutoGain(unittest.TestCase):
    def test_quiet_input_is_lifted_towards_the_target(self):
        agc = AutoGain(target=0.3, max_gain=50)
        for _ in range(20):
            out = agc.apply(block_at(0.01))
        self.assertGreater(audio_peak(out), 0.1, "quiet speech must be amplified")
        self.assertLess(audio_peak(out), 0.99, "amplified audio must not be clipping")

    def test_loud_input_is_returned_untouched(self):
        agc = AutoGain()
        data = block_at(0.8)
        self.assertIs(agc.apply(data), data)
        self.assertEqual(agc.gain, 1.0)

    def test_silence_is_not_amplified_into_noise(self):
        agc = AutoGain()
        data = b"\x00" * 3200
        self.assertIs(agc.apply(data), data)
        self.assertEqual(agc.gain, 1.0)

    def test_gain_never_exceeds_the_cap(self):
        agc = AutoGain(target=0.3, max_gain=8)
        for _ in range(60):
            agc.apply(block_at(0.001))
        self.assertLessEqual(agc.gain, 8.0)

    def test_samples_stay_in_range(self):
        agc = AutoGain(target=0.3, max_gain=50)
        out = b""
        for _ in range(20):
            out = agc.apply(block_at(0.02))
        samples = array.array("h")
        samples.frombytes(out)
        self.assertLessEqual(max(samples), 32767)
        self.assertGreaterEqual(min(samples), -32768)

    def test_block_length_is_preserved(self):
        agc = AutoGain()
        data = block_at(0.005)
        self.assertEqual(len(agc.apply(data)), len(data))

    def test_odd_length_input_does_not_raise(self):
        self.assertIsInstance(AutoGain().apply(b"\x01\x02\x03"), bytes)


class TestGainStageOnTheLivePath(unittest.TestCase):
    """The hotkey path and the replay path must apply the same gain stage."""

    def make_dictation(self, agc_on: bool):
        sys.path.insert(0, str(APP))
        from inject_win import StdoutInjector
        from ar_dictate import DEFAULT_CONFIG, Dictation, load_config

        cfg = load_config(DEFAULT_CONFIG)
        cfg["agc"] = agc_on
        return Dictation(cfg, StdoutInjector())

    def test_quiet_blocks_are_amplified(self):
        d = self.make_dictation(True)
        quiet = block_at(0.008)
        out = quiet
        for _ in range(20):
            out = d._gain_stage(quiet)
        self.assertGreater(audio_peak(out), audio_peak(quiet) * 5)

    def test_gain_can_be_switched_off(self):
        d = self.make_dictation(False)
        quiet = block_at(0.008)
        self.assertIs(d._gain_stage(quiet), quiet)


@unittest.skipUnless(MODEL.exists() and SAMPLE.exists(), "model or sample missing")
class TestQuietRecordingEndToEnd(unittest.TestCase):
    """The exact symptom: quiet mic in, nothing typed out."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        quiet = Path(cls._tmp.name) / "quiet_0004.wav"
        with wave.open(str(SAMPLE), "rb") as wf:
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
        samples = array.array("h")
        samples.frombytes(frames)
        peak = max(max(samples), -min(samples)) / 32768.0
        scale = 0.004 / peak
        quiet_samples = array.array("h", (int(s * scale) for s in samples))
        with wave.open(str(quiet), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(quiet_samples.tobytes())
        cls.quiet = quiet

    def dictate(self, agc: str) -> str:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        proc = subprocess.run(
            [sys.executable, str(APP / "ar_dictate.py"), "--wav", str(self.quiet),
             "--injector", "stdout", "--agc", agc],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, cwd=str(APP.parent), timeout=240)
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        return arabic_text(proc.stdout)

    def test_without_gain_the_recording_produces_no_text(self):
        self.assertEqual(self.dictate("off"), "",
                         "a too-quiet recording used to produce nothing at all")

    def test_with_gain_the_same_recording_is_transcribed(self):
        typed = self.dictate("on")
        self.assertGreater(len(typed), 20, f"nothing recognised: {typed!r}")
        self.assertIn("\u0627\u0644\u0623\u0648\u0644", typed,
                      "expected the words of the sample to come through")


if __name__ == "__main__":
    unittest.main(verbosity=2)
