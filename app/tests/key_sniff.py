"""key_sniff.py -- print every key event pynput sees, with its virtual-key code
and the character the CURRENT keyboard layout produces. Diagnoses the class of
bug where a letter shortcut never fires (layout-dependent character matching),
as opposed to the key never arriving at all.
"""
import sys, time
from pynput import keyboard

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0

def show(kind, key):
    vk = getattr(key, "vk", None)
    char = getattr(key, "char", None)
    print(f"{time.strftime('%H:%M:%S')} {kind:7} {str(key):22} vk={vk} char={char!r}", flush=True)

listener = keyboard.Listener(on_press=lambda k: show("press", k),
                            on_release=lambda k: show("release", k))
listener.start()
deadline = time.time() + DURATION
while time.time() < deadline:
    time.sleep(0.2)
listener.stop()
print("sniff done", flush=True)
