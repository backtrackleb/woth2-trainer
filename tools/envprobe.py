# envprobe.py - run as admin, SOLO only, standing in the world.
import struct, time
import woth2lib as lib
from woth2lib import pm, rb, rp

print("Indexing game objects...")
idx = lib.Index()

def rd_f(a): b = rb(a, 4); return struct.unpack("<f", b)[0] if b else None
def rd_d(a): b = rb(a, 8); return struct.unpack("<d", b)[0] if b else None
def rd_b(a): b = rb(a, 1); return b[0] if b else None
def wr_f(a, v): pm.write_bytes(a, struct.pack("<f", v), 4)
def wr_d(a, v): pm.write_bytes(a, struct.pack("<d", v), 8)
def wr_b(a, v): pm.write_bytes(a, bytes([1 if v else 0]), 1)

times    = idx.instances("BP_GameTimeSubsystem", prefix=True)
weathers = idx.instances("BP_WeatherSubsystem", prefix=True)
skies    = idx.instances("BP_SkySetup_C")
wsetups  = idx.instances("BP_WeatherSetup_C")

print(f"time subsystems : {[(hex(o), idx.name(o)) for o in times]}")
print(f"weather subsys  : {[(hex(o), idx.name(o)) for o in weathers]}")
print(f"sky actors      : {[hex(o) for o in skies]}")
print(f"weather actors  : {[hex(o) for o in wsetups]}")

# name: (value offset, manual-override flag offset) on the Ultra Dynamic Weather actor
WEATHER = {
    "clouds":    (0x358, 0x360),
    "rain":      (0x368, 0x370),
    "snow":      (0x378, 0x380),
    "lightning": (0x388, 0x390),
    "wind":      (0x398, 0x3A0),
    "fog":       (0x3A8, 0x3B0),
    "dust":      (0x3B8, 0x3C0),
    "wet":       (0x3C8, 0x3D0),
}

orig = {}                       # original speed floats, so we can restore them
def remember(key, val): orig.setdefault(key, val)

def show():
    for t in times:
        print(f"\n[{idx.name(t)} @ {t:#x}]")
        print(f"  start={rd_f(t+0x68)} daySpeed={rd_f(t+0x6C)} nightSpeed={rd_f(t+0x70)} "
              f"sunrise={rd_f(t+0x74)} sundown={rd_f(t+0x78)} freeze={rd_b(t+0x7C)}")
        remember((t, 0x6C), rd_f(t + 0x6C)); remember((t, 0x70), rd_f(t + 0x70))
    for w in weathers:
        sky_ptr, wea_ptr = rp(w + 0x2F0), rp(w + 0x288)
        print(f"\n[{idx.name(w)} @ {w:#x}] dynamicSky={sky_ptr:#x} dynamicWeather={wea_ptr:#x}")
        print(f"  sky pointer is a known sky actor: {sky_ptr in skies}; "
              f"weather pointer is a known weather actor: {wea_ptr in wsetups}")
    for s in skies:
        print(f"\n[sky @ {s:#x}] Time_of_Day={rd_d(s+0x398)}  (compare with your HUD clock) "
              f"animate={rd_b(s+0x660)} dayLength={rd_d(s+0x668)}")
    for w in wsetups:
        print(f"\n[weather actor @ {w:#x}]")
        for name, (v, f) in WEATHER.items():
            print(f"  {name:10s} = {rd_d(w + v)}   manual_override = {rd_b(w + f)}")

def hold_double(addr, value, seconds):
    t0 = time.time()
    try:
        while time.time() - t0 < seconds:
            wr_d(addr, value)
            time.sleep(0.005)
    except KeyboardInterrupt:
        pass

def hold_weather(name, value, seconds):
    for w in wsetups:
        vo, fo = WEATHER[name]
        old_flag = rd_b(w + fo)
        wr_b(w + fo, True)                          # take manual control of this effect
        print(f"{name}: override on (was {old_flag}), holding {value} for {seconds:.0f}s. Look at the sky.")
        t0 = time.time()
        try:
            while time.time() - t0 < seconds:
                wr_b(w + fo, True)
                wr_d(w + vo, value)
                time.sleep(0.005)
        except KeyboardInterrupt:
            pass
        wr_b(w + fo, bool(old_flag))                # give control back to the game
        print(f"{name}: released")

show()
print("""
Commands:
  show
  rain|snow|fog|clouds|lightning|wind|dust|wet <0-1> [seconds]   force a weather effect (default 15 s)
  tod <0-2400> [seconds]     hold the sky's Time_of_Day (1830 = 6:30 PM)
  freeze | unfreeze          toggle m_configFreezeTime on the time subsystem
  speed <x>                  scale day/night speed by x (speed 1 restores)
  quit""")

while True:
    parts = input("> ").split()
    if not parts: continue
    cmd = parts[0].lower()
    try:
        secs = float(parts[2]) if len(parts) > 2 else 15.0
        if cmd == "show":
            show()
        elif cmd in WEATHER and wsetups:
            hold_weather(cmd, float(parts[1]), secs)
        elif cmd == "tod" and skies:
            print("Holding Time_of_Day... watch the sky and the HUD clock.")
            hold_double(skies[0] + 0x398, float(parts[1]), secs)
            print("released")
        elif cmd in ("freeze", "unfreeze"):
            for t in times: wr_b(t + 0x7C, cmd == "freeze")
            print(cmd, "written; check whether the HUD clock stops")
        elif cmd == "speed":
            x = float(parts[1])
            for t in times:
                for off in (0x6C, 0x70):
                    base_val = orig.get((t, off))
                    if base_val is not None: wr_f(t + off, base_val * x)
            print(f"speed x{x} written; watch how fast the HUD clock moves")
        elif cmd == "quit":
            break
        else:
            print("unknown command, or that object was not found")
    except Exception as ex:
        print("error:", repr(ex))

for (t, off), v in orig.items():                   # always restore speeds on exit
    try: wr_f(t + off, v)
    except Exception: pass
print("restored speed values. Bye.")