"""تنزيل نماذج Vosk العربية المجانية وتثبيتها في المسار المخصص.

Everything the installer, the settings window and the command line need to get a
recogniser on the machine -- without asking the user a single question:

* :data:`ARABIC_MODELS` is the curated list of free Arabic models. ``size_mb`` is
  the **download** size, not the size on disk after unpacking (the small model is
  99.5 MB to fetch and 288 MB unpacked) -- it is what the progress bar and the
  user's data plan care about. Re-verify the list with ``--verify-urls``: a model
  name that looks plausible can still be a 404 (``vosk-model-ar-0.22-lgraph``
  was, and only a real request showed it).
* :func:`models_dir` is the dedicated path. The installed app keeps its models
  under ``%LOCALAPPDATA%\\Keyboardless\\models`` (never inside Program Files, which
  is read-only for a normal user) while a portable/development tree keeps using
  the ``models`` folder next to the project, so nothing moves under the user's
  feet.
* :func:`download` streams to a ``.part`` file, resumes what was already
  downloaded, verifies the archive and only then replaces the target folder.

Progress is reported through a plain callback so the same code serves a silent
installer, a Qt progress bar and a console.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

try:
    import branding
except ImportError:  # imported as part of the app package
    from . import branding  # type: ignore[no-redef]

MODELS_BASE = "https://alphacephei.com/vosk/models"
#: every model here is free (Apache-2.0) and works offline once downloaded
ARABIC_MODELS: tuple["ModelInfo", ...] = ()


@dataclass(frozen=True)
class ModelInfo:
    """One downloadable recogniser."""

    name: str          # the folder name after extraction (same as the zip stem)
    title: str         # what a human reads
    size_mb: int       # download size, for the progress bar and for honesty
    note: str          # when to pick it
    url: str = ""      # defaults to <MODELS_BASE>/<name>.zip

    @property
    def archive(self) -> str:
        return self.url or f"{MODELS_BASE}/{self.name}.zip"


ARABIC_MODELS = (
    ModelInfo(
        "vosk-model-small-ar-0.3", "عربي صغير — الأسرع (الافتراضي)", 100,
        "تنزيل 100MB فقط ويفتح 288MB. يكتب وهو تتكلم على أي لابتوب بلا بطاقة "
        "رسوميات، وهذا ما يُنزَّل تلقائيًا أثناء التثبيت.",
    ),
    ModelInfo(
        "vosk-model-ar-mgb2-0.4", "عربي دقيق (MGB2) — أبطأ من الزمن الحقيقي", 318,
        "تنزيل 318MB. دقّة أعلى لكنه غالبًا أبطأ من الكلام على المعالج؛ مناسب "
        "لتفريغ تسجيلات لا للإملاء المباشر.",
    ),
    ModelInfo(
        "vosk-model-ar-0.22-linto-1.1.0", "عربي كبير (LINTO) — للتفريغ لا للإملاء", 1314,
        "تنزيل 1.3GB ودقّة عالية، لكنه يحتاج جهازًا قويًا: استخدمه لتفريغ ملف "
        "صوتي، لا للإملاء المباشر.",
    ),
)
DEFAULT_MODEL = "vosk-model-small-ar-0.3"


def find(name: str) -> ModelInfo | None:
    for info in ARABIC_MODELS:
        if info.name == name:
            return info
    return None


def models_dir(root: Path | None = None) -> Path:
    """The dedicated place for the recognisers.

    ``AR_DICTATE_MODELS`` wins, then a ``models`` folder beside a portable
    checkout (how the project has always worked), and only then the per-user
    application folder used by a real installation.
    """
    override = os.environ.get("AR_DICTATE_MODELS")
    if override:
        return Path(override).expanduser()
    if root is not None:
        return Path(root)
    here = Path(__file__).resolve().parent
    portable = here.parent / "models"
    if (here.parent / "app" / "ar_dictate.py").exists() or portable.exists():
        return portable
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    base = Path(base) if base else Path.home() / ".local" / "share"
    return base / branding.DATA_DIR / "models"


# where a model is usable: these three folders are what vosk actually loads
_REQUIRED = ("am", "conf")
_SENTINEL = "conf/model.conf"


def is_installed(name: str, directory: Path | None = None) -> bool:
    """True when the model folder is present *and* looks like a loaded model."""
    path = (directory or models_dir()) / name
    return path.is_dir() and all((path / part).exists() for part in _REQUIRED)


def installed(directory: Path | None = None) -> dict[str, Path]:
    directory = directory or models_dir()
    return {info.name: directory / info.name for info in ARABIC_MODELS
            if is_installed(info.name, directory)}


def folder_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"


def _request(url: str, offset: int = 0, validator: str = "") -> urllib.request.addinfourl:
    request = urllib.request.Request(url, headers={"User-Agent": branding.SLUG})
    if offset:
        request.add_header("Range", f"bytes={offset}-")
        if validator:
            # If-Range makes the server answer 200 (start over) when the file it
            # holds is no longer the one the partial download belongs to
            request.add_header("If-Range", validator)
    return urllib.request.urlopen(request, timeout=60)  # noqa: S310 (fixed https host)


def _validator_of(response) -> str:
    """The server's fingerprint for the file (ETag, else Last-Modified)."""
    for header in ("ETag", "Last-Modified"):
        value = response.headers.get(header)
        if value:
            return value
    return ""


