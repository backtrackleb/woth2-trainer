# trainer_gui.py - WOTH2 Trainer, made by Backtrackleb. Run as administrator, SOLO ONLY.
# Needs woth2lib.py in the same folder.   pip install pymem
import ctypes, importlib, math, os, queue, struct, threading, time, traceback
from ctypes import wintypes
import tkinter as tk

ctypes.windll.winmm.timeBeginPeriod(1)

# ---------- settings ----------
AUTHOR = "Backtrackleb"
HOTKEYS_ONLY_IN_GAME = True      # hotkeys only act when the game (or this window) is focused
GAME_EXE = "woth2-win64-shipping.exe"

# Keys: F1-F12, INSERT, DELETE, HOME, END, PGUP, PGDN, NUM0-NUM9, SPACE, LCTRL, LSHIFT, LALT, A-Z, 0-9
KEYS = {"speed": "F9", "jump": "F10", "super": "INSERT", "god": "F3", "nofall": "F4",
        "money_small": "F5", "money_big": "F6", "time": "F7", "weather": "F8",
        "fly_up": "SPACE", "fly_down": "LCTRL"}      # fly_up / fly_down are held, not toggles

# ---------- game data (from the Dumper-7 dump; offsets change when the game updates) ----------
OFF_VEL, OFF_MAXSPD, OFF_ACCEL, OFF_GRAVITY = 0xD8, 0x62E0, 0x62C8, 0x6380
GAIT_SPEED = {1500: 300.0, 2000: 500.0}          # accel value -> natural speed (measured)
CAP_DEFAULT, LOCK_TIMEOUT, GRAV_MIN = 800.0, 1.0, 0.03
FLY_GRAVITY = 0.001                               # gravity scale while Superman is on

# fall damage: PlayerHealthComponent+0x140 -> HealthObjectEnergyMap; +0xE0 = {FName, CurveFloat*};
# the curve maps landing speed to damage (2 keys: 13 -> 0.0, 18 -> 1.0); keys at curve+0xA0, 28 bytes each
COMP_EMAP, FALL_SETUP, CURVE_ARR, KEY = 0x140, 0xE0, 0xA0, 28

SOFT = "PlayerEconomy.Resources.SoftCurrency"
MONEY_SMALL, MONEY_BIG = 100_000, 1_000_000

# health: PlayerHealthComponent +0x148 -> root node; node +0x50 = child array; child[0] +0x48 = health (0..1)
HP_ROOT, HP_ARR, HP_NUM, HP_VALUE = 0x148, 0x50, 0x58, 0x48
ONE_F = struct.pack("<f", 1.0)

W_OFFS = {"clouds": (0x358, 0x360), "rain": (0x368, 0x370), "snow": (0x378, 0x380),
          "lightning": (0x388, 0x390), "fog": (0x3A8, 0x3B0)}     # (value, manual-override flag)
MODES = [   # weather scale is 0-10, taken from the game's own presets
    ("Auto",     None),
    ("Clear",    dict(clouds=0.0,  rain=0.0,  snow=0.0,  lightning=0.0,  fog=0.0)),
    ("Overcast", dict(clouds=7.0,  rain=0.0,  snow=0.0,  lightning=0.0,  fog=0.0)),
    ("Fog",      dict(clouds=3.8,  rain=0.0,  snow=0.0,  lightning=0.0,  fog=6.0)),
    ("Rain",     dict(clouds=7.0,  rain=7.0,  snow=0.0,  lightning=2.0,  fog=3.0)),
    ("Storm",    dict(clouds=9.0,  rain=10.0, snow=0.0,  lightning=10.0, fog=4.5)),
    ("Snow",     dict(clouds=6.25, rain=0.0,  snow=6.0,  lightning=0.0,  fog=5.0)),
    ("Blizzard", dict(clouds=10.0, rain=0.0,  snow=10.0, lightning=0.0,  fog=10.0)),
]
SKY_TOD = 0x398          # sunrise is 07:30 and sundown 19:30 in this game
TIMES = [("Auto", None), ("08:00", 800.0), ("10:00", 1000.0), ("12:00", 1200.0),
         ("15:00", 1500.0), ("18:00", 1800.0), ("21:00", 2100.0), ("00:00", 0.0)]

