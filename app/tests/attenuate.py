"""Rescale an audio sample to a chosen peak level.

Used to reproduce a quiet microphone, and to prove that the app's auto-gain
stage fixes it:

    python attenuate.py samples/test_msa.wav 0.004 samples/quiet_0004.wav

With no arguments it writes one file per level into the temp directory, which
is how the "quiet audio is transcribed as silence" threshold was measured.
"""
import array
import sys
import tempfile
import wave
from pathlib import Path

DEFAULT_SRC = Path(__file__).resolve().parents[2] / "samples" / "test_msa.wav"
LEVELS = (0.5, 0.1, 0.03, 0.01, 0.003)


def read_mono16(path: Path) -> tuple[array.array, int]:
    with wave.open(str(path), "rb") as wf:
        if wf.getsampwidth() != 2:
            raise SystemExit(f"{path} must be 16-bit PCM")
        rate, channels = wf.getframerate(), wf.getnchannels()
        samples = array.array("h")
        samples.frombytes(wf.readframes(wf.getnframes()))
    if channels != 1:
        # downmix an interleaved stereo pair by keeping the left channel
        samples = array.array("h", samples[::channels])
    return samples, rate


def write_mono16(path: Path, samples: array.array, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())


def rescale(samples: array.array, target: float, peak: float) -> array.array:
    scale = target / peak
    return array.array("h", (max(-32768, min(32767, int(s * scale))) for s in samples))


def main(argv: list[str]) -> int:
    src = Path(argv[0]) if argv else DEFAULT_SRC
    samples, rate = read_mono16(src)
    peak = max(max(samples), -min(samples)) / 32768.0
    print(f"source: {rate}Hz 16-bit peak={peak:.4f} dur={len(samples) / rate:.1f}s")

    if len(argv) >= 3:
        target, out = float(argv[1]), Path(argv[2])
        write_mono16(out, rescale(samples, target, peak), rate)
        print(f"wrote {out} at peak {target}")
        return 0

    outdir = Path(tempfile.gettempdir())
    for level in LEVELS:
        out = outdir / f"att_{int(level * 1000):04d}.wav"
        write_mono16(out, rescale(samples, level, peak), rate)
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
