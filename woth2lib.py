# woth2lib.py - shared helpers, keep next to the other scripts
import struct, pymem, pymem.process

PROC = "WOTH2-Win64-Shipping.exe"
GWORLD = 0xB0016B8
GOBJECTS, APPEND_STRING = 0xAE768E0, 0x1399CC0
CHUNK, ISZ, SHIFT, POFF = 0x10000, 0x18, 16, 0x10   # entry layout found by the detector

pm = pymem.Pymem(PROC)
base = pymem.process.module_from_name(pm.process_handle, PROC).lpBaseOfDll

def ok(p): return 0x10000 < p < 0x7FFFFFFFFFFF
def rb(a, n):
    try: return pm.read_bytes(a, n)
    except Exception: return None
def rp(a):
    b = rb(a, 8); return struct.unpack("<Q", b)[0] if b else 0
def ri(a):
    b = rb(a, 4); return struct.unpack("<i", b)[0] if b else 0
def read_big(addr, size, step=0x10000):
    out = bytearray()
    for off in range(0, size, step):
        n = min(step, size - off)
        part = rb(addr + off, n)
        out += part if part is not None else b"\0" * n
    return bytes(out)

def _find_namepool():
    code = rb(base + APPEND_STRING, 0x400)
    if not code: return None, None
    for i in range(len(code) - 7):
        if code[i] in (0x48, 0x4C) and code[i+1] in (0x8D, 0x8B) and (code[i+2] & 0xC7) == 0x05:
            cand = base + APPEND_STRING + i + 7 + struct.unpack_from("<i", code, i + 3)[0]
            for blk_off in (0x10, 0x8, 0x18, 0x20, 0x0):
                blk0 = rp(cand + blk_off)
                if not ok(blk0): continue
                h = rb(blk0, 6)
                if h and (struct.unpack_from("<H", h)[0] >> 6) == 4 and h[2:6] == b"None":
                    return cand, blk_off
    return None, None

_pool, _blk = _find_namepool()
if not _pool:
    raise SystemExit("The name table was not found: the game was probably updated, so the saved offsets are out of date. Re-run Dumper-7 on the current game, then run woth2_update.py")

_names = {}
def fname(idx, num=0):
    key = (idx, num)
    if key in _names: return _names[key]
    s = None
    if 0 <= idx < 0x10000000:
        b = rp(_pool + _blk + 8 * (idx >> 16))
        if ok(b):
            h = rb(b + 2 * (idx & 0xFFFF), 2)
            if h:
                hv = struct.unpack("<H", h)[0]
                ln, wide = hv >> 6, hv & 1
                if 0 < ln <= 1024:
                    raw = rb(b + 2 * (idx & 0xFFFF) + 2, ln * (2 if wide else 1))
                    if raw:
                        s = raw.decode("utf-16-le" if wide else "latin-1", "replace")
                        if num: s += f"_{num - 1}"
    _names[key] = s
    return s

class Index:
    """Snapshot of every UObject: address -> (class, name index, name number)."""
    def __init__(self): self.scan()

    def scan(self):
        objs = rp(base + GOBJECTS)
        num, nch = ri(base + GOBJECTS + 0x14), ri(base + GOBJECTS + 0x1C)
        self.info = {}
        for c in range(nch):
            cp = rp(objs + 8 * c) + SHIFT
            cnt = min(CHUNK, num - c * CHUNK)
            if not ok(cp) or cnt <= 0: continue
            blob = read_big(cp, cnt * ISZ)
            for i in range(cnt):
                o = struct.unpack_from("<Q", blob, i * ISZ + POFF)[0]
                if not ok(o): continue
                h = rb(o + 0x10, 0x10)
                if h: self.info[o] = struct.unpack_from("<Qii", h, 0)
        self.by_cls = {}
        for o, (cls, _, _) in self.info.items():
            self.by_cls.setdefault(cls, []).append(o)
        self.cls_name = {c: self.name(c) for c in self.by_cls}

    def name(self, o):
        e = self.info.get(o)
        return fname(e[1], e[2]) if e else None

    def instances(self, nm, prefix=False):
        out = []
        for c, n in self.cls_name.items():
            if n and (n.startswith(nm) if prefix else n == nm):
                out += [o for o in self.by_cls[c]
                        if not (self.name(o) or "").startswith("Default__")]
        return out