# ---------- shared state (the GUI and hotkeys write it, the worker thread reads it) ----------
S = {"speed_on": False, "speed_mult": 2.0, "jump_on": False, "jump_level": 3.0,
     "super_on": False, "fly_speed": 800.0, "fly_down": 400.0,
     "god_on": False, "nofall_on": False, "health": None,
     "weather_i": 0, "time_i": 0, "money_req": 0, "money": None,
     "status": "waiting_game", "stop": False}
LOGQ = queue.Queue()
def log(msg): LOGQ.put(msg)

# ---------- keyboard / foreground-window helpers (no hooks: polls the physical key state) ----------
_u32, _k32 = ctypes.windll.user32, ctypes.windll.kernel32
_u32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_u32.GetAsyncKeyState.restype = ctypes.c_short
_u32.GetForegroundWindow.restype = wintypes.HWND
_u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                            wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]

_SPECIAL = {"INSERT": 0x2D, "DELETE": 0x2E, "HOME": 0x24, "END": 0x23, "PGUP": 0x21, "PGDN": 0x22,
            "SPACE": 0x20, "LCTRL": 0xA2, "RCTRL": 0xA3, "LSHIFT": 0xA0, "RSHIFT": 0xA1, "LALT": 0xA4}
def vk(name):
    n = name.strip().upper()
    if n in _SPECIAL: return _SPECIAL[n]
    if len(n) == 1 and (n.isalpha() or n.isdigit()): return ord(n)
    if n.startswith("NUM") and n[3:].isdigit(): return 0x60 + int(n[3:])
    if n.startswith("F") and n[1:].isdigit() and 1 <= int(n[1:]) <= 12: return 0x6F + int(n[1:])
    raise ValueError(f"Unknown key name in KEYS: {name!r}")

def key_down(code):
    return bool(_u32.GetAsyncKeyState(code) & 0x8000)

def hotkeys_allowed():
    if not HOTKEYS_ONLY_IN_GAME:
        return True
    try:
        hwnd = _u32.GetForegroundWindow()
        pid = wintypes.DWORD(0)
        _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            return True                               # the trainer window itself
        h = _k32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return True                               # can't tell: don't lock the user out
        buf, n = ctypes.create_unicode_buffer(520), wintypes.DWORD(520)
        okq = _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
        _k32.CloseHandle(h)
        if not okq:
            return True
        return os.path.basename(buf.value).lower() == GAME_EXE
    except Exception:
        return True

def flip(key, label):
    S[key] = not S[key]
    log(f"{label}: {'ON' if S[key] else 'OFF'}")

ACTIONS = {
    "speed":       lambda: flip("speed_on", "Speed boost"),
    "jump":        lambda: flip("jump_on", "High jump"),
    "super":       lambda: flip("super_on", "Superman"),
    "god":         lambda: flip("god_on", "Max health"),
    "nofall":      lambda: flip("nofall_on", "No fall damage"),
    "money_small": lambda: S.__setitem__("money_req", MONEY_SMALL),
    "money_big":   lambda: S.__setitem__("money_req", MONEY_BIG),
    "time":        lambda: S.__setitem__("time_i", (S["time_i"] + 1) % len(TIMES)),
    "weather":     lambda: S.__setitem__("weather_i", (S["weather_i"] + 1) % len(MODES)),
}

def hotkey_loop():
    codes = {name: vk(KEYS[name]) for name in ACTIONS}
    was_down = {name: False for name in ACTIONS}
    while not S["stop"]:
        for name, code in codes.items():
            pressed = key_down(code)
            if pressed and not was_down[name] and hotkeys_allowed():
                try: ACTIONS[name]()
                except Exception as ex: log(f"Hotkey {name} failed: {ex!r}")
            was_down[name] = pressed
        time.sleep(0.01)

# ================= worker thread: all memory work =================
def worker():
    try:
        _worker()
    except Exception:
        log("Worker crashed:\n" + traceback.format_exc())

