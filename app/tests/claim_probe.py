"""claim_probe.py -- which candidate dictate shortcuts are free on THIS machine?

Windows-only. For each combination it asks the OS whether another program has
already registered it (``RegisterHotKey`` -> error 1409). That is the failure
mode behind "my shortcut opens Claude": the other program wins, our app never
sees the key -- and a passive listener like pynput cannot tell you that.

Usage (from the repo root, venv python):

    .venv\\Scripts\\python.exe app\\tests\\claim_probe.py
    .venv\\Scripts\\python.exe app\\tests\\claim_probe.py ctrl+alt+d win+alt+space

Exit code 0 when every combination asked about is free, 2 when any is taken.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ar_dictate import hotkey_claim, pynput_combo  # noqa: E402

CANDIDATES = [
    "ctrl+alt+space",     # Claude Desktop's quick-entry default: expected TAKEN
    "ctrl+alt+d",
    "ctrl+alt+j",
    "shift+alt+d",
    "ctrl+shift+space",
    "win+alt+space",
    "ctrl+alt+f9",
]


def main(argv: list[str]) -> int:
    combos = argv or CANDIDATES
    taken = 0
    print(f"{'combination':22} {'claim':14} pynput syntax")
    print("-" * 62)
    for spec in combos:
        claim = hotkey_claim(spec)
        if claim == "TAKEN":
            taken += 1
        print(f"{spec:22} {claim:14} {pynput_combo(spec)}")
    print("\nTAKEN = another program owns it (it will open that program instead).")
    print("A combination needs at least one modifier (ctrl/alt/shift/win).")
    print("Pick a 'free' one with:")
    print("  .venv\\Scripts\\python.exe app\\ar_dictate.py --set-hotkey <combination>")
    return 2 if taken else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
