"""أيقونات Keyboardless: مسارات الحالات، أي حالة تُستخدم متى، وبناء ملف ICO.

The artwork is Emad's: four states (``ready`` جاهز, ``listening`` يُنصت,
``paused`` موقوف, ``mono`` أحادية اللون) at eight sizes, with a design note that
matters:

* 16, 20 and 24 px are **drawn by hand** for those sizes -- never downscale 256,
* the tray uses ``mono`` in dark mode, ``ready``/``listening`` otherwise,
* the application icon is ``ready``, switching to ``listening`` while recording.

Nothing here imports Qt, so the mapping and the ICO builder are testable on a
machine without a display (this project's Linux server has no libEGL).
"""

from __future__ import annotations

import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSET_DIR = HERE / "assets" / "icons"
PNG_DIR = ASSET_DIR / "png"
SVG_DIR = ASSET_DIR / "svg"

STATES = ("ready", "listening", "paused", "mono")
#: the sizes the designer exported (all four states, every size)
SIZES = (16, 20, 24, 32, 48, 64, 128, 256)
#: what goes into a Windows .ico, per the design notes
ICO_SIZES = (16, 20, 24, 32, 48, 256)
#: the size used for the window and the dialog artwork
DISPLAY_SIZE = 256
FALLBACK_SIZE = 64


def icon_path(state: str = "ready", size: int = DISPLAY_SIZE) -> Path | None:
    """مسار صورة الحالة بالمقاس المطلوب، أو أقرب مقاس متاح، أو None."""
    if state not in STATES:
        state = "ready"
    exact = PNG_DIR / f"keyboardless-{state}-{size}.png"
    if exact.exists():
        return exact
    for candidate in (DISPLAY_SIZE, 128, 64, 48, 32, 24, 20, 16):
        if candidate == size:
            continue
        path = PNG_DIR / f"keyboardless-{state}-{candidate}.png"
        if path.exists():
            return path
    return None


def window_state(active: bool, model_loaded: bool) -> str:
    """أيقونة النافذة: يُنصت أثناء الكتابة، موقوف قبل جاهزية النموذج، وإلا جاهز."""
    if active:
        return "listening"
    return "ready" if model_loaded else "paused"


def tray_state(active: bool, dark: bool) -> str:
    """أيقونة علبة النظام: الحالة ظاهرة دائمًا.

    دليل التصميم يقترح النسخة الأحادية في الوضع الداكن، وطلب عماد أن يُعرف
    الوضع من الأيقونة نفسها — فيبقى السكون أحاديًا في الداكن، ويظهر «يُنصت»
    لحظة العمل في الوضعين.
    """
    if active:
        return "listening"
    return "mono" if dark else "ready"


def system_prefers_dark() -> bool:
    """هل ويندوز في الوضع الداكن؟ يُقرأ من الريجستري، ولا يفشل على غير ويندوز."""
    try:
        import winreg  # noqa: PLC0415  (Windows-only module)

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return int(light) == 0
    except Exception:  # noqa: BLE001
        return False


def missing_assets() -> list[str]:
    """ما الناقص من الحزمة (يُستعمل في الفحص الذاتي وفي الاختبارات)."""
    missing: list[str] = []
    for state in STATES:
        for size in SIZES:
            path = PNG_DIR / f"keyboardless-{state}-{size}.png"
            if not path.exists():
                missing.append(path.name)
    return missing


def _png_size(blob: bytes) -> tuple[int, int]:
    """عرض/ارتفاع صورة PNG من ترويسة IHDR."""
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("ليس ملف PNG")
    width, height = struct.unpack(">II", blob[16:24])
    return int(width), int(height)


def write_ico(target: Path, state: str = "ready", sizes: tuple[int, ...] = ICO_SIZES) -> Path:
    """يبني ملف .ico متعدّد المقاسات من صور PNG (تنسيق Vista+).

    Qt يستطيع كتابة ICO بصورة واحدة فقط، وويندوز يريد عدة مقاسات في الملف نفسه:
    16 للشريط، 32/48 للشاشة، 256 لصفحة الإعدادات. لذلك يُبنى الملف هنا مباشرة.
    """
    entries: list[bytes] = []
    payloads: list[bytes] = []
    offset = 6 + 16 * len(sizes)
    for size in sizes:
        path = icon_path(state, size)
        if path is None:
            raise FileNotFoundError(f"أيقونة ناقصة: {state} {size}px")
        blob = path.read_bytes()
        width, height = _png_size(blob)
        entries.append(struct.pack("<BBBBHHII", width % 256, height % 256, 0, 0, 1, 32,
                                   len(blob), offset))
        payloads.append(blob)
        offset += len(blob)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(header + b"".join(entries) + b"".join(payloads))
    return target


def ico_entries(path: Path) -> list[tuple[int, int]]:
    """يقرأ مقاسات ملف ICO (للفحص: هل الملف يحتوي ما طلبه المصمم فعلًا)."""
    blob = path.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", blob[:6])
    if reserved != 0 or kind != 1:
        raise ValueError(f"{path.name}: ليس ملف ICO صالحًا")
    out: list[tuple[int, int]] = []
    for index in range(count):
        entry = blob[6 + 16 * index: 6 + 16 * (index + 1)]
        width, height = struct.unpack("<BB", entry[:2])
        out.append((width or 256, height or 256))
    return out