def _read_stamp(path: Path) -> str:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("validator", "")
    except (OSError, ValueError):
        return ""


def _write_stamp(path: Path, validator: str) -> None:
    if not validator:
        return
    try:
        path.write_text(json.dumps({"validator": validator}), encoding="utf-8")
    except OSError:
        pass


def download(info: ModelInfo | str, directory: Path | None = None,
             progress=None, retries: int = 3) -> Path:
    """Fetch one model into ``directory`` and return its folder.

    Already installed: returns immediately, no request. Interrupted earlier: the
    partial ``.part`` file is resumed, not thrown away (a 666 MB download on a
    slow line is exactly where a lost hour hurts). Progress is reported as
    ``progress(name, done_bytes, total_bytes, phase)``.
    """
    if isinstance(info, str):
        found = find(info)
        info = found or ModelInfo(info, info, 0, "")
    directory = Path(directory or models_dir())
    target = directory / info.name
    if is_installed(info.name, directory):
        if progress:
            size = folder_size(target)
            progress(info.name, size, size, "installed")
        return target

    directory.mkdir(parents=True, exist_ok=True)
    part = directory / f"{info.name}.zip.part"
    stamp = directory / f"{info.name}.zip.meta"
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            offset = part.stat().st_size if part.exists() else 0
            validator = _read_stamp(stamp)
            if offset and not validator:
                # without the server's fingerprint there is no way to prove the
                # partial bytes belong to *this* archive: start over
                offset = 0
                part.unlink(missing_ok=True)
            response = _request(info.archive, offset, validator)
            if not validator:
                _write_stamp(stamp, _validator_of(response))
            total = info.size_mb * 1024 * 1024
            length = response.headers.get("Content-Length")
            if length:
                total = int(length) + offset
            if offset and response.status != 206:
                # the server ignored the range request: start over instead of
                # gluing a second copy of the archive onto the first
                offset = 0
                part.unlink(missing_ok=True)
            done = offset
            if progress:
                progress(info.name, done, total, "downloading")
            with part.open("ab" if offset else "wb") as fh:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(info.name, done, total, "downloading")
            response.close()
            try:
                _extract(part, target, info)
            except Exception as broken:  # noqa: BLE001
                # BadZipFile is not a RuntimeError: catching only our own error
                # left the corrupt .part in place and every retry resumed from
                # the same broken offset (measured while testing this)
                # a truncated or corrupted partial download: throw it away and
                # fetch the whole archive again instead of failing for good
                part.unlink(missing_ok=True)
                stamp.unlink(missing_ok=True)
                raise RuntimeError(f"archive rejected, downloading again: {broken}") from broken
            part.unlink(missing_ok=True)
            stamp.unlink(missing_ok=True)
            if progress:
                progress(info.name, folder_size(target), folder_size(target), "installed")
            return target
        except Exception as exc:  # noqa: BLE001 -- retried below
            last_error = exc
            if progress:
                progress(info.name, part.stat().st_size if part.exists() else 0,
                         info.size_mb * 1024 * 1024, f"retry {attempt}/{retries}: {exc}")
            if attempt < retries:
                time.sleep(2 * attempt)
    raise RuntimeError(f"تعذّر تنزيل {info.name}: {last_error}")


