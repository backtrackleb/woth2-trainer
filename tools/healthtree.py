# healthtree.py - read-only. Run as admin, SOLO, standing in the world at full health.
import struct
import woth2lib as lib
from woth2lib import ok, rb, rp, ri, base, GWORLD, fname

def get_pawn():
    p = rp(base + GWORLD)
    for o in (0x228, 0x38, 0, 0x30, 0x358):
        if not ok(p): return 0
        p = rp(p + o)
    return p if ok(p) else 0

pawn = get_pawn()
print("pawn", hex(pawn))
print("Indexing game objects...")
idx = lib.Index()

def cname(o):
    e = idx.info.get(o)
    return idx.cls_name.get(e[0]) if e else None

# ---- find the PlayerHealthComponent owned by the pawn (UObject::Outer is at +0x20) ----
comps = []
for cls, name in idx.cls_name.items():
    if name and "HealthComponent" in name:
        for o in idx.by_cls[cls]:
            if (idx.name(o) or "").startswith("Default__"): continue
            comps.append((o, name, rp(o + 0x20)))
for o, name, outer in comps[:12]:
    print(f"  {o:#x} {name} outer={outer:#x}{'  <-- yours' if outer == pawn else ''}")
mine = [c for c in comps if c[2] == pawn]
if not mine:
    raise SystemExit("No HealthComponent owned by the pawn. Paste this output to me.")
comp = next((c[0] for c in mine if "Player" in c[1]), mine[0][0])
root = rp(comp + 0x148)
print(f"\nUsing {cname(comp)} @ {comp:#x}   m_rootNode = {root:#x}")
if not ok(root):
    raise SystemExit("m_rootNode is null. Paste this output to me.")

# ---- walk the health object tree ----
seen, tree = set(), []
def walk(obj, depth, path):
    if depth > 6 or obj in seen or not ok(obj): return
    seen.add(obj)
    tree.append((obj, depth, path))
    cn = cname(obj) or ""
    if "HealthObjectNode" in cn:
        data, num = rp(obj + 0x50), ri(obj + 0x58)         # TArray<UHealthObjectBase*> m_healthObjects
        if ok(data) and 0 < num <= 256:
            for i in range(num):
                walk(rp(data + 8 * i), depth + 1, f"{path}/{i}")
walk(root, 0, "root")
print(f"{len(tree)} health objects in the tree\n")

def tag_of(obj):
    b = rb(obj + 0x28, 8)
    return fname(*struct.unpack("<ii", b)) if b else None

def floats(obj, lo=0x28, hi=0x80):
    blob = rb(obj + lo, hi - lo) or b""
    out = {}
    for off in range(0, len(blob) - 3, 4):
        v = struct.unpack_from("<f", blob, off)[0]
        if v == v and 0.0 <= v <= 100000.0:
            out[lo + off] = v
    return out

for obj, depth, path in tree:
    vals = " ".join(f"+{o:#04x}={v:.2f}" for o, v in floats(obj, 0x30, 0x60).items() if v != 0.0)
    print(f"{'  ' * depth}{path}  {cname(obj)}  tag={tag_of(obj)}  @ {obj:#x}\n{'  ' * depth}   {vals}")

def snap():
    return {(obj, off): v for obj, _, _ in tree for off, v in floats(obj).items()}

a = snap()
input("\nNow take a LITTLE damage (step off a low ledge). Note your HUD health, then press Enter...")
b = snap()
drops = [(k, a[k], b[k]) for k in a if k in b and b[k] < a[k] - 0.01]
print(f"\nValues that went DOWN ({len(drops)}):")
for (obj, off), x, y in drops[:40]:
    print(f"  {obj:#x}+{off:#x}  {x:.2f} -> {y:.2f}   {cname(obj)}  tag={tag_of(obj)}")

input("\nNow wait for health to regenerate (or heal), then press Enter...")
c = snap()
back = [(k, y, c[k]) for k, x, y in drops if k in c and c[k] > y + 0.01]
print(f"\nValues that went down and then came back UP ({len(back)}):")
for (obj, off), y, z in back[:30]:
    print(f"  {obj:#x}+{off:#x}  {y:.2f} -> {z:.2f}   {cname(obj)}  tag={tag_of(obj)}")
print("\nDone. Paste all of this, plus what the HUD health said at each step.")