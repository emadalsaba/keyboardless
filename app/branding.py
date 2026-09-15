"""هوية المنتج — الاسم في مكان واحد.

The product is *Keyboardless* (بدون كيبورد). Everything the user can read -- the
window title, the tray tooltip, the console banner, the launcher file names --
comes from here, so a rename is one edit instead of a hunt through the tree.

Internal names deliberately stay as they are: the repository folder, the engine
module ``ar_dictate.py`` and the log file. They are not product surfaces, and
renaming them would break the launchers, the probes and every path in the skill
notes for no user-visible gain.
"""

from __future__ import annotations

PRODUCT_EN = "Keyboardless"
PRODUCT_AR = "بدون كيبورد"
TAGLINE = "إملاء صوتي عربي بدون إنترنت"
#: 1.0.2 adds the dedication below to the About box, the command line, the
#: installer and the documentation -- a visible content change, so the version
#: moves with it.
VERSION = "1.0.2"

# ---- صاحب البرنامج: يظهر في نافذة «حول البرنامج» وفي --about ----
AUTHOR_AR = "عماد السبع"
AUTHOR_ROLE_AR = "المبرمج"
AUTHOR_LINE_AR = f"تم إنشاؤه بواسطة {AUTHOR_ROLE_AR} {AUTHOR_AR}"
LINKEDIN = "https://www.linkedin.com/in/emad-alsaba"
LINKEDIN_LABEL = "linkedin.com/in/emad-alsaba"
COPYRIGHT = f"© 2026 {AUTHOR_AR}"
#: إهداء: البرنامج صدقة — يظهر في «حول البرنامج»، وفي سطر الأوامر، وفي شاشة
#: التثبيت، وفي التوثيق. صياغة فصحى واضحة تحفظ معنى طلب عماد.
DEDICATION_AR = "أحتسبه عند ربي صدقةً عني وعن والديّ وأهلي."
DEDICATION_EN = "A charity on behalf of myself, my parents and my family."

#: ما يشرحه البرنامج عن نفسه: محلي بلا إنترنت، ونموذج مفتوح المصدر
ABOUT_NOTE = ("يعمل بلا إنترنت: التعرف الصوتي يتم على جهازك بالكامل عبر نموذج Vosk "
              "العربي مفتوح المصدر (رخصة Apache-2.0).")

#: one line that names the product in both languages
TITLE = f"{PRODUCT_EN} — {PRODUCT_AR}"
WINDOW_TITLE = f"{TITLE} · {TAGLINE}"

#: lowercase form used for temp files, user agent strings and folders
SLUG = "keyboardless"
#: where an *installed* copy keeps its data (%LOCALAPPDATA%\<DATA_DIR>)
DATA_DIR = "Keyboardless"

#: the files the user double-clicks
LAUNCHER = "keyboardless.cmd"
LAUNCHER_GUI = "keyboardless-gui.cmd"
CHECKER = "keyboardless-check.cmd"
#: kept for compatibility with everything already written down
OLD_LAUNCHERS = ("ar-dictate.cmd", "ar-dictate-gui.cmd", "ar-dictate-check.cmd")

#: the log file keeps its historical name: config.json owns its path, and the
#: existing logs on the user's machine are still the ones worth reading
LOG_NAME = "dictate.log"


def banner(width: int = 44) -> str:
    """The two-line banner printed by the console launcher."""
    rule = "=" * width
    return (f"{rule}\n  {PRODUCT_EN} ({PRODUCT_AR}) — {TAGLINE}\n{rule}\n")


def version_line() -> str:
    return f"{PRODUCT_EN} {VERSION} — {PRODUCT_AR}"


def about_text() -> str:
    """نص «حول البرنامج» بلا واجهة رسومية (للطرفية ولصفحة إنهاء التثبيت)."""
    return "\n".join(about_lines())


def about_lines() -> list[str]:
    return [
        TITLE,
        f"الإصدار {VERSION}",
        AUTHOR_LINE_AR,
        DEDICATION_AR,
        f"لينكدإن: {LINKEDIN}",
        ABOUT_NOTE,
        COPYRIGHT,
    ]