def _extract(archive: Path, target: Path, info: ModelInfo) -> None:
    """Unpack the archive into ``target``, refusing anything suspicious.

    A downloaded zip is untrusted input: an entry like ``../../startup.bat``
    would otherwise be written outside the models folder. Every member is
    checked to stay inside the destination before a single byte is unpacked.
    """
    with tempfile.TemporaryDirectory(prefix="ar-dictate-unzip-") as staging:
        staging_path = Path(staging)
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                name = member.filename.replace("\\", "/")
                if name.startswith("/") or ".." in Path(name).parts:
                    raise RuntimeError(f"أرشيف غير آمن: {member.filename}")
                resolved = (staging_path / name).resolve()
                if not str(resolved).startswith(str(staging_path.resolve())):
                    raise RuntimeError(f"أرشيف غير آمن: {member.filename}")
            zf.extractall(staging_path)
        # the archive always contains one top-level folder
        candidates = [p for p in staging_path.iterdir() if p.is_dir()]
        source = candidates[0] if len(candidates) == 1 else staging_path
        if not (source / "conf").is_dir():
            raise RuntimeError(f"{archive.name}: ليس نموذج Vosk صالحًا "
                               f"(لا يوجد conf/ في {info.name})")
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(source), str(target))


def ensure_default(directory: Path | None = None, progress=None) -> Path:
    """What the installer calls: make sure the default model is on the machine."""
    return download(DEFAULT_MODEL, directory, progress)


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="تنزيل نماذج Vosk العربية المجانية")
    parser.add_argument("--dir", type=Path, default=None, help="المسار المخصص للنماذج")
    parser.add_argument("--list", action="store_true", help="اعرض النماذج المتاحة والمثبّتة")
    parser.add_argument("--json", action="store_true", help="الإخراج بصيغة JSON")
    parser.add_argument("--download", metavar="NAME", help="نزّل نموذجًا بالاسم")
    parser.add_argument("--ensure-default", action="store_true",
                        help="تأكّد من وجود النموذج الافتراضي (يُستخدم أثناء التثبيت)")
    parser.add_argument("--quiet", action="store_true", help="بلا تقدّم مطبوع")
    parser.add_argument("--verify-urls", action="store_true",
                        help="تحقّق من كل عنوان تنزيل (HEAD) — يمنع إدخال اسم نموذج "
                             "معقول لكنه غير موجود (404)")
    args = parser.parse_args(argv)
    directory = args.dir or models_dir()

    def show(name: str, done: int, total: int, phase: str) -> None:
        if args.quiet:
            return
        percent = (done / total * 100) if total else 0
        print(f"\r{name}: {phase:<28} {percent:5.1f}%  {human(done)}/{human(total)}",
              end="", flush=True)
        if phase == "installed":
            print()

    if args.verify_urls:
        import urllib.error

        problems = 0
        for info in ARABIC_MODELS:
            request = urllib.request.Request(info.archive, method="HEAD",
                                             headers={"User-Agent": branding.SLUG})
            try:
                with urllib.request.urlopen(request, timeout=45) as response:  # noqa: S310
                    size = int(response.headers.get("Content-Length", 0))
                    declared = info.size_mb * 1024 * 1024
                    off = abs(size - declared) / max(declared, 1) > 0.15
                    problems += 1 if off else 0
                    print(f"[OK]   {info.name}  {response.status}  "
                          f"{size/1024/1024:.1f}MB"
                          + (f"  ← الحجم المعلن {info.size_mb}MB مختلِف" if off else ""))
            except Exception as exc:  # noqa: BLE001
                problems += 1
                print(f"[FAIL] {info.name}  {exc}")
        print(f"نماذج بها مشكلة: {problems}")
        return 1 if problems else 0

    if args.list or (not args.download and not args.ensure_default):
        rows = [{
            "name": info.name, "title": info.title, "size_mb": info.size_mb,
            "note": info.note, "installed": is_installed(info.name, directory),
            "path": str(directory / info.name),
            "on_disk": human(folder_size(directory / info.name))
            if is_installed(info.name, directory) else None,
            "default": info.name == DEFAULT_MODEL,
        } for info in ARABIC_MODELS]
        if args.json:
            print(json.dumps({"models_dir": str(directory), "models": rows},
                             ensure_ascii=False, indent=2))
        else:
            print(f"مجلد النماذج: {directory}")
            for row in rows:
                mark = "مثبَّت" if row["installed"] else "غير مثبَّت"
                star = " (الافتراضي)" if row["default"] else ""
                print(f"  [{mark}] {row['name']}{star} — {row['size_mb']}MB — {row['title']}")
        return 0

    try:
        path = (ensure_default(directory, show) if args.ensure_default
                else download(args.download, directory, show))
    except Exception as exc:  # noqa: BLE001
        print(f"\nفشل: {exc}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"تم: {path} ({human(folder_size(path))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
