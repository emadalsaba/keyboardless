"""يبني أيقونة ويندوز (.ico) من تصميم عماد متعدّد المقاسات.

The designer's note is explicit: build the ICO from 16, 20, 24, 32, 48 and 256 --
the small sizes are drawn by hand and must not be downscaled. Qt can only write a
single-image ICO, so :func:`app_icons.write_ico` writes the real multi-size file.

    .venv\\Scripts\\python.exe app\\packaging\\make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))

import app_icons  # noqa: E402


def build(target: Path, state: str = "ready") -> Path:
    """اكتب ملف ICO بالمقاسات المطلوبة، وتحقّق أنه يحتويها فعلًا."""
    app_icons.write_ico(target, state=state, sizes=app_icons.ICO_SIZES)
    written = app_icons.ico_entries(target)
    expected = [(size, size) for size in app_icons.ICO_SIZES]
    if written != expected:
        raise SystemExit(f"{target.name}: المقاسات المكتوبة {written} != {expected}")
    return target


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "keyboardless.ico"
    state = sys.argv[2] if len(sys.argv) > 2 else "ready"
    path = build(out, state)
    sizes = " · ".join(str(size) for size, _ in app_icons.ico_entries(path))
    print(f"{path} ({path.stat().st_size} bytes) — مقاسات: {sizes}")
