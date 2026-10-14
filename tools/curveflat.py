# curveflat.py - Run as admin, SOLO. Flattens the player's fall-damage curve while running; restores on exit.
import struct, time
import woth2lib as L
from woth2lib import ok, rb, rp, base, GWORLD, pm

HP_ROOT, HP_ARR, HP_VALUE = 0x148, 0x50, 0x48
ARR, KEY = 0xA0, 28            # FRichCurve key array at curve+0xA0, 28 bytes per key

def get_pawn():
    p = rp(base + GWORLD)
    for o in (0x228, 0x38, 0, 0x30, 0x358):
        if not ok(p): return 0
        p = rp(p + o)
    return p if ok(p) else 0

pawn = get_pawn()
if not pawn: raise SystemExit("Stand in the world first.")
print("Indexing game objects...")
idx = L.Index()
comp = next((c for c in idx.instances("PlayerHealthComponent") if rp(c + 0x20) == pawn), 0)
if not comp: raise SystemExit("PlayerHealthComponent not found.")
root = rp(comp + HP_ROOT)
leaf = rp(rp(root + HP_ARR))
emap = rp(comp + 0x140)
curve = rp(emap + 0xE0 + 8)
if not ok(curve): raise SystemExit("Curve pointer invalid.")

data = rp(curve + ARR)
num = struct.unpack("<i", rb(curve + ARR + 8, 4))[0]
if not ok(data) or num != 2: raise SystemExit(f"Unexpected curve layout (num={num}). Not writing.")
orig = rb(data, KEY * num)
(t0, v0), (t1, v1) = (struct.unpack_from("<4xff", orig, i * KEY) for i in range(2))
print(f"curve keys: ({t0:g}, {v0:g}) ({t1:g}, {v1:g})")
if not (abs(t0 - 13.0) < 0.01 and abs(v0) < 1e-3 and abs(t1 - 18.0) < 0.01 and abs(v1 - 1.0) < 1e-3):
    raise SystemExit("Keys are not the expected 13/0 and 18/1. Not writing.")

flat = bytearray(orig)
for i in range(num):
    flat[i * KEY + 8: i * KEY + 20] = b"\0" * 12      # Value, ArriveTangent, LeaveTangent -> 0
flat = bytes(flat)

def health():
    b = rb(leaf + HP_VALUE, 4)
    return struct.unpack("<f", b)[0] * 100.0 if b else None

pm.write_bytes(data, flat, len(flat))
print("Fall-damage curve FLATTENED. Test your landing / tree hit. Ctrl+C restores it.")
last = health()
try:
    while True:
        cur = rb(data, len(flat))
        if cur != flat:
            pm.write_bytes(data, flat, len(flat))
        h = health()
        if h is not None and last is not None and abs(h - last) >= 0.5:
            print(f"health {last:.1f}% -> {h:.1f}%")
        last = h
        time.sleep(0.01)
except KeyboardInterrupt:
    pass
finally:
    try:
        pm.write_bytes(data, orig, len(orig))
        print("Curve restored.")
    except Exception as ex:
        print("Could not restore (game closed?):", ex)