def _worker():
    L = None
    _why = [None]   # woth2_update: show why
    while L is None and not S["stop"]:
        try:
            L = importlib.import_module("woth2lib")
        except (Exception, SystemExit) as _ex:
            _msg = str(_ex) or type(_ex).__name__
            if _msg != _why[0]:
                _why[0] = _msg; log("Cannot connect: " + _msg)
            S["status"] = "waiting_game"
            time.sleep(2.0)
    if L is None:
        return
    pm, base, ok, rb, rp, ri, fname = L.pm, L.base, L.ok, L.rb, L.rp, L.ri, L.fname

    def get_pawn():
        p = rp(base + L.GWORLD)
        for o in (0x228, 0x38, 0, 0x30, 0x358):
            if not ok(p): return 0
            p = rp(p + o)
        return p if ok(p) else 0

    def get_gmc():
        pawn = get_pawn()
        if not pawn: return 0
        g = rp(pawn + 0x338)
        return g if ok(g) else 0

    idx = None
    env = {"weather": 0, "sky": 0}
    health = {"comp": 0, "leaf": 0}
    curve = {"data": 0, "orig": None, "flat": None}
    orig_flags = {}

    def refresh_env():
        nonlocal idx
        S["status"] = "indexing"
        idx = L.Index()
        w, s = idx.instances("BP_WeatherSetup_C"), idx.instances("BP_SkySetup_C")
        env["weather"], env["sky"] = (w[0] if w else 0), (s[0] if s else 0)
        health["comp"] = health["leaf"] = 0
        S["status"] = "ready"
        log(f"Indexed game objects (weather {'ok' if w else 'missing'}, sky {'ok' if s else 'missing'})")

    def resolve_leaf():
        """character -> PlayerHealthComponent -> root node -> first child (the health leaf)"""
        pawn = get_pawn()
        if not pawn or idx is None: return 0
        comp = health["comp"]
        if not (comp and rp(comp + 0x20) == pawn):        # UObject::Outer must be our character
            comp = 0
            for c in idx.instances("PlayerHealthComponent"):
                if rp(c + 0x20) == pawn:
                    comp = c; break
            health["comp"] = comp
        if not comp: return 0
        root = rp(comp + HP_ROOT)
        if not ok(root): return 0
        data, num = rp(root + HP_ARR), ri(root + HP_NUM)
        if not ok(data) or not (0 < num <= 64): return 0
        leaf = rp(data)
        if not ok(leaf): return 0
        b = rb(leaf + HP_VALUE, 4)
        v = struct.unpack("<f", b)[0] if b else -1.0
        return leaf if 0.0 <= v <= 1.0001 else 0          # sanity check: a real 0..1 health fraction

    # ---- fall damage curve: flatten while "No fall damage" is on, restore afterwards ----
    def curve_patch():
        comp = health["comp"]
        if not comp: return False
        emap = rp(comp + COMP_EMAP)
        cv = rp(emap + FALL_SETUP + 8) if ok(emap) else 0
        if not ok(cv): return False
        data = rp(cv + CURVE_ARR)
        nb = rb(cv + CURVE_ARR + 8, 4)
        num = struct.unpack("<i", nb)[0] if nb else 0
        if not ok(data) or num != 2: return False
        raw = rb(data, KEY * 2)
        if not raw: return False
        if curve["data"] == data and curve["flat"]:            # already ours: just keep it flat
            if raw != curve["flat"]:
                pm.write_bytes(data, curve["flat"], len(curve["flat"]))
            return True
        (t0, v0), (t1, v1) = (struct.unpack_from("<4xff", raw, i * KEY) for i in range(2))
        if not (abs(t0 - 13.0) < 0.01 and abs(t1 - 18.0) < 0.01 and abs(v0) < 1e-3):
            log(f"Fall-damage curve looks different ({t0:g},{v0:g}) ({t1:g},{v1:g}); not touching it. "
                "The game may have been updated.")
            return False
        flat = bytearray(raw)
        for i in range(2):
            flat[i * KEY + 8: i * KEY + 20] = b"\0" * 12        # value + both tangents -> 0
        flat = bytes(flat)
        curve["data"], curve["flat"] = data, flat
        curve["orig"] = raw if abs(v1 - 1.0) < 1e-3 else None
        if curve["orig"] is None:
            log("Curve was already flat (left over from an earlier session); restart the game to restore it.")
        pm.write_bytes(data, flat, len(flat))
        return True

    def curve_restore():
        try:
            if curve["data"] and curve["orig"] and curve["flat"]:
                if rb(curve["data"], len(curve["flat"])) == curve["flat"]:   # still our data, not something else
                    pm.write_bytes(curve["data"], curve["orig"], len(curve["orig"]))
        except Exception:
            pass
        curve["data"], curve["orig"], curve["flat"] = 0, None, None

    def soft_currency_slot():
        if idx is None: return None
        for e in idx.instances("BP_PlayerEconomy_GS_C"):
            dp, n = rp(e + 0x48), ri(e + 0x50)
            if not ok(dp) or not (0 < n <= 256): continue
            for i in range(n):
                raw = rb(dp + i * 0x40, 0x10)
                if not raw: continue
                ki, kn, cur, mx = struct.unpack("<iiii", raw)
                if fname(ki, kn) == SOFT:
                    return dp + i * 0x40 + 8, cur, mx
        return None

    def add_money(amount):
        slot = soft_currency_slot()
        if not slot:
            refresh_env(); slot = soft_currency_slot()
        if not slot:
            log("Could not find the money entry."); return
        addr, cur, mx = slot
        if cur < 0 or mx <= 0 or cur > mx:
            log(f"Unexpected money values (cur={cur}, max={mx}); not writing."); return
        new = min(cur + amount, mx)
        pm.write_int(addr, new)
        log(f"Money {cur:,} -> {new:,}  (open a shop or menu if the HUD hasn't updated)")

    def release_weather():
        w = env["weather"]
        if w:
            for fo, b in orig_flags.items():
                try: pm.write_bytes(w + fo, bytes([b]), 1)
                except Exception: pass
        orig_flags.clear()

    def build_weather(i):
        name, vals = MODES[i]
        if vals is None:
            release_weather(); return []
        w = env["weather"]
        if not w:
            log("Weather actor not found yet."); S["weather_i"] = 0; return []
        for _, (_, fo) in W_OFFS.items():
            if fo not in orig_flags:
                b = rb(w + fo, 1); orig_flags[fo] = b[0] if b else 0
        log(f"Weather: {name}")
        return [(vo, struct.pack("<d", vals[k]), fo) for k, (vo, fo) in W_OFFS.items()]

    # ---- wait for the player, then index ----
    S["status"] = "waiting_player"
    gmc = 0
    while not S["stop"] and not gmc:
        gmc = get_gmc(); time.sleep(0.5)
    if S["stop"]: return
    refresh_env()
    slot = soft_currency_slot()
    if slot: log(f"Connected. Current money: {slot[1]:,}")

    applied_w = applied_t = 0
    weather_writes, tod_packed = [], None
    grav_set = cap_set = sup_was = god_was = nofall_was = False
    moving, natural = False, None
    last_f = last_r = 0
    pending_lock = locked = False
    lock_dir, lock_t = (0.0, 0.0), 0.0
    last_slow = last_gmc = last_input = last_money = last_health = last_idx = last_fg = 0.0
    fg_ok = True
    K_W, K_A, K_S, K_D = 0x57, 0x41, 0x53, 0x44
    K_UP, K_DOWN = vk(KEYS["fly_up"]), vk(KEYS["fly_down"])

    try:
        while not S["stop"]:
            now = time.perf_counter()

            if now - last_gmc > 0.25:                    # new player object = level/map changed
                last_gmc = now
                g = get_gmc()
                if g and g != gmc:
                    gmc = g
                    release_weather()
                    refresh_env()
                    applied_w = applied_t = -1

            if S["money_req"]:
                amt, S["money_req"] = S["money_req"], 0
                try: add_money(amt)
                except Exception as ex: log(f"Money failed: {ex!r}")

            if S["weather_i"] != applied_w:
                weather_writes = build_weather(S["weather_i"])
                applied_w = S["weather_i"]
            if S["time_i"] != applied_t:
                val = TIMES[S["time_i"]][1]
                if val is not None and not env["sky"]:
                    log("Sky actor not found yet."); S["time_i"] = 0; tod_packed = None
                else:
                    tod_packed = None if val is None else struct.pack("<d", val)
                    if val is not None: log(f"Time of day: {TIMES[S['time_i']][0]}")
                applied_t = S["time_i"]

            # ---- health: re-resolve twice a second, also feeds the display ----
            if now - last_health > 0.5:
                last_health = now
                try:
                    leaf = resolve_leaf()
                    if not leaf and (S["god_on"] or S["nofall_on"]) and now - last_idx > 10.0:
                        last_idx = now                   # component may be newer than our object index
                        refresh_env(); leaf = resolve_leaf()
                    health["leaf"] = leaf
                    if leaf:
                        b = rb(leaf + HP_VALUE, 4)
                        S["health"] = struct.unpack("<f", b)[0] * 100.0 if b else None
                    else:
                        S["health"] = None
                    if S["nofall_on"]:
                        curve_patch()                    # keeps it applied across level changes
                except Exception:
                    health["leaf"] = 0
            if S["god_on"] != god_was:
                god_was = S["god_on"]
                if god_was and not health["leaf"]:
                    log("Health object not found yet; it will connect when it appears.")

            # ---- No fall damage: flatten / restore the fall-damage curve ----
            if S["nofall_on"] != nofall_was:
                nofall_was = S["nofall_on"]
                if nofall_was:
                    try:
                        if not health["comp"]: resolve_leaf()
                        patched = curve_patch()
                    except Exception:
                        patched = False
                    if not patched:
                        log("Could not patch the fall-damage curve (stand in the world and try again).")
                        S["nofall_on"] = nofall_was = False
                else:
                    curve_restore()

            holding = False
            try:
                w = env["weather"]
                if weather_writes and w:                 # rewritten every loop so the game can't win
                    holding = True
                    for vo, packed, fo in weather_writes:
                        pm.write_bytes(w + vo, packed, 8)
                        pm.write_bytes(w + fo, b"\x01", 1)
                if tod_packed and env["sky"]:
                    holding = True
                    pm.write_bytes(env["sky"] + SKY_TOD, tod_packed, 8)
                if S["god_on"] and health["leaf"]:       # hold health at 100% (skip if already dead)
                    holding = True
                    b = rb(health["leaf"] + HP_VALUE, 4)
                    v = struct.unpack("<f", b)[0] if b else 0.0
                    if 0.0 < v < 0.9999:
                        pm.write_bytes(health["leaf"] + HP_VALUE, ONE_F, 4)
            except Exception:
                pass

            if now - last_money > 1.0:
                last_money = now
                try:
                    s = soft_currency_slot(); S["money"] = s[1] if s else None
                except Exception:
                    pass

            if now - last_fg > 0.1:                      # is the game focused? (gates the held keys)
                last_fg = now
                fg_ok = hotkeys_allowed()

            if now - last_input > 0.005:
                last_input = now
                f = int(key_down(K_W)) - int(key_down(K_S))
                r = int(key_down(K_D)) - int(key_down(K_A))
                if (f and last_f and f != last_f) or (r and last_r and r != last_r):
                    pending_lock = True                  # direction flip: pause the boost briefly
                if f: last_f = f
                if r: last_r = r
                moving = fg_ok and bool(f or r)

            sup, speed_on, jump_on = S["super_on"], S["speed_on"], S["jump_on"]
            if sup != sup_was:
                sup_was = sup

            try:
                # gravity: Superman overrides High jump
                want_g = FLY_GRAVITY if sup else (max(1.0 / S["jump_level"], GRAV_MIN) if jump_on else None)
                if want_g is not None:
                    pm.write_float(gmc + OFF_GRAVITY, want_g); grav_set = True
                elif grav_set:
                    pm.write_float(gmc + OFF_GRAVITY, 1.0); grav_set = False

                # max-speed cap
                want_c = S["fly_speed"] * 1.5 if sup else (CAP_DEFAULT * S["speed_mult"] if speed_on else None)
                if want_c is not None:
                    pm.write_float(gmc + OFF_MAXSPD, max(want_c, CAP_DEFAULT)); cap_set = True
                elif cap_set:
                    pm.write_float(gmc + OFF_MAXSPD, CAP_DEFAULT); cap_set = False

                # vertical: Superman steers it
                if sup:
                    holding = True
                    up = fg_ok and key_down(K_UP)
                    down = fg_ok and key_down(K_DOWN)
                    vz_t = S["fly_speed"] if up else (-S["fly_down"] if down else 0.0)
                    pm.write_bytes(gmc + OFF_VEL + 16, struct.pack("<d", vz_t), 8)

                # horizontal: Superman or the speed boost, never both
                target = None
                if sup:
                    target = S["fly_speed"]
                elif speed_on and moving:
                    if now - last_slow > 0.05:
                        last_slow = now
                        natural = GAIT_SPEED.get(round(pm.read_float(gmc + OFF_ACCEL)))
                    if natural:
                        target = natural * S["speed_mult"]
                if moving and target:
                    vx, vy, _vz = struct.unpack("<ddd", pm.read_bytes(gmc + OFF_VEL, 24))
                    cur = math.hypot(vx, vy)
                    if cur < 20.0:
                        last_f = last_r = 0
                        locked = pending_lock = False
                    else:
                        if pending_lock:
                            lock_dir = (vx / cur, vy / cur)
                            lock_t, locked, pending_lock = now, True, False
                        if locked and (vx * lock_dir[0] + vy * lock_dir[1] < 0
                                       or now - lock_t > LOCK_TIMEOUT):
                            locked = False
                        if not locked and cur < target * 0.999:
                            k = target / cur
                            pm.write_bytes(gmc + OFF_VEL, struct.pack("<dd", vx * k, vy * k), 16)
            except Exception:
                pass

            time.sleep(0 if (holding or ((speed_on or sup) and moving)) else 0.003)
    finally:
        try:
            release_weather()
            curve_restore()
            g = get_gmc()
            if g:
                pm.write_float(g + OFF_GRAVITY, 1.0)
                pm.write_float(g + OFF_MAXSPD, CAP_DEFAULT)
        except Exception:
            pass

