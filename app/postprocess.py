"""Post-processing for dictated Arabic: voice punctuation + dialect repair.

Two jobs that the acoustic model cannot do for us:

1. Punctuation. Vosk's Arabic acoustic model emits no punctuation at all, so a
   paragraph arrives as one undifferentiated run of words. The standard fix
   (and what Android's own dictation does) is voice commands: the speaker says
   "نقطة" / "فاصلة" / "سطر جديد" and the app substitutes the glyph. This is
   deterministic, has zero latency and never hallucinates, unlike a learned
   punctuation-restoration model.

2. Dialect repair. The only accurate offline Arabic model available for CPU
   streaming is trained on Modern Standard Arabic broadcast speech (MGB-2).
   Everyday Gulf/Saudi speech therefore loses or distorts exactly the words
   that carry the meaning ("عشان" -> "عشرين", "أبغى" disappearing). A small
   hand-built correction table fixes the recurring offenders immediately; long
   term this should be replaced by fine-tuning, but that is a separate project.
"""
from __future__ import annotations

import re
import unicodedata

# --------------------------------------------------------------------- commands
# Longest keys first at match time so "سطر جديد" wins over "سطر".
VOICE_COMMANDS: dict[str, str] = {
    "سطر جديد": "\n",
    "نقطة جديدة": "\n",
    "علامة استفهام": "؟",
    "علامة تعجب": "!",
    "علامة استفهاميه": "؟",
    "نقطتان": ":",
    "فاصلة منقوطة": "؛",
    "قوسين": "()",
    "نقطة": ".",
    "فاصله": "،",
    "فاصلة": "،",
    "مسافة": " ",
    "new line": "\n",
    "newline": "\n",
    "question mark": "?",
    "full stop": ".",
    "period": ".",
    "comma": "،",
}

# ---------------------------------------------------------------- dialect table
# Keys are what the recognizer produces, values what the speaker actually said.
DIALECT_FIXES: dict[str, str] = {
    "عشرين": "عشان",
    "الطلبة": "الطلب",
    "الجي": "الجاي",
    "ابغى": "أبغى",
    "ابي": "أبي",
    "وش": "وش",
    "ايش": "إيش",
    "الحين": "الحين",
    "دحين": "الحين",
    "عاد": "عاد",
    "وكذا": "وكذا",
    "زين": "زين",
    "ما ادري": "ما أدري",
}

# Multi-word repairs, applied before single-word ones.
DIALECT_PHRASES: dict[str, str] = {
    "ما ادري": "ما أدري",
    "ان شاء الله": "إن شاء الله",
    "باذن الله": "بإذن الله",
    "الاسبوع الجاي": "الأسبوع الجاي",
}

_ARABIC_DIACRITICS = re.compile(r"[\u0617-\u061A\u064B-\u0652\u0670\u0640]")


def strip_diacritics(text: str) -> str:
    """Remove harakat/tatweel -- speech output never carries them reliably."""
    text = _ARABIC_DIACRITICS.sub("", text)
    return unicodedata.normalize("NFC", text)


HUG_GLYPHS = ".،؛:!؟"  # glyphs that attach to the word before them

# Glyphs that already terminate a segment: nothing is appended after them.
_SENTENCE_ENDS = ".،؛:!؟\n"


def _apply_commands(words: list[str], commands: dict[str, str]) -> str:
    """Replace spoken punctuation words with glyphs and re-join the text."""
    out: list[str] = []
    i = 0
    keys = sorted(commands, key=lambda k: -len(k.split()))
    while i < len(words):
        matched = False
        for key in keys:
            parts = key.split()
            if words[i:i + len(parts)] == parts:
                glyph = commands[key]
                if glyph == "\n":
                    if out and out[-1] != "\n":
                        out.append("\n")
                elif glyph == " ":
                    pass
                elif glyph == "()":
                    out.append(glyph)
                else:
                    # punctuation glyphs hug the preceding word (Arabic style)
                    if out:
                        out[-1] = out[-1] + glyph
                    else:
                        out.append(glyph)
                i += len(parts)
                matched = True
                break
        if not matched:
            out.append(words[i])
            i += 1
    text = " ".join(w for w in out if w != "")
    text = re.sub(rf"\s+([{re.escape(HUG_GLYPHS)}])", r"\1", text)
    text = re.sub(r"\n\s+", "\n", text)
    return text.strip()


def postprocess(
    text: str,
    *,
    mode: str = "msa",
    punctuation: bool = True,
    auto_period: bool = True,
    closing: str = "",
    extra_fixes: dict[str, str] | None = None,
) -> str:
    """Clean one recognized segment.

    mode: "msa" applies no dialect repairs, "dialect" applies the repair tables.
    closing: glyph typed at the end of a *closed* segment (a pause closes one).
        The caller decides what a pause means: the app appends "،" when the
        speaker merely paused and "." when they stopped dictating. It is only
        added when the text does not already end with punctuation, so a spoken
        "نقطة" is never doubled.
    """
    text = strip_diacritics(text.strip())
    if not text:
        return ""

    if mode == "dialect":
        fixes = {**DIALECT_PHRASES, **(extra_fixes or {})}
        for wrong, right in fixes.items():
            text = re.sub(rf"(?<!\S){re.escape(wrong)}(?!\S)", right, text)
        text = " ".join(DIALECT_FIXES.get(w, w) for w in text.split())

    if punctuation:
        text = _apply_commands(text.split(), VOICE_COMMANDS)
        if text and text[-1] not in _SENTENCE_ENDS:
            if closing:
                # a closed segment carries the caller's separator (a pause) --
                # it must hug the last word, which is why it is appended here
                # and not by the injector
                text += closing
            elif auto_period:
                text += "."
    return text
