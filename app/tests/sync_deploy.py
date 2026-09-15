"""نشر المشروع إلى جهاز ويندوز مع التحقّق بالبصمة (md5) لكل ملف.

A half-deployed tree is the failure mode that costs the most: the engine grew a
keyword argument the helper modules on the machine did not have, and the app died
on the first committed word. Copying "the files I remember" is how that happens,
so this script never guesses:

1. hashes every shipped file locally,
2. asks the device for its hashes in **one** call (PowerShell ``Get-FileHash``),
3. copies only what differs (one ``scp`` per file -- multi-target scp is broken
   on Windows OpenSSH),
4. re-reads the device hashes and fails loudly if anything is still different.

    python app/tests/sync_deploy.py            # laptop (default)
    python app/tests/sync_deploy.py --device desktop --check
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
PATTERNS = ("app/*.py", "app/*.json", "app/*.md", "app/*.ps1", "app/*.txt",
            "app/tests/*.py", "app/tests/*.ps1",
            "app/packaging/*.py", "app/packaging/*.ps1", "app/packaging/*.spec",
            "app/packaging/*.iss",
            # the artwork is part of the product: forgetting it here made a build
            # fail with "unable to find ...\\app\\assets" on the target machine
            "app/assets/icons/*.txt", "app/assets/icons/png/*.png",
            "app/assets/icons/svg/*.svg",
            # the published documentation travels with the code: a build that
            # names a version the README does not mention is a support ticket
            "README.md", "CHANGELOG.md", "LICENSE", ".gitignore",
            "docs/*.md", "docs/images/*.png",
            "*.cmd")
#: files that must never be copied over a working installation
SKIP: set[str] = set()

#: ``--remote-user`` override; empty = ask the device who it is
REMOTE_USER = ""
_user_cache: dict[str, str] = {}


def remote_user(device: str) -> str:
    """The account that owns the project folder on the device.

    Read from the device itself so the script is not tied to one machine's user
    name; ``--remote-user`` wins when SSH lands in a different account than the
    one that owns the folder.
    """
    if not REMOTE_USER:
        if device not in _user_cache:
            result = sh(["ssh", device, "echo %USERNAME%"])
            name = (result.stdout or "").strip().splitlines()
            if not name or not name[-1].strip():
                raise SystemExit(f"could not read the user name on {device}: "
                                 f"stdout={result.stdout!r} stderr={result.stderr!r}")
            _user_cache[device] = name[-1].strip().replace("\r", "")
        return _user_cache[device]
    return REMOTE_USER


def local_files() -> list[Path]:
    files: list[Path] = []
    for pattern in PATTERNS:
        files.extend(p for p in sorted(ROOT.glob(pattern)) if p.is_file())
    return [p for p in files if p.relative_to(ROOT).as_posix() not in SKIP]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def remote_dir(device: str) -> str:
    return f"C:/Users/{remote_user(device)}/ar-voice-typing"


def sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def remote_hashes(device: str, files: list[Path]) -> dict[str, str]:
    """One SSH round trip for every file's hash on the device."""
    listing = ",".join(f"'{f.relative_to(ROOT).as_posix()}'" for f in files)
    script = (
        f"$root = '{remote_dir(device)}';"
        f"$names = @({listing});"
        "foreach ($n in $names) { $p = Join-Path $root ($n -replace '/', '\\');"
        "  if (Test-Path $p) { $h = (Get-FileHash $p -Algorithm MD5).Hash.ToLower();"
        "    Write-Output ($h + ' ' + $n) } else { Write-Output ('missing ' + $n) } }"
    )
    result = sh(["ssh", device, f'powershell -NoProfile -Command "{script}"'])
    out: dict[str, str] = {}
    for line in result.stdout.splitlines():
        line = line.strip().replace("\r", "")
        if not line or " " not in line:
            continue
        digest, _, name = line.partition(" ")
        out[name] = digest.lower()
    return out


def ensure_remote_dirs(device: str, names: list[str]) -> None:
    """Create the folders the files need (a new package folder breaks scp).

    ``scp`` cannot create a missing parent directory, so copying the first file
    of a new package fails with a bare "scp: failed" and the deployment silently
    stays incomplete.
    """
    dirs = sorted({str(PurePosixPath(n).parent) for n in names if "/" in n})
    dirs = [d for d in dirs if d not in (".", "")]
    if not dirs:
        return
    root = remote_dir(device).replace("/", "\\")
    steps = "; ".join(
        f"New-Item -ItemType Directory -Force -Path (Join-Path '{root}' '{d}') | Out-Null"
        for d in dirs)
    sh(["ssh", device, f'powershell -NoProfile -Command "{steps}"'])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="نشر المشروع إلى الجهاز مع التحقّق")
    parser.add_argument("--device", default="laptop")
    parser.add_argument("--remote-user", default="",
                        help="اسم حساب الجهاز (افتراضيًا يُقرأ من الجهاز نفسه)")
    parser.add_argument("--check", action="store_true", help="تحقّق فقط، بلا نسخ")
    args = parser.parse_args(argv)

    global REMOTE_USER
    REMOTE_USER = args.remote_user

    files = local_files()
    local = {f.relative_to(ROOT).as_posix(): md5(f) for f in files}
    print(f"{len(files)} ملفًا محليًا · الجهاز: {args.device}")
    remote = remote_hashes(args.device, files)
    if not remote:
        print("تعذّر قراءة بصمات الجهاز (هل SSH يعمل؟)", file=sys.stderr)
        return 2

    to_send = [name for name, digest in local.items() if remote.get(name) != digest]
    print(f"مختلف: {len(to_send)} · مطابق: {len(local) - len(to_send)}")
    if args.check or not to_send:
        for name in sorted(to_send):
            print(f"  DIFF {name}")
        return 1 if to_send else 0

    ensure_remote_dirs(args.device, to_send)
    failed: list[str] = []
    for name in to_send:
        source = ROOT / name
        target = f"{args.device}:{remote_dir(args.device)}/{name}"
        result = sh(["scp", str(source), target])
        status = "ok" if result.returncode == 0 else f"FAILED {result.stderr.strip()[:120]}"
        print(f"  sent {name} — {status}")
        if result.returncode != 0:
            failed.append(name)

    after = remote_hashes(args.device, files)
    still = [name for name, digest in local.items() if after.get(name) != digest]
    print(f"\nبعد النشر: مطابق {len(local) - len(still)}/{len(local)}")
    for name in still:
        print(f"  STILL DIFFERENT: {name}")
    return 1 if (failed or still) else 0


if __name__ == "__main__":
    raise SystemExit(main())