# ================= GUI =================
BG, CARD, BORDER = "#0f1117", "#171a23", "#262b3a"
TEXT, MUTED = "#e6e8ee", "#8a90a2"
GREEN, GREY, AMBER, BLUE = "#22c55e", "#3a3f4f", "#f59e0b", "#3b82f6"
STATUS = {"waiting_game": ("Waiting for game...", AMBER),
          "waiting_player": ("Load into the world...", AMBER),
          "indexing": ("Indexing game objects...", AMBER),
          "ready": ("Connected", GREEN)}

def rrect(c, x1, y1, x2, y2, r, **kw):
    pts = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2,
           x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)

class Switch(tk.Canvas):
    W, H = 46, 24
    def __init__(self, parent, command):
        super().__init__(parent, width=self.W, height=self.H, bg=CARD,
                         highlightthickness=0, cursor="hand2")
        self.command, self.on, self.enabled = command, False, True
        self.bind("<Button-1>", lambda e: self.enabled and self.command())
        self.draw()
    def draw(self):
        self.delete("all")
        col = ("#2a2e3a" if not self.enabled else GREEN if self.on else GREY)
        rrect(self, 1, 1, self.W - 1, self.H - 1, 11, fill=col, outline="")
        x = self.W - 13 if self.on else 13
        self.create_oval(x - 9, 3, x + 9, self.H - 3,
                         fill="#ffffff" if self.enabled else "#6b7080", outline="")
    def set(self, on, enabled=True):
        if (on, enabled) != (self.on, self.enabled):
            self.on, self.enabled = on, enabled
            self.draw()

