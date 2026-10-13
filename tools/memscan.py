# memscan.py - Cheat-Engine-style value scanner. Run as admin, SOLO only.
import ctypes, struct, time
import numpy as np
import pymem
from ctypes import wintypes as w

PROC = "WOTH2-Win64-Shipping.exe"
pm = pymem.Pymem(PROC)
H = pm.process_handle
k = ctypes.WinDLL("kernel32", use_last_error=True)

TYPES = {"i8": (np.int8, "b", 1), "i16": (np.int16, "h", 2), "i32": (np.int32, "i", 4),
         "i64": (np.int64, "q", 8), "f32": (np.float32, "f", 4)}
tname = "i32"

class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_uint64), ("AllocationBase", ctypes.c_uint64),
                ("AllocationProtect", w.DWORD), ("_a1", w.DWORD),
                ("RegionSize", ctypes.c_uint64), ("State", w.DWORD),
                ("Protect", w.DWORD), ("Type", w.DWORD), ("_a2", w.DWORD)]

k.VirtualQueryEx.argtypes = [w.HANDLE, ctypes.c_uint64, ctypes.POINTER(MBI), ctypes.c_size_t]
k.VirtualQueryEx.restype = ctypes.c_size_t
k.ReadProcessMemory.argtypes = [w.HANDLE, ctypes.c_uint64, ctypes.c_void_p,
                                ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]

def rd(addr, n):
    buf = ctypes.create_string_buffer(n)
    got = ctypes.c_size_t(0)
    k.ReadProcessMemory(H, addr, buf, n, ctypes.byref(got))
    return buf.raw[:got.value]

def rd_val(addr):
    _, fmt, size = TYPES[tname]
    d = rd(addr, size)
    return struct.unpack("<" + fmt, d)[0] if len(d) == size else None

def wr_val(addr, v):
    _, fmt, size = TYPES[tname]
    pm.write_bytes(addr, struct.pack("<" + fmt, float(v) if fmt == "f" else int(v)), size)

def parse(s):
    return float(s) if tname == "f32" else int(s)

def regions():
    addr, out, mbi = 0, [], MBI()
    while addr < 0x7FFFFFFFFFFF:
        if not k.VirtualQueryEx(H, addr, ctypes.byref(mbi), ctypes.sizeof(mbi)):
            break
        if (mbi.State == 0x1000 and mbi.Type == 0x20000
                and mbi.Protect in (0x04, 0x08, 0x40, 0x80)):   # committed, private, writable
            out.append((mbi.BaseAddress, mbi.RegionSize))
        addr = mbi.BaseAddress + mbi.RegionSize
    return out

def first_scan(value):
    npt, _, size = TYPES[tname]
    SLICE, found = 1 << 24, []
    for base_, rsize in regions():
        off = 0
        while off < rsize:
            n = min(SLICE, rsize - off)
            data = rd(base_ + off, n)
            m = len(data) // size * size
            if m:
                arr = np.frombuffer(data[:m], dtype=npt)
                idx = np.flatnonzero(arr == value)
                if idx.size:
                    found.append(np.uint64(base_ + off) + idx.astype(np.uint64) * np.uint64(size))
            off += n
    return np.concatenate(found) if found else np.empty(0, np.uint64)

def next_scan(addrs, value):
    npt, _, size = TYPES[tname]
    addrs = np.sort(addrs)
    pages = addrs >> np.uint64(12)
    uniq, starts = np.unique(pages, return_index=True)
    ends = list(starts[1:]) + [len(addrs)]
    keep = []
    for pg, s, e in zip(uniq, starts, ends):
        data = rd(int(pg) << 12, 4096)
        if len(data) < 4096: continue
        arr = np.frombuffer(data, dtype=npt)
        sub = addrs[s:e]
        pos = ((sub & np.uint64(0xFFF)) // np.uint64(size)).astype(np.int64)
        keep.append(sub[arr[pos] == value])
    return np.concatenate(keep) if keep else np.empty(0, np.uint64)

HELP = """Commands:
  new <n> [type]   first scan for n. type = i16 (try first), i32, i8, i64, f32. Default i32.
  next <n>         keep only addresses that now hold n (same type)
  undo             go back one step
  show             list the remaining addresses
  watch            read-only: log changes for 20s (fire shots while it runs)
  hold <n>         write n to all candidates every 10 ms (Ctrl+C stops)
  holdlog <n>      same, faster, and logs each time the game changes the value
  quit
Always type the number the in-game HUD shows right now.
i8 can produce hundreds of millions of candidates; avoid it unless needed."""
print(HELP)
print("Stay still while a scan runs. The first scan takes up to a minute.")

cands = None
history = []

while True:
    parts = input("> ").split()
    if not parts: continue
    cmd = parts[0].lower()
    try:
        if cmd == "new":
            if len(parts) > 2:
                if parts[2] not in TYPES:
                    print("types:", ", ".join(TYPES)); continue
                tname = parts[2]
            else:
                tname = "i32"
            t = time.time(); cands = first_scan(parse(parts[1])); history = []
            print(f"[{tname}] {len(cands)} candidates ({time.time()-t:.0f}s)")

        elif cmd == "next" and cands is not None:
            t = time.time(); history.append(cands)
            cands = next_scan(cands, parse(parts[1]))
            print(f"[{tname}] {len(cands)} candidates left ({time.time()-t:.0f}s)")
            if len(cands) == 0:
                print("List is empty. Type 'undo' and try the number the HUD shows.")

        elif cmd == "undo":
            if history:
                cands = history.pop()
                print(f"back to {len(cands)} candidates")
            else:
                print("nothing to undo")

        elif cmd == "show" and cands is not None:
            for a in cands[:30]:
                print(f"  {int(a):#x}  value={rd_val(int(a))}")
            if len(cands) > 30: print(f"  ...and {len(cands) - 30} more")

        elif cmd == "watch" and cands is not None:
            if len(cands) == 0 or len(cands) > 200:
                print("Need between 1 and 200 candidates."); continue
            print("Watching 20s (read-only). Fire shots. Ctrl+C to stop early.")
            last = {int(a): None for a in cands}
            t0 = time.time()
            try:
                while time.time() - t0 < 20:
                    for a in last:
                        v = rd_val(a)
                        if v != last[a]:
                            print(f"  {time.time()-t0:5.2f}s {a:#x}: {last[a]} -> {v}")
                            last[a] = v
                    time.sleep(0.005)
            except KeyboardInterrupt:
                pass

        elif cmd in ("hold", "holdlog") and cands is not None:
            if len(cands) == 0:
                print("No candidates to hold. Use 'undo' or start a new scan."); continue
            if len(cands) > 40:
                print("Too many candidates; narrow them down first."); continue
            v = parse(parts[1])
            log = (cmd == "holdlog")
            print(f"Holding {v} on {len(cands)} address(es). Fire shots now. Ctrl+C to stop.")
            t0 = time.time()
            try:
                while True:
                    for a in cands:
                        a = int(a)
                        if log:
                            cur = rd_val(a)
                            if cur != v:
                                print(f"  {time.time()-t0:6.2f}s {a:#x}: game set {cur}, rewriting {v}")
                                wr_val(a, v)
                        else:
                            wr_val(a, v)
                    time.sleep(0.002 if log else 0.01)
            except KeyboardInterrupt:
                print("stopped")

        elif cmd == "quit":
            break
        else:
            print("Run 'new <n>' first, or check the command.")
            print(HELP)
    except Exception as ex:
        print("error:", repr(ex))