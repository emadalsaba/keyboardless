"""hook_test.py -- does THIS machine actually deliver our hotkeys to pynput?

Run it in the session where you type (double-click ar-dictate-check.cmd, or run
this file with the venv python). The combinations it listens for come from
``app/config.json`` (``hotkey``, one or several fallbacks), not from a literal
in this file: when Claude Desktop owned ctrl+alt+space, a hardcoded default here
kept testing the wrong key and hid the real problem.

Exit 0 = at least one configured combination reached the keyboard hook, so the
         OS/hook path is fine for that key.
Exit 1 = none arrived: a program that claims the key is swallowing it (Claude
         Desktop claims ctrl+alt+space), or the hook cannot see the window you
         are typing in (an elevated app), or the app never started.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ar_dictate import combo_list, load_config  # noqa: E402  (single source of truth)

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--combo",
                    help="test this combination instead of the config ones "
                         "(comma separated for several)")
    ap.add_argument("--seconds", type=int, default=15)
    args = ap.parse_args()

    try:
        specs = [s.strip() for s in args.combo.split(",")] if args.combo else None
        cfg = load_config(args.config)
        combos = [c for c in combo_list(specs or cfg["hotkey"])]
        combo_specs = list(zip(specs or (cfg["hotkey"] if isinstance(cfg["hotkey"], list)
                                         else [cfg["hotkey"]]), combos))
    except Exception as exc:  # bad config should not look like a dead hotkey
        print(f"could not read hotkeys from {args.config}: {type(exc).__name__}: {exc}")
        return 2

    from pynput.keyboard import HotKey, Listener

    seen: dict[str, list[float]] = {combo: [] for combo in combos}
    hooks = {combo: HotKey(HotKey.parse(combo),
                           (lambda c: (lambda: seen[c].append(time.monotonic())))(combo))
             for combo in combos}
    state: dict = {}

    def normalize(key):
        return state["listener"].canonical(key)

    def on_press(key) -> None:
        for hook in hooks.values():
            hook.press(normalize(key))

    def on_release(key) -> None:
        for hook in hooks.values():
            hook.release(normalize(key))

    listed = "  |  ".join(f"{spec} -> {combo}" for spec, combo in combo_specs)
    print(f"Press one of these now -- listening for {args.seconds} s ...")
    print(f"  {listed}", flush=True)
    listener = Listener(on_press=on_press, on_release=on_release)
    state["listener"] = listener
    listener.start()
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline and not any(seen.values()):
            time.sleep(0.05)
    finally:
        listener.stop()

    hit = [c for c in combos if seen[c]]
    for spec, combo in combo_specs:
        print(f"  {'OK: captured' if seen[combo] else 'NOT captured'} {spec} ({combo})")
    if hit:
        print("RESULT: hook works on this machine for: " + ", ".join(hit))
        return 0
    print("RESULT: none of the configured hotkeys arrived -- the app would never "
          "hear them.")
    print("  * another program claims the key (Claude Desktop claims "
          "ctrl+alt+space): change it with")
    print("      ar_dictate.py --set-hotkey ctrl+alt+d,ctrl+alt+j")
    print("  * or you are typing into an elevated window (Run as administrator)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