class Slider(tk.Canvas):
    def __init__(self, parent, lo, hi, value, command, step=0.5):
        super().__init__(parent, width=280, height=22, bg=CARD, highlightthickness=0, cursor="hand2")
        self.lo, self.hi, self.value, self.command, self.step = lo, hi, value, command, step
        self.bind("<Button-1>", self.drag); self.bind("<B1-Motion>", self.drag)
        self.bind("<Configure>", lambda e: self.draw())
    def width(self): return max(self.winfo_width(), 60)
    def draw(self):
        self.delete("all")
        w, y = self.width(), 11
        x = 10 + (self.value - self.lo) / (self.hi - self.lo) * (w - 20)
        self.create_line(10, y, w - 10, y, width=4, fill="#2b3040", capstyle="round")
        self.create_line(10, y, x, y, width=4, fill=GREEN, capstyle="round")
        self.create_oval(x - 8, y - 8, x + 8, y + 8, fill="#ffffff", outline="")
    def drag(self, e):
        f = min(max((e.x - 10) / (self.width() - 20), 0.0), 1.0)
        v = round((self.lo + f * (self.hi - self.lo)) / self.step) * self.step
        self.value = min(max(v, self.lo), self.hi)
        self.draw(); self.command(self.value)

class Btn(tk.Label):
    def __init__(self, parent, text, command, bg=BLUE, hover="#5b9bff"):
        super().__init__(parent, text=text, bg=bg, fg="#ffffff", font=("Segoe UI", 10, "bold"),
                         padx=14, pady=8, cursor="hand2")
        self.bind("<Button-1>", lambda e: command())
        self.bind("<Enter>", lambda e: self.config(bg=hover))
        self.bind("<Leave>", lambda e: self.config(bg=bg))

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"WOTH2 Trainer - by {AUTHOR}")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.build()
        self.update_idletasks()
        self.geometry(f"480x{self.winfo_reqheight()}")
        self.refresh()

    def card(self, title):
        outer = tk.Frame(self, bg=BG); outer.pack(fill="x", padx=16, pady=(10, 0))
        tk.Label(outer, text=title.upper(), bg=BG, fg=MUTED,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))
        box = tk.Frame(outer, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        box.pack(fill="x")
        return box

    def toggle_row(self, box, title, hotkey, command, sliders=None, hint=None, first=False):
        """sliders: list of (state_key, lo, hi, step, format[, label])"""
        sliders = sliders or []
        if not first: tk.Frame(box, bg=BORDER, height=1).pack(fill="x")
        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x", padx=14, pady=(12, 4 if (sliders or hint) else 12))
        tk.Label(row, text=title, bg=CARD, fg=TEXT, font=("Segoe UI", 11, "bold")).pack(side="left")
        tk.Label(row, text=hotkey, bg=CARD, fg=MUTED, font=("Segoe UI", 9)).pack(side="left", padx=8)
        sw = Switch(row, command); sw.pack(side="right")
        for n, (key, lo, hi, step, fmt, *lab) in enumerate(sliders):
            last = (n == len(sliders) - 1) and not hint
            r2 = tk.Frame(box, bg=CARD); r2.pack(fill="x", padx=14, pady=(0, 12 if last else 4))
            if lab:
                tk.Label(r2, text=lab[0], bg=CARD, fg=MUTED, width=9, anchor="w",
                         font=("Segoe UI", 9)).pack(side="left")
            val = tk.Label(r2, text=fmt.format(S[key]), bg=CARD, fg=TEXT, width=6, anchor="e",
                           font=("Segoe UI", 10, "bold"))
            val.pack(side="right")
            def changed(v, key=key, fmt=fmt, val=val):
                S[key] = v; val.config(text=fmt.format(v))
            Slider(r2, lo, hi, S[key], changed, step).pack(side="left", fill="x", expand=True)
        self.last_hint = None
        if hint:
            self.last_hint = tk.Label(box, text=hint, bg=CARD, fg=MUTED, font=("Segoe UI", 8),
                                      anchor="w", justify="left", wraplength=420)
            self.last_hint.pack(fill="x", padx=14, pady=(0, 10))
        return sw

    def chips(self, box, names, key):
        wrap = tk.Frame(box, bg=CARD); wrap.pack(fill="x", padx=10, pady=8)
        out = []
        for i, name in enumerate(names):
            c = tk.Label(wrap, text=name, bg=GREY, fg=TEXT, font=("Segoe UI", 9, "bold"),
                         pady=7, cursor="hand2")
            c.grid(row=i // 4, column=i % 4, padx=4, pady=4, sticky="ew")
            c.bind("<Button-1>", lambda e, i=i: S.__setitem__(key, i))
            out.append(c)
        for col in range(4): wrap.columnconfigure(col, weight=1, uniform="c")
        return out

    def build(self):
        hdr = tk.Frame(self, bg=BG); hdr.pack(fill="x", padx=16, pady=(16, 0))
        tk.Label(hdr, text="WOTH2", bg=BG, fg=TEXT, font=("Segoe UI", 18, "bold")).pack(side="left")
        tk.Label(hdr, text=" TRAINER", bg=BG, fg=GREEN, font=("Segoe UI", 18, "bold")).pack(side="left")
        self.status = tk.Label(hdr, text="", font=("Segoe UI", 9, "bold"), padx=8, pady=3)
        self.status.pack(side="right")
        tk.Label(self, text=f"Made by {AUTHOR}  \u00b7  Single-player only", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=16)

        c = self.card("Movement")
        self.sw_speed = self.toggle_row(c, "Speed boost", KEYS["speed"], ACTIONS["speed"],
                                        sliders=[("speed_mult", 1.5, 10.0, 0.5, "x{:.1f}")], first=True)
        self.sw_jump = self.toggle_row(c, "High jump", KEYS["jump"], ACTIONS["jump"],
                                       sliders=[("jump_level", 1.0, 20.0, 0.5, "x{:.1f}")])
        self.sw_super = self.toggle_row(
            c, "Superman", KEYS["super"], ACTIONS["super"],
            sliders=[("fly_speed", 200.0, 3000.0, 50.0, "{:.0f}", "Fly speed"),
                     ("fly_down", 100.0, 3000.0, 50.0, "{:.0f}", "Descend")],
            hint=f"Hold {KEYS['fly_up']} to rise, {KEYS['fly_down']} to descend, W/A/S/D to fly. "
                 "Release to hover. Turn on No fall damage so landings are harmless.")

        c = self.card("Survival")
        self.sw_god = self.toggle_row(c, "Max health", KEYS["god"], ACTIONS["god"],
                                      hint="Health: -", first=True)
        self.lbl_health = self.last_hint
        self.sw_nofall = self.toggle_row(
            c, "No fall damage", KEYS["nofall"], ACTIONS["nofall"],
            hint="Falls and hard landings can't hurt you, at any speed. Animals and bullets still do. "
                 "Restored when you turn it off or close the trainer.")

        c = self.card("Economy")
        row = tk.Frame(c, bg=CARD); row.pack(fill="x", padx=14, pady=12)
        tk.Label(row, text="Balance", bg=CARD, fg=MUTED, font=("Segoe UI", 9)).pack(side="left")
        self.lbl_money = tk.Label(row, text="-", bg=CARD, fg=TEXT, font=("Segoe UI", 12, "bold"))
        self.lbl_money.pack(side="left", padx=8)
        Btn(row, f"+1,000,000  {KEYS['money_big']}", ACTIONS["money_big"]).pack(side="right")
        Btn(row, f"+100,000  {KEYS['money_small']}", ACTIONS["money_small"]).pack(side="right", padx=8)

        c = self.card(f"Weather  -  {KEYS['weather']} cycles")
        self.weather_chips = self.chips(c, [m[0] for m in MODES], "weather_i")
        c = self.card(f"Time of day  -  {KEYS['time']} cycles")
        self.time_chips = self.chips(c, [t[0] for t in TIMES], "time_i")

        c = self.card("Log")
        self.log = tk.Text(c, height=5, bg=CARD, fg=MUTED, bd=0, highlightthickness=0,
                           font=("Consolas", 9), wrap="word", state="disabled")
        self.log.pack(fill="x", padx=10, pady=8)
        tk.Label(self, text=f"WOTH2 Trainer by {AUTHOR}  \u00b7  Back up your save before using the money buttons.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=16, pady=(8, 12))

    def drain_log(self):
        lines = []
        while True:
            try: lines.append(LOGQ.get_nowait())
            except queue.Empty: break
        if lines:
            self.log.config(state="normal")
            for l in lines: self.log.insert("end", l + "\n")
            n = int(self.log.index("end-1c").split(".")[0])
            if n > 200: self.log.delete("1.0", f"{n - 200}.0")
            self.log.see("end"); self.log.config(state="disabled")

    def refresh(self):
        self.sw_speed.set(S["speed_on"]); self.sw_jump.set(S["jump_on"]); self.sw_super.set(S["super_on"])
        self.sw_god.set(S["god_on"]); self.sw_nofall.set(S["nofall_on"])
        for chips, key in ((self.weather_chips, "weather_i"), (self.time_chips, "time_i")):
            for i, ch in enumerate(chips):
                on = (i == S[key])
                ch.config(bg=GREEN if on else GREY, fg="#04110a" if on else TEXT)
        text, col = STATUS.get(S["status"], ("...", AMBER))
        self.status.config(text=f" {text} ", bg=col, fg="#04110a")
        self.lbl_money.config(text=f"{S['money']:,}" if S["money"] is not None else "-")
        h = S["health"]
        self.lbl_health.config(text="Health: not found yet" if h is None else f"Health: {h:.0f}%")
        self.drain_log()
        self.after(100, self.refresh)

    def on_close(self):
        S["stop"] = True
        WORKER.join(timeout=3)
        ctypes.windll.winmm.timeEndPeriod(1)
        self.destroy()

if __name__ == "__main__":
    if not ctypes.windll.shell32.IsUserAnAdmin():
        log("Not running as administrator: the trainer can't open the game. Right-click > Run as administrator.")
    WORKER = threading.Thread(target=worker, daemon=True)
    WORKER.start()
    threading.Thread(target=hotkey_loop, daemon=True).start()
    App().mainloop()