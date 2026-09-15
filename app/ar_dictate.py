#!/usr/bin/env python3
"""Keyboardless (بدون كيبورد) -- محرّك الإملاء الصوتي العربي بلا إنترنت.

Press a hotkey, talk, and the words appear in whatever application has focus
*while you are still speaking*. Everything runs locally: the microphone audio is
decoded by a Vosk model on this machine and never leaves it.

    python ar_dictate.py                    # live dictation with the hotkey
    python ar_dictate.py --wav sample.wav    # replay a file (no mic, no typing)
    python ar_dictate.py --list-devices      # show microphones
    python ar_dictate.py --list-hotkeys-config

Hotkeys (config.json -> "hotkey"):
    toggle      start / stop dictation
    mode_key    switch between فصحى (msa) and لهجة (dialect) post-processing
    quit_key    exit

Design notes worth knowing before editing:
  * The recognizer is fed 100 ms blocks straight from the microphone callback,
    so partial hypotheses arrive while the speaker is mid-sentence.
  * `streaming.CommitEngine` decides which of those words are stable enough to
    type; the rest wait in the pending tail. That is what stops the app from
    typing a word and then backspacing over it.
  * Only one thread ever calls the injector, so the edit state stays coherent.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import sys
import threading
import time
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
def user_data_dir() -> Path:
    """المجلد القابل للكتابة: يختلف بين نسخة المشروع والنسخة المثبَّتة.

    A packaged app must never try to write inside its own install folder (on
    Windows that lives under Program Files, which a normal user cannot write).
    The frozen build therefore keeps config, log and models under
    ``%LOCALAPPDATA%\\Keyboardless``; a source checkout keeps everything beside
    the project, exactly as before.
    """
    if getattr(sys, "frozen", False) or os.environ.get("AR_DICTATE_USER_DIR"):
        base = os.environ.get("AR_DICTATE_USER_DIR") or os.environ.get("LOCALAPPDATA")
        base = Path(base) if base else Path.home() / ".local" / "share"
        root = base if os.environ.get("AR_DICTATE_USER_DIR") else base / "Keyboardless"
        return root
    return HERE.parent


DEFAULT_CONFIG = (user_data_dir() / "config.json" if getattr(sys, "frozen", False)
                  else HERE / "config.json")
if str(HERE) not in sys.path:      # run as a script from anywhere
    sys.path.insert(0, str(HERE))
import branding  # noqa: E402


BUNDLED_CONFIG = HERE / "config.json"


def ensure_user_config(path: Path) -> bool:
    """Copy the shipped default config next to the user's data on first run.

    Returns True when the file was created, so the caller can say so. Without
    this, a freshly installed app has no config to read and every path (model,
    log) would be resolved against an empty dictionary.
    """
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    source = BUNDLED_CONFIG if BUNDLED_CONFIG.exists() else None
    data = json.loads(source.read_text(encoding="utf-8")) if source else {}
    models = user_data_dir() / "models"
    if source:
        # the models live in the user's folder in an installed copy
        data["model"] = str(models / Path(str(data.get("model", ""))).name)
        for key in ("models",):
            if isinstance(data.get(key), dict):
                data[key] = {k: str(models / Path(str(v)).name)
                             for k, v in data[key].items()}
    data["log"] = str(user_data_dir() / branding.LOG_NAME)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


def load_config(path: Path) -> dict:
    cfg = {
        "model": str(HERE.parent / "models" / "vosk-model-ar-mgb2-0.4"),
        "sample_rate": 16000,
        "chunk_ms": 100,
        "device": None,
        "mode": "msa",
        "injector": "sendinput",
        "hotkey": ["ctrl+alt+d", "ctrl+alt+j"],
        "mode_key": "ctrl+alt+m",
        "quit_key": "ctrl+alt+q",
        "punctuation": True,
        "auto_period": True,
        "space_before": False,
        "auto_stop_seconds": 0,
        "agc": True,
        "agc_target": 0.3,
        # pause separator: after this many seconds without a word, close the run
        # with `pause_sep` so a long dictation stays readable. 0 disables it.
        "pause_seconds": 0.0,
        "pause_sep": "\n",
        "log": "dictate.log",
    }
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
        # a relative model path is meant relative to the config file, not to
        # whatever directory the user happened to launch from
        if not Path(cfg["model"]).is_absolute():
            cfg["model"] = str((path.parent / cfg["model"]).resolve())
        # same for the log: it must not depend on the launch directory (a
        # double-click on the .cmd runs with the repo root as cwd, while a
        # direct python launch runs from app\)
        if not Path(cfg["log"]).is_absolute():
            cfg["log"] = str((path.parent / cfg["log"]).resolve())
    return cfg


class Dictation:
    """Owns the streaming decode loop and the commit logic."""

    def __init__(self, cfg: dict, injector):
        self.cfg = cfg
        self.injector = injector
        self.mode = cfg["mode"]
        self.log_path = Path(cfg["log"])
        self.active = False
        self._queue: queue.Queue[bytes | None] = queue.Queue()
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self.total_injected_chars = 0
        # the last text handed to the injector: a segment's closing glyph needs
        # to know whether the caret sits after a separator space or after a word
        self._last_typed = ""
        # audio-level accounting, reported every couple of seconds while
        # dictating so "the app hears nothing" is visible in the log
        self._audio_blocks = 0
        self._audio_peak = 0.0
        self._audio_reported = time.time()
        # quiet microphones are the number one cause of "nothing is typed"
        self.agc = AutoGain(cfg.get("agc_target", 0.3)) if cfg.get("agc", True) else None
        # ---- desktop UI hook -------------------------------------------------
        # The engine stays head-less: the window subscribes here instead of
        # scraping stdout, and the CLI simply leaves the hook unset.
        self.on_event = None
        # the window takes over the quit key (a graceful "close the app"
        # instead of "kill the audio loop") and needs to rebind hotkeys live
        self.on_quit = None
        self._hotkey_listener = None
        # a device change cannot be applied to a live PortAudio stream, so the
        # microphone pass is asked to reopen instead of restarting the app
        self._reload = threading.Event()
        # pause-separator bookkeeping (see _check_pause)
        self._last_voice_ts = time.time()
        self._pause_written = False
        self.new_engine()

    # ------------------------------------------------------------------ logging
    def log(self, msg: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
        if sys.stdout is None:      # a windowed build: the file below is the log
            self.emit("log", line=line)
            try:
                with self.log_path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass
            return
        try:
            print(line, flush=True)
        except UnicodeEncodeError:
            # A Windows console whose code page cannot represent the text (e.g.
            # cp1256 hit "->" in the char-count line) used to kill the whole run
            # from inside logging. The .cmd launcher sets chcp 65001, but a
            # plain PowerShell/cmd window does not -- degrade the console copy
            # and always keep the UTF-8 log file.
            enc = "utf-8"
            try:
                enc = sys.stdout.encoding or "utf-8"
                print(line.encode(enc, "replace").decode(enc, "replace"), flush=True)
            except Exception:
                pass
        try:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass
        self.emit("log", line=line)

    def emit(self, kind: str, **payload) -> None:
        """Hand one event to the desktop UI, if one is attached.

        Never raises: a broken window (or a UI running on another thread) must
        not be able to kill the dictation loop.
        """
        hook = self.on_event
        if hook is None:
            return
        try:
            hook(kind, payload)
        except Exception:  # noqa: BLE001
            pass

    # -------------------------------------------------------- injector plumbing
    def apply_edit(self, edit, post) -> None:
        """Realise one CommitEngine edit in the focused window.

        Backspacing has to be done in *characters*, but the engine thinks in
        words, so every word that gets typed is remembered together with how
        many characters it put on screen. Post-processing mutates the text
        (punctuation glyphs hug the preceding word, a space may be dropped), so
        the character delta it introduced is charged to the last word of the
        fragment -- that keeps the accounting exact enough for rewinds.
        """
        if edit.delete_words > 0:
            costs = self._word_costs[-edit.delete_words:]
            del self._word_costs[-edit.delete_words:]
            self.injector.press_backspace(sum(costs))
        if edit.insert_text:
            from postprocess import HUG_GLYPHS

            text = post(edit.insert_text)
            if text:
                prefix = " " if (self.cfg.get("space_before") and self.total_injected_chars == 0) else ""
                # A fragment can be *just* punctuation (the spoken word "فاصلة"
                # gets committed on its own once the words before it are already
                # on screen). Delete the separator that follows the previous word
                # so the glyph attaches to it instead of floating alone.
                if text[0] in HUG_GLYPHS and self.total_injected_chars > 0:
                    self.injector.press_backspace(1)
                    self.total_injected_chars -= 1
                    if self._word_costs:
                        self._word_costs[-1] -= 1
                # Fragments must not run into each other: without an explicit
                # separator the next insert lands on the same caret position and
                # "أعلنت" + "وزارة" reaches the screen as "أعلنتوزارة".
                sep = "" if text.endswith(("\n", " ")) else " "
                self.injector.type_text(prefix + text + sep)
                self._last_typed = prefix + text + sep
                typed_len = len(prefix) + len(text) + len(sep)
                self.total_injected_chars += typed_len
                self.emit("typed", chars=typed_len, total=self.total_injected_chars,
                          text=prefix + text + sep)
                # words are on screen again: the pause clock restarts, so a
                # separator is written once per silence, not once per sentence
                self._last_voice_ts = time.time()
                self._pause_written = False
                if self.cfg.get("log_injection", True):
                    # "nothing is typed" is the hardest bug to see from outside:
                    # record where the characters went, so the log can prove
                    # whether the window we typed into was the right one.
                    where = getattr(self.injector, "target_info", lambda: "?")()
                    snippet = (prefix + text + sep).replace("\n", "\\n")[:40]
                    self.log(f"typed {typed_len:>3} chars → {snippet!r} @ {where}")
                costs = [len(w) + 1 for w in edit.insert_text.split()]
                if costs:
                    # charge whatever post-processing added or removed to the
                    # last word so a rewind deletes exactly the right amount
                    costs[-1] += typed_len - sum(costs)
                    self._word_costs.extend(costs)

    # -------------------------------------------------------------------- engine
    def _gain_stage(self, data: bytes) -> bytes:
        """Apply the auto-gain; the microphone and WAV paths both go through here.

        Kept as one method on purpose: the live hotkey path and the offline
        replay must not drift apart, and a test can exercise the real thing.
        """
        return self.agc.apply(data) if self.agc else data

    def new_engine(self) -> None:
        from streaming import CommitEngine

        self._engine = CommitEngine(min_agree=2, hold_back=1)
        self._word_costs: list[int] = []
        return self._engine

    def handle_hypothesis(self, text: str, final: bool = False,
                          closing: str | None = None) -> None:
        """Feed one hypothesis from the recognizer.

        ``final=True`` closes the current segment, which happens at every pause:
        Vosk finishes the utterance, so the words that follow belong to a *new*
        segment and must be appended after ``closing`` instead of replacing what
        is on screen (see CommitEngine.seal_segment).

        ``closing`` is the glyph that ends the segment; ``None`` means "the
        config decides" -- a full stop, which is what stopping dictation means.
        A pause passes the configured ``auto_sep`` (a comma) instead, so pausing
        mid-thought continues the same line instead of ending the sentence.
        """
        from postprocess import HUG_GLYPHS, postprocess

        if closing is None:
            closing = "." if (final and self.cfg.get("auto_period", True)) else ""

        def post(fragment: str) -> str:
            return postprocess(
                fragment, mode=self.mode, punctuation=self.cfg["punctuation"],
                auto_period=False, closing=closing,
            )

        edit, pending = self._engine.update(text, final=final)
        if not edit.is_empty():
            self.apply_edit(edit, post)
        elif final and text.strip() and closing:
            # the segment closed with nothing new to insert (its words were
            # already on screen) -- the pause still deserves its separator
            self._type_closing(closing)
        if pending:
            tail = " ".join(pending)
            self._overlay_tail(tail)
        if final and text.strip():
            # everything after a pause is a continuation, never a rewording
            self._engine.seal_segment()

    def _type_closing(self, closing: str) -> None:
        """Type a segment's closing glyph when there were no new words.

        The previous fragment ended with a separator space; the glyph belongs to
        the word before it, so that space is taken back first and the character
        accounting is corrected with it (a later rewind must delete the right
        number of characters).
        """
        tail = self._last_typed
        from postprocess import HUG_GLYPHS

        if not tail or tail[-1] in HUG_GLYPHS + "\n":
            return
        if tail.endswith(" "):
            self.injector.press_backspace(1)
            self.total_injected_chars -= 1
            if self._word_costs:
                self._word_costs[-1] -= 1
        self.injector.type_text(closing)
        self.total_injected_chars += len(closing)
        if self._word_costs:
            self._word_costs[-1] += len(closing)
        self._last_typed = tail.rstrip(" ") + closing

    def _overlay_tail(self, tail: str) -> None:
        # the live "what am I hearing" line: console in CLI mode, the transcript
        # box in the desktop window
        self.emit("partial", text=tail)
        if self.cfg.get("verbose"):
            print(f"\r    …{tail[:60]:<60}", end="", flush=True)

    # ------------------------------------------------------------------- mic/loop
    def feed_wav(self, path: Path) -> None:
        """Offline replay: exercises the entire pipeline except microphone I/O."""
        from vosk import KaldiRecognizer

        with wave.open(str(path), "rb") as wf:
            if (wf.getnchannels(), wf.getframerate(), wf.getsampwidth()) != (1, 16000, 2):
                raise SystemExit(f"{path} must be 16 kHz mono 16-bit PCM")
            rec = KaldiRecognizer(self.model, wf.getframerate())
            rec.SetWords(True)
            self.new_engine()
            chunk = int(wf.getframerate() * self.cfg["chunk_ms"] / 1000)
            t0 = time.perf_counter()
            audio_s = 0.0
            while True:
                data = wf.readframes(chunk)
                if not data:
                    break
                audio_s += self.cfg["chunk_ms"] / 1000
                data = self._gain_stage(data)
                if rec.AcceptWaveform(data):
                    text = json.loads(rec.Result()).get("text", "")
                    # mirror the live path exactly: a pause closes the segment
                    self.handle_hypothesis(text, final=bool(text.strip()),
                                           closing=self.cfg.get("auto_sep", "،"))
                else:
                    part = json.loads(rec.PartialResult()).get("partial", "")
                    if part:
                        self.handle_hypothesis(part)
            self.handle_hypothesis(json.loads(rec.FinalResult()).get("text", ""), final=True,
                                   closing="." if self.cfg.get("auto_period", True) else "")
            self.injector.type_text("\n")
            wall = time.perf_counter() - t0
            print()
            self.log(f"wav={path.name} audio={audio_s:.1f}s decode={wall:.1f}s "
                     f"RTF={wall/max(audio_s,0.01):.3f}")

    def feed_mic(self) -> None:
        import sounddevice as sd
        from vosk import KaldiRecognizer

        rate = self.cfg["sample_rate"]
        block = int(rate * self.cfg["chunk_ms"] / 1000)

        def callback(indata, frames, time_info, status):  # runs on PortAudio thread
            if status:
                self.log(f"audio status: {status}")
            if self.active:
                self._queue.put(bytes(indata))

        # A device change cannot be applied to a live PortAudio stream, so the
        # whole microphone pass is wrapped in a loop that reopens the device
        # when the settings window asks for another input (or after a failure).
        while not self._stop.is_set():
            rec = KaldiRecognizer(self.model, rate)
            rec.SetWords(True)
            self._rec = rec  # so stop() can flush the words still held by the model
            self.new_engine()
            self._reload.clear()
            try:
                with sd.RawInputStream(samplerate=rate, blocksize=block,
                                       device=self.cfg["device"], dtype="int16",
                                       channels=1, callback=callback) as stream:
                    del stream  # only the side effect (an open device) matters
                    self.log(f"listening on device={self.cfg['device']}"
                             f" ({rate} Hz, {self.cfg['chunk_ms']} ms blocks)")
                    self.emit("listening", device=self.cfg["device"])
                    self._stream_loop(rec)
            except Exception as exc:  # noqa: BLE001
                # a device that is busy, unplugged or blocked must not kill the
                # app: report it, then keep trying so the user can fix it live
                self.log(f"audio device error: {exc}")
                self.emit("error", message=f"audio device error: {exc}")
                if self._stop.is_set():
                    break
                if self._device_fallback():
                    continue
                time.sleep(1.0)
            if self._stop.is_set():
                break
            self.log(f"reopening microphone (device={self.cfg['device']})")

    def _device_fallback(self) -> bool:
        """Give up on an unopenable input device and use the system default.

        Device indexes are global across host APIs, so a perfectly listed index
        can still refuse to open ("Could not obtain stream info" on a WASAPI /
        ASIO mix, measured on a test machine). Without this the user picks a
        microphone in the window and the app stays silent forever with one line
        in the log -- the worst possible outcome for a dictation tool.
        """
        if self.cfg.get("device") is None:
            return False
        self.log(f"falling back to the default microphone (device={self.cfg['device']} "
                 f"could not be opened)")
        self.cfg["device"] = None
        self.emit("device-fallback", device=None)
        return True

    def _stream_loop(self, rec) -> None:
        """One microphone pass: decode blocks until stopped or told to reopen."""
        last_voice = time.time()
        while not self._stop.is_set() and not self._reload.is_set():
            try:
                data = self._queue.get(timeout=0.2)
            except queue.Empty:
                data = None
            if data is None:
                self._check_pause()
                if self.active and self.cfg.get("auto_stop_seconds"):
                    if time.time() - last_voice > self.cfg["auto_stop_seconds"]:
                        self.log("auto-stop: silence")
                        self.stop()
                continue
            raw = data
            data = self._gain_stage(data)
            if self.active:
                self._audio_blocks += 1
                self._audio_peak = max(self._audio_peak, audio_peak(raw))
                self.emit("level", peak=audio_peak(raw))
                if time.time() - self._audio_reported >= 2.0:
                    gain = self.agc.gain if self.agc else 1.0
                    self.log(f"audio: {self._audio_blocks} blocks · mic peak {self._audio_peak:.4f}"
                             f" · gain x{gain:.1f}"
                             + ("  ← لا صوت يصل!" if self._audio_peak < 1e-4 else ""))
                    if self._audio_peak < 1e-4:
                        self.log("WARNING: no sound reaching the app — check the microphone, "
                                 "then run:  python ar_dictate.py --mic-level 5")
                    self.emit("meter", peak=self._audio_peak, gain=gain, blocks=self._audio_blocks)
                    self._audio_blocks = 0
                    self._audio_peak = 0.0
                    self._audio_reported = time.time()
            self._check_pause()
            if rec.AcceptWaveform(data):
                text = json.loads(rec.Result()).get("text", "")
                last_voice = time.time()
                # Vosk finishing the utterance *is* the pause the user hears.
                # It used to be fed as an ordinary hypothesis, so the words of
                # the next sentence looked like a rewording of this one and
                # erased it (measured on the user's PC, 2026-09).
                self.handle_hypothesis(text, final=bool(text.strip()),
                                       closing=self.cfg.get("auto_sep", "،"))
            else:
                part = json.loads(rec.PartialResult()).get("partial", "")
                if part:
                    last_voice = time.time()
                    self.handle_hypothesis(part)

    # ------------------------------------------------------------------ settings
    def _check_pause(self) -> None:
        """Close a run with the configured separator after a long enough silence.

        Wanted by the user as "put a separator between sentences after N seconds":
        the recogniser already ends the utterance, but what makes a long dictation
        readable on screen is the *visible* separator between runs. Written once
        per pause, then re-armed as soon as speech comes back.
        """
        if not self.active or self._pause_written:
            return
        pause = float(self.cfg.get("pause_seconds") or 0)
        if pause <= 0 or self.total_injected_chars == 0:
            return
        if time.time() - self._last_voice_ts < pause:
            return
        sep = self.cfg.get("pause_sep", "\n") or ""
        if not sep:
            return
        self._pause_written = True
        self.injector.type_text(sep)
        self.total_injected_chars += len(sep)
        self._last_typed = sep
        if self._word_costs and sep != "\n":
            # a glyph that hugs the previous word has to be removable with it
            self._word_costs[-1] += len(sep)
        self.log(f"pause {pause:.2f}s → separator {sep!r}")
        self.emit("typed", chars=len(sep), total=self.total_injected_chars, text=sep)

    def apply_settings(self, updates: dict) -> list[str]:
        """Live-apply settings coming from the desktop window.

        Returns the keys that the *application* has to handle (only ``model``
        today: loading another recogniser takes seconds and belongs in the UI,
        not in the audio thread). Everything else takes effect immediately --
        the microphone pass reopens itself for a device change.
        """
        deferred: list[str] = []
        for key, value in updates.items():
            if key == "agc_target" and self.agc:
                self.agc.target = float(value)
            elif key == "agc":
                if value and not self.agc:
                    self.agc = AutoGain(float(self.cfg.get("agc_target", 0.3)))
                elif not value:
                    self.agc = None
            elif key == "device":
                if self.cfg.get("device") != value:
                    self._reload.set()
            elif key == "model":
                deferred.append(key)
            elif key == "mode":
                self.mode = value
            self.cfg[key] = value
        self.emit("settings", **{k: self.cfg.get(k) for k in updates})
        return deferred

    # -------------------------------------------------------------- start / stop
    def start(self) -> None:
        with self._state_lock:
            if self.active:
                return
            self.new_engine()
            self.total_injected_chars = 0
            self._last_typed = ""
            self._last_voice_ts = time.time()
            self._pause_written = False
            self.active = True
        self.log(f"▶ dictation START (mode={self.mode})")
        self.log(f"target window: {getattr(self.injector, 'target_info', lambda: '?')()}")
        self.emit("state", active=True, mode=self.mode)
        self._audio_blocks = 0
        self._audio_peak = 0.0
        self._audio_reported = time.time()

    def stop(self) -> None:
        with self._state_lock:
            if not self.active:
                return
            self.active = False
        # flush whatever the recognizer still holds so no words are lost
        if getattr(self, "_rec", None) is not None:
            try:
                self.handle_hypothesis(
                    json.loads(self._rec.FinalResult()).get("text", ""), final=True,
                    closing="." if self.cfg.get("auto_period", True) else "")
            except Exception as exc:  # noqa: BLE001
                self.log(f"final flush failed: {exc}")
        self.log(f"■ dictation STOP — typed {self.total_injected_chars} chars"
                 + ("" if self.total_injected_chars else
                    "  (nothing was written: check 'audio:' lines above and the target window)"))
        self.emit("state", active=False, mode=self.mode)
        self.emit("stopped", chars=self.total_injected_chars)

    def toggle(self) -> None:
        self.stop() if self.active else self.start()

    def switch_mode(self) -> None:
        self.set_mode("dialect" if self.mode == "msa" else "msa")

    def set_mode(self, mode: str) -> None:
        """Pick the recogniser variant explicitly (the window offers both)."""
        if mode not in ("msa", "dialect") or mode == self.mode:
            return
        self.mode = mode
        self.log(f"mode switched -> {self.mode}")
        self.emit("state", active=self.active, mode=self.mode)


class AutoGain:
    """Lift quiet microphone input to a level the recogniser can actually use.

    Measured on a test machine: the built-in array reports ambient at peak
    0.007 and only slightly more while speaking. Rescaling a known-good Arabic
    sample proved the recogniser transcribes at peak 0.03 but returns *nothing
    at all* at 0.003 -- indistinguishable from "the app is broken".

    Gain is only ever applied upward, capped, and refused below the noise floor,
    so loud input is bit-identical and a silent room is not amplified to noise.
    """

    def __init__(self, target: float = 0.3, max_gain: float = 50.0,
                 floor: float = 2e-4, release: float = 0.94, smooth: float = 0.25):
        self.target = target
        self.max_gain = max_gain
        self.floor = floor
        self.release = release
        self.smooth = smooth
        self._recent = 0.0
        self._gain = 1.0

    def apply(self, data: bytes) -> bytes:
        """Return the block, amplified towards ``target`` when it is quiet."""
        import array

        samples = array.array("h")
        samples.frombytes(data[: len(data) // 2 * 2])
        if not samples:
            return data
        peak = max(max(samples), -min(samples)) / 32768.0
        # attack at once (never clip the first syllable), release over ~1.5 s
        self._recent = max(peak, self._recent * self.release)
        if self._recent < self.floor:
            want = 1.0
        else:
            # only ever amplify: loud input is returned bit-identical
            want = max(1.0, min(self.max_gain, self.target / self._recent))
        # smooth the gain so consecutive blocks do not pump
        self._gain += (want - self._gain) * self.smooth
        if self._gain <= 1.01:
            return data
        gain = self._gain
        out = array.array("h", (max(-32768, min(32767, int(sample * gain)))
                                for sample in samples))
        return out.tobytes()

    @property
    def gain(self) -> float:
        return self._gain


def audio_peak(data: bytes) -> float:
    """Largest absolute 16-bit sample in a block, normalised to 0..1.

    Used by the microphone diagnostics: a peak near zero while the user talks
    means the audio never arrived (muted, wrong device, or blocked by Windows
    privacy settings) -- which otherwise looks exactly like "the app does
    nothing".
    """
    import array

    if not data:
        return 0.0
    samples = array.array("h")
    samples.frombytes(data[: len(data) // 2 * 2])
    if not samples:
        return 0.0
    return max(max(samples), -min(samples)) / 32768.0


def mic_level(d, seconds: float = 5.0) -> int:
    """Record from the configured microphone, report level, then transcribe.

    Answers the only question that matters when the hotkey works but nothing
    is typed: did audio actually reach the app? A near-zero peak separates a
    muted / wrong / OS-blocked microphone from a decoding or injection fault.
    """
    import sounddevice as sd

    cfg = d.cfg
    rate = cfg["sample_rate"]
    block = int(rate * cfg["chunk_ms"] / 1000)
    agc = d.agc
    frames: list[bytes] = []
    peaks: list[float] = []
    print(f"recording {seconds:.0f}s from device={cfg['device']!r} -- تكلم الآن بشكل عادي …",
          flush=True)
    with sd.RawInputStream(samplerate=rate, blocksize=block, device=cfg["device"],
                           dtype="int16", channels=1) as stream:
        done = 0.0
        while done < seconds:
            data, _overflowed = stream.read(block)
            raw = bytes(data)
            frames.append(agc.apply(raw) if agc else raw)
            peaks.append(audio_peak(raw))
            done += cfg["chunk_ms"] / 1000.0
            print(".", end="", flush=True)
    print()
    per_second = max(1, int(round(1.0 / (cfg["chunk_ms"] / 1000.0))))
    for i in range(0, len(peaks), per_second):
        chunk = peaks[i:i + per_second]
        loud = max(chunk) if chunk else 0.0
        print(f"  {i * cfg['chunk_ms'] / 1000.0:5.1f}s  peak {loud:.4f}  {'#' * min(40, int(loud * 40))}")
    top = max(peaks) if peaks else 0.0
    if top < 1e-4:
        print("MIC SILENT: peak ≈ 0 — لا يصل أي صوت إلى البرنامج.")
        print("  * ويندوز: Settings > Privacy & security > Microphone > 'Let desktop apps' = ON")
        print("  * تأكد أن المايك غير مكتوم (Sound settings) وأن اللابتوب لا يستعمل مدخلًا آخر")
        print("  * اختر مدخلًا آخر:  ar_dictate.py --list-devices   ثم  --device <رقم>")
        return 1
    print(f"MIC OK: peak {top:.4f}"
          + (f" · auto-gain x{agc.gain:.1f}" if agc else " (auto-gain off)"))
    from vosk import KaldiRecognizer

    rec = KaldiRecognizer(d.model, rate)
    for raw in frames:
        rec.AcceptWaveform(raw)
    text = json.loads(rec.FinalResult()).get("text", "").strip()
    if text:
        print(f"heard: {text}")
        return 0
    print("heard: (لم يُتعرّف على كلام) — الصوت يصل لكن لم تُفهم كلمات.")
    return 2


def pynput_combo(spec: str) -> str:
    """Translate a hotkey string into pynput's syntax.

    ``"ctrl+alt+space"`` -> ``"<ctrl>+<alt>+<space>"``. pynput's GlobalHotKeys
    only accepts the angle-bracket form: it raises ``ValueError: ctrl`` for the
    plain ``keyboard``-style string, which is what the config uses.
    """
    aliases = {"control": "ctrl", "win": "cmd", "super": "cmd", "meta": "cmd",
               "option": "alt", "escape": "esc", "return": "enter"}
    keys = [t for t in re.split(r"[\s+]+", str(spec).strip().lower()) if t]
    if not keys:
        raise ValueError(f"empty hotkey: {spec!r}")
    out = []
    for k in keys:
        k = aliases.get(k, k)
        # pynput accepts a printable single character bare ('m'), but a named
        # key only in angle brackets ('<ctrl>', '<space>', '<f9>'). Verified on
        # pynput 1.7.7: '<m>' raises ValueError, 'm' works.
        out.append(k if len(k) == 1 else f"<{k}>")
    return "+".join(out)


def vk_code(name: str) -> int:
    """Virtual-key code for a key name (Windows), or -1 if unknown."""
    name = name.strip().lower()
    aliases = {"win": "cmd", "super": "cmd", "meta": "cmd", "control": "ctrl",
               "escape": "esc", "return": "enter", "option": "alt"}
    name = aliases.get(name, name)
    if len(name) == 1 and name.isalnum():
        return ord(name.upper())
    table = {"space": 0x20, "tab": 0x09, "enter": 0x0D, "esc": 0x1B,
             "backspace": 0x08, "delete": 0x2E, "insert": 0x2D, "home": 0x24,
             "end": 0x23, "page_up": 0x21, "page_down": 0x22,
             "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
             "cmd": 0x5B, "ctrl": 0x11, "alt": 0x12, "shift": 0x10,
             "`": 0xC0, "-": 0xBD, "=": 0xBB}
    match = re.fullmatch(r"f([1-9]|1[0-2])", name)
    if match:
        return 0x6F + int(match.group(1))
    return table.get(name, -1)


def hotkey_claim(spec: str) -> str:
    """Has another program already registered this combination?

    This is the question that "my shortcut opens Claude instead" really is.
    Windows answers it: ``RegisterHotKey`` returns 0 and sets
    ``ERROR_HOTKEY_ALREADY_REGISTERED`` (1409) when somebody else owns the
    combination. We register and immediately release, so nothing is stolen.

    Returns ``free`` / ``TAKEN`` / ``unknown (...)`` / ``n/a`` (not Windows).
    """
    if os.name != "nt":
        return "n/a"
    try:
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        mods = {"ctrl": 0x0002, "alt": 0x0001, "shift": 0x0004, "cmd": 0x0008}
        parsed = 0
        key = -1
        for part in [t for t in re.split(r"[\s+]+", spec.strip().lower()) if t]:
            part = {"control": "ctrl", "win": "cmd", "super": "cmd",
                    "meta": "cmd", "option": "alt"}.get(part, part)
            if part in mods:
                parsed |= mods[part]
            else:
                key = vk_code(part)
        if key < 0 or not parsed:
            return f"unknown (cannot parse {spec!r})"
        if user32.RegisterHotKey(None, 1, parsed, key):
            user32.UnregisterHotKey(None, 1)
            return "free"
        err = ctypes.get_last_error()
        if err == 1409:
            return "TAKEN"
        return f"unknown (win error {err})"
    except Exception as exc:  # noqa: BLE001 - diagnostics must never crash a run
        return f"unknown ({exc})"


def split_specs(value) -> list[str]:
    """Normalise a config hotkey field into a list of specs.

    A field may be a single string (``"ctrl+alt+d"``) or a list of fallbacks
    (``["ctrl+alt+d", "ctrl+alt+j"]``). Fallbacks matter on real machines:
    another app can own a combination and swallow the key before we ever see it
    (Claude Desktop owns ``ctrl+alt+space``), so listening on two keys means one
    being taken does not kill dictation.
    """
    items = value if isinstance(value, (list, tuple)) else [value]
    out: list[str] = []
    for item in items:
        for part in str(item).split(","):  # comma form inside a single string
            part = part.strip()
            if part and part not in out:
                out.append(part)
    if not out:
        raise ValueError(f"no hotkey in {value!r}")
    return out


def combo_list(value) -> list[str]:
    """Every pynput combo for a config field, validated (raises ValueError)."""
    return [pynput_combo(spec) for spec in split_specs(value)]


HOTKEY_FIELDS = ("hotkey", "mode_key", "quit_key")


def update_config_keys(path: Path, updates: dict,
                       hotkey_fields: tuple[str, ...] = HOTKEY_FIELDS) -> dict:
    """Write settings into ``config.json`` in place; everything else stays.

    Hotkey fields are validated (through the same ``pynput_combo`` the app uses)
    so a typo is rejected while the user is still looking at the command, instead
    of dying at the next launch in a window that closes too fast to read.
    Anything else -- numbers, switches, device indexes coming from the settings
    window -- is written as-is: validating those as key combinations used to
    raise ``ValueError: <0.297>`` the moment the sensitivity slider moved.
    """
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    try:
        from pynput.keyboard import HotKey
    except ImportError:
        HotKey = None
    for field, value in updates.items():
        if field not in hotkey_fields:
            data[field] = value
            continue
        combos = combo_list(value)  # validates first
        if HotKey is not None:
            for combo in combos:
                HotKey.parse(combo)  # pynput's own rejection path
        specs = split_specs(value)
        data[field] = specs if len(specs) > 1 else specs[0]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return data


KEY_ALIASES = {"control": "ctrl", "win": "cmd", "super": "cmd", "meta": "cmd",
               "option": "alt", "escape": "esc", "return": "enter",
               "pgup": "page_up", "pgdn": "page_down", "prior": "page_up",
               "next": "page_down", "del": "delete", "ins": "insert"}
# canonical modifier names, and the pynput side names they correspond to.
# pynput reports Key.ctrl_l / Key.alt_l / Key.cmd_l (not Key.ctrl), so the raw
# event name must be normalised before it can be compared with a combination.
MOD_CANON = {"ctrl": "ctrl", "alt": "alt", "shift": "shift",
             "win": "win", "cmd": "win", "super": "win", "meta": "win"}


def mod_name(raw: str | None) -> str | None:
    """``"ctrl_l"`` -> ``"ctrl"``; anything that is not a modifier -> None."""
    if not raw:
        return None
    if raw == "alt_gr":
        return "alt"
    base = raw[:-2] if raw.endswith(("_l", "_r")) else raw
    return MOD_CANON.get(base)


def parse_combo(spec: str) -> tuple[frozenset, str]:
    """``"ctrl+alt+d"`` -> ``(frozenset({"ctrl", "alt"}), "d")``.

    Raises ValueError when there is no modifier (a bare letter/function key
    would fire while typing) or when the combination has more than one main key.
    """
    parts = [p.strip("<>") for p in re.split(r"[\s+]+", str(spec).strip().lower()) if p]
    mods, mains = set(), []
    for part in parts:
        part = KEY_ALIASES.get(part, part)
        if part in MOD_CANON:
            mods.add(MOD_CANON[part])
        else:
            mains.append(part)
    if len(mains) != 1:
        raise ValueError(f"combination needs exactly one main key, got {spec!r}")
    if not mods:
        raise ValueError(f"combination needs a modifier (ctrl/alt/shift/win): {spec!r}")
    return frozenset(mods), mains[0]


def combo_matches(main: str, vk=None, char=None, name=None) -> bool:
    """Does a key event mean ``main``?

    Matched by **virtual-key code first**, and only then by character. That
    order is the fix for a real failure: with Ctrl+Alt held, a letter key emits
    no character at all (``char=None``) and on a non-Latin layout the character
    is not the Latin one either -- so pynput's character-based HotKey matching
    never fires for ctrl+alt+d on an Arabic (101) keyboard, even though the key
    arrives as ``vk=68``. Named keys (space, tab, f9) have no vk from pynput but
    report their name, so both are accepted.
    """
    wanted = KEY_ALIASES.get(main, main)
    if name is not None and KEY_ALIASES.get(name, name) == wanted:
        return True
    want_vk = vk_code(wanted)
    if want_vk > 0 and vk == want_vk:
        return True
    if char and len(wanted) == 1 and char.lower() == wanted:
        return True
    return False


def bind_hotkeys(d, cfg: dict) -> None:
    """Global hotkeys without needing an elevated process.

    ``keyboard`` hooks the keyboard through a filter driver only when the
    process is elevated; a normal double-click launch would silently get no
    hotkeys at all. ``pynput`` uses the ordinary low-level hook instead, so it
    works unelevated -- prefer it, and keep ``keyboard`` as the fallback for
    when pynput is missing.

    pynput's own ``GlobalHotKeys`` is deliberately NOT used: it matches keys by
    character, which never fires for a letter while Ctrl+Alt is held under a
    non-Latin layout (see ``combo_matches``). We keep our own modifier state and
    match on the virtual-key code instead.
    """
    # Rebinding from the settings window must not leave the old listener alive:
    # two live listeners would fire every press twice (toggle on, toggle off).
    old_listener = getattr(d, "_hotkey_listener", None)
    if old_listener is not None:
        try:
            old_listener.stop()
        except Exception:  # noqa: BLE001
            pass
        d._hotkey_listener = None

    bindings = []
    for spec in split_specs(cfg["hotkey"]):  # raw form; combo_list is only a preview
        bindings.append((spec, *parse_combo(spec), d.toggle))
    bindings.append((cfg["mode_key"], *parse_combo(cfg["mode_key"]), d.switch_mode))
    def quit_all() -> None:
        """Quit key: let the host app close itself if it registered a hook."""
        if getattr(d, "on_quit", None) is not None:
            d.on_quit()
            return
        d._stop.set()
        d._queue.put(None)
    bindings.append((cfg["quit_key"], *parse_combo(cfg["quit_key"]), quit_all))

    # a combination fires once per press, not on every auto-repeat
    fired: set[str] = set()

    def on_press(key) -> None:
        for spec, mods, main, callback in bindings:
            if mods != pressed:  # exact set: one extra modifier means no fire
                continue
            if combo_matches(main, vk=getattr(key, "vk", None),
                             char=getattr(key, "char", None),
                             name=getattr(key, "name", None)) and spec not in fired:
                fired.add(spec)
                callback()

    pressed: set[str] = set()

    def on_mod_press(key) -> None:
        canonical = mod_name(getattr(key, "name", None))
        if canonical:
            pressed.add(canonical)

    def on_release(key) -> None:
        canonical = mod_name(getattr(key, "name", None))
        if canonical:
            pressed.discard(canonical)
            for spec, mods, _main, _cb in bindings:
                if canonical in mods:
                    fired.discard(spec)  # re-arm once the modifier is let go

    try:
        from pynput import keyboard as pk

        # one hook, two callbacks: modifier state first, then combination match
        listener = pk.Listener(on_press=lambda k: (on_mod_press(k), on_press(k)),
                               on_release=on_release)
        listener.daemon = True
        listener.start()
        d._hotkey_listener = listener
        backend = "pynput/vk"
    except ImportError:
        import keyboard

        try:
            keyboard.unhook_all_hotkeys()   # a rebind must not double-fire either
        except Exception:  # noqa: BLE001
            pass

        # the keyword backend does its own matching, with the same caveat about
        # characters; it is only the last resort when pynput is unavailable
        for spec in split_specs(cfg["hotkey"]):
            keyboard.add_hotkey(spec, d.toggle, suppress=False)
        keyboard.add_hotkey(cfg["mode_key"], d.switch_mode, suppress=False)
        keyboard.add_hotkey(cfg["quit_key"], quit_all)
        backend = "keyboard (needs Administrator for the hook)"
    d.log(f"hotkeys[{backend}]: {' · '.join(split_specs(cfg['hotkey']))} = dictate · "
          f"{cfg['mode_key']} = mode · {cfg['quit_key']} = quit")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=f"{branding.PRODUCT_EN} — offline Arabic dictation")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--model", help="override model directory")
    ap.add_argument("--profile", choices=["fast", "accurate"],
                    help="fast = small model (keeps up on a laptop CPU), accurate = big model")
    ap.add_argument("--wav", type=Path, help="transcribe a 16 kHz mono WAV and exit")
    ap.add_argument("--mode", choices=["msa", "dialect"], help="override post-processing mode")
    ap.add_argument("--injector", choices=["sendinput", "clipboard", "stdout"])
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--agc", choices=["on", "off"],
                    help="auto-gain for quiet microphones (default: from config.json)")
    ap.add_argument("--device", type=int,
                    help="input device index for --mic-level (see --list-devices)")
    ap.add_argument("--mic-level", nargs="?", const=5.0, type=float, metavar="SECS",
                    help="record SECS (default 5) from the microphone, print the level, "
                         "then transcribe it — use when the hotkey works but nothing is typed")
    ap.add_argument("--check-hotkeys", action="store_true",
                    help="validate config hotkeys against the pynput syntax and exit")
    ap.add_argument("--print-hotkeys", action="store_true",
                    help="print the configured hotkeys (single source: config.json) and exit")
    ap.add_argument("--set-hotkey", metavar="COMBO",
                    help="set the dictate hotkey in config.json, e.g. ctrl+alt+d "
                         "(several, comma separated, are all bound as fallbacks)")
    ap.add_argument("--set-key", metavar="FIELD=COMBO", action="append",
                    help="set any hotkey field: hotkey | mode_key | quit_key")
    ap.add_argument("--version", action="version", version=branding.version_line())
    ap.add_argument("--models", action="store_true",
                    help="اعرض نماذج الصوت المتاحة والمثبّتة وأين")
    ap.add_argument("--ensure-model", nargs="?", const="", metavar="NAME",
                    help="نزّل النموذج (الافتراضي إن لم تُسمِّ) إلى المسار المخصص "
                         "— هذا ما يستدعيه المثبّت أثناء التثبيت")
    ap.add_argument("--models-dir", help="مجلد النماذج (افتراضي: المسار المخصص)")
    ap.add_argument("--about", action="store_true",
                    help="اطبع معلومات «حول البرنامج» (الاسم، الإصدار، المؤلف) واخرج")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    if getattr(sys, "frozen", False) or os.environ.get("AR_DICTATE_USER_DIR"):
        # a packaged copy keeps its settings in the user's folder: create them
        # from the shipped defaults the first time it runs
        ensure_user_config(Path(args.config))

    if args.about:
        print(branding.about_text())
        return 0

    if args.models or args.ensure_model is not None:
        import model_store

        directory = Path(args.models_dir) if args.models_dir else model_store.models_dir()

        def show_progress(name: str, done: int, total: int, phase: str) -> None:
            percent = (done / total * 100) if total else 0.0
            print(f"\r{name}: {phase:<26} {percent:5.1f}%  {model_store.human(done)}"
                  f"/{model_store.human(total)}", end="", flush=True)
            if phase == "installed":
                print()

        if args.ensure_model is not None:
            wanted = args.ensure_model or model_store.DEFAULT_MODEL
            try:
                path = model_store.download(wanted, directory, show_progress)
            except Exception as exc:  # noqa: BLE001
                print(f"\nفشل تنزيل النموذج: {exc}", file=sys.stderr)
                return 1
            print(f"النموذج جاهز: {path}")
            print("لتفعيله في الإعداد: اسم النموذج في app\\config.json ← \"model\"")
            return 0

        print(f"مجلد النماذج: {directory}")
        for info in model_store.ARABIC_MODELS:
            state = "مثبَّت" if model_store.is_installed(info.name, directory) else "غير مثبَّت"
            default = " (الافتراضي)" if info.name == model_store.DEFAULT_MODEL else ""
            print(f"  [{state}] {info.name}{default} — {info.size_mb}MB — {info.title}")
        return 0

    updates = {}
    if args.set_key:
        for item in args.set_key:
            field, _, spec = item.partition("=")
            field = field.strip()
            if not spec or field not in ("hotkey", "mode_key", "quit_key"):
                raise SystemExit(
                    f"bad --set-key {item!r}: use hotkey|mode_key|quit_key=<combo>")
            updates[field] = spec.strip()
    if args.set_hotkey:
        updates["hotkey"] = args.set_hotkey
    if updates:
        try:
            data = update_config_keys(args.config, updates)
        except ValueError as exc:
            raise SystemExit(f"bad hotkey: {exc}")
        for field in updates:
            print(f"{field:9} = {', '.join(split_specs(data[field]))}"
                  f"  ->  {' + '.join(combo_list(data[field]))}")
        print(f"saved to {args.config}")
        print(f"أغلق نافذة {branding.LAUNCHER} وأعد فتحها ليعمل الاختصار الجديد.")
        return 0
    cfg = load_config(args.config)
    if args.print_hotkeys:
        print(f"dictate: {' · '.join(split_specs(cfg['hotkey']))}   "
              f"mode: {cfg['mode_key']}   quit: {cfg['quit_key']}")
        return 0

    if args.list_devices:
        import sounddevice as sd

        print(sd.query_devices())
        return 0

    for key, val in (("model", args.model), ("mode", args.mode), ("injector", args.injector)):
        if val:
            cfg[key] = val
    if args.agc:
        cfg["agc"] = args.agc == "on"
    if args.device is not None:
        cfg["device"] = args.device
    if args.profile:
        profiles = cfg.get("models") or {}
        if args.profile not in profiles:
            raise SystemExit(f"no model configured for profile {args.profile!r} in {args.config}")
        cfg["model"] = profiles[args.profile]
    if args.verbose:
        cfg["verbose"] = True

    if args.check_hotkeys:
        rc = 0
        try:
            from pynput.keyboard import HotKey
        except ImportError:
            HotKey = None
        for name in ("hotkey", "mode_key", "quit_key"):
            for spec in split_specs(cfg[name]):
                combo = pynput_combo(spec)
                try:
                    mods, main = parse_combo(spec)
                    if vk_code(main) <= 0 and main not in ("space", "tab", "enter", "esc"):
                        print(f"FAIL {name:9} {spec:16} -> unknown main key {main!r}")
                        rc = 2
                except ValueError as exc:
                    print(f"FAIL {name:9} {spec:16} -> {exc}")
                    rc = 2
                    continue
                claim = hotkey_claim(spec)
                note = "" if claim == "n/a" else f"  [{claim}]"
                if claim == "TAKEN":
                    rc = 2
                if HotKey is None:
                    print(f"?    {name:9} {spec:16} -> {combo:26}{note} (pynput missing; keyboard backend takes the raw form)")
                    continue
                try:
                    HotKey.parse(combo)
                    print(f"OK   {name:9} {spec:16} -> {combo:26}{note}")
                except Exception as exc:
                    print(f"FAIL {name:9} {spec:16} -> {combo:26} {type(exc).__name__}: {exc}")
                    rc = 2
        if rc:
            print("\n[TAKEN] = another program already owns that combination (it will open "
                  "that program instead).\n        pick a free one:  ar_dictate.py --set-hotkey ctrl+alt+j")
        return rc
    if args.wav and not args.injector:
        cfg["injector"] = "stdout"

    model_dir = Path(cfg["model"])
    if not model_dir.is_absolute():
        # profile paths in config.json (fast/accurate) are written relative to the
        # app folder; resolving them against the *launch* directory broke the
        # double-click path, which runs with the repo root as cwd
        model_dir = (args.config.resolve().parent / model_dir).resolve()
        cfg["model"] = str(model_dir)
    if not model_dir.exists():
        raise SystemExit(
            f"model not found: {model_dir}\n"
            f"download it with:  download_model.ps1   (or point --model at vosk-model-ar-mgb2-0.4)"
        )

    from vosk import Model, SetLogLevel

    SetLogLevel(-1)
    t0 = time.perf_counter()
    print(f"loading model {model_dir.name} …", flush=True)
    model = Model(str(model_dir))
    print(f"model ready in {time.perf_counter()-t0:.1f}s", flush=True)

    from inject_win import make_injector

    injector = make_injector(cfg["injector"],
                            restore_clipboard=cfg.get("restore_clipboard", True))
    d = Dictation(cfg, injector)
    d.model = model

    if args.mic_level:
        return mic_level(d, args.mic_level)
    if args.wav:
        d.feed_wav(args.wav)
        return 0

    bind_hotkeys(d, cfg)
    d.log(f"{branding.PRODUCT_EN} {branding.VERSION} ready. "
          f"Press the hotkey and start talking.")
    try:
        d.feed_mic()
    except KeyboardInterrupt:
        pass
    finally:
        injector.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
