#!/usr/bin/env python3
"""
woth2_update.py - run this after a game update, once you have re-dumped the game with Dumper-7.

  python woth2_update.py                   (finds the newest dump under C:\\Dumper-7 and the trainer files next to this script)
  python woth2_update.py --dump "C:\\Dumper-7\\<folder>" --dir "C:\\woth2-trainer"
  python woth2_update.py --dry-run         (only report, change nothing)

Why it exists: the trainer reads the game through fixed offsets. A game update moves them (the engine ones nearly always,
the game-specific ones sometimes). This checks every offset the trainer uses against the NEW dump, BY NAME, and rewrites
the ones it can verify (keeping a backup of every file it touches). It never touches the game, and never guesses:
anything it cannot verify is listed under "NEEDS ATTENTION" instead of being changed.
"""
import argparse
import glob
import os
import re
import shutil
import sys
import time

OLD_ENGINE = {"GWorld": 0x0AFF5238, "GObjects": 0x0AE6A460, "AppendString": 0x01398DA0}

# (label, field name, class test, offset the trainer currently assumes) - checked by NAME against the new dump
NAME_CHECKS = [
    ("UWorld.OwningGameInstance", "OwningGameInstance", lambda c: c == "UWorld", 0x228, "chain0"),
    ("UGameInstance.LocalPlayers", "LocalPlayers", lambda c: c == "UGameInstance", 0x38, "chain1"),
    ("UPlayer.PlayerController", "PlayerController", lambda c: c in ("UPlayer", "ULocalPlayer"), 0x30, "chain3"),
    ("APlayerController.AcknowledgedPawn", "AcknowledgedPawn", lambda c: c == "APlayerController", 0x358, "chain4"),
    ("ACharacter.CharacterMovement", "CharacterMovement", lambda c: c == "ACharacter", 0x338, "charmove"),
    ("GMC MaxDesiredSpeed", "MaxDesiredSpeed", lambda c: "GMC" in c, 0x62E0, "maxspd"),
    ("GMC InputAccelerationGrounded", "InputAccelerationGrounded", lambda c: "GMC" in c, 0x62C8, "accel"),
    ("GMC GravityScale", "GravityScale", lambda c: "GMC" in c, 0x6380, "gravity"),
    ("PlayerHealthComponent.m_rootNode", "m_rootNode", lambda c: "PlayerHealth" in c, 0x148, "hproot"),
    ("PlayerEconomy.m_resourcesMap", "m_resourcesMap", lambda c: "PlayerEconomy" in c, 0x48, "econ"),
]
# verified only (we do not know these fields' names): a class must still have these TYPES at these offsets
LAYOUT_CHECKS = [
    ("Weather actor: decimal values", lambda c: "WeatherSetup" in c, [0x358, 0x368, 0x378, 0x388, 0x3A8], "double"),
    ("Weather actor: override flags", lambda c: "WeatherSetup" in c, [0x360, 0x370, 0x380, 0x390, 0x3B0], "bool"),
    ("Sky actor: time of day", lambda c: "SkySetup" in c, [0x398], "double"),
]

CLASS_RE = re.compile(r"^\s*(?:class|struct)\s+(?:alignas\(\d+\)\s+)?(\w+)\b(?!.*;\s*$)")
FIELD_RE = re.compile(r"^\s*(?P<type>.+?)\s+\**(?P<name>\w+)(?:\[[^\]]*\])?\s*;\s*//\s*(?P<off>0x[0-9A-Fa-f]+)\(0x[0-9A-Fa-f]+\)")
ENGINE_RE = re.compile(r"constexpr\s+int32\s+(\w+)\s*=\s*(0x[0-9A-Fa-f]+)")


# --------------------------------------------------------------------------------------------- reading the dump
def find_dump(explicit):
    if explicit:
        p = explicit
        for sub in ("", "CppSDK", os.path.join("CppSDK", "SDK")):
            q = os.path.join(p, sub)
            if os.path.isfile(os.path.join(q, "Basic.hpp")):
                return q
        return None
    found = []
    for root in (r"C:\Dumper-7", os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        for pat in ("*/CppSDK/SDK/Basic.hpp", "CppSDK/SDK/Basic.hpp", "*/*/CppSDK/SDK/Basic.hpp"):
            found += glob.glob(os.path.join(root, pat))
    found = sorted(set(found), key=os.path.getmtime, reverse=True)
    return os.path.dirname(found[0]) if found else None


def read_engine_offsets(sdk):
    out = {}
    with open(os.path.join(sdk, "Basic.hpp"), encoding="utf-8", errors="replace") as f:
        txt = f.read()
    for m in ENGINE_RE.finditer(txt):
        out[m.group(1)] = int(m.group(2), 16)
    return out


def parse_fields(sdk):
    """-> {class: {offset: (name, type)}}  and  {field name: [(class, offset)]}"""
    classes, by_name = {}, {}
    for path in glob.glob(os.path.join(sdk, "*_classes.hpp")) + glob.glob(os.path.join(sdk, "*_structs.hpp")):
        cur = None
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if "// 0x" in line:
                    m = FIELD_RE.match(line)
                    if m and cur:
                        off = int(m.group("off"), 16)
                        classes[cur][off] = (m.group("name"), m.group("type").strip())
                        by_name.setdefault(m.group("name"), []).append((cur, off))
                    continue
                s = line.lstrip()
                if s.startswith(("class ", "struct ")):
                    m = CLASS_RE.match(line)
                    if m:
                        cur = m.group(1)
                        classes.setdefault(cur, {})
    return classes, by_name


# --------------------------------------------------------------------------------------------- checking
def resolve(by_name, field, test, old):
    cands = [(c, o) for c, o in by_name.get(field, []) if test(c)]
    if not cands:
        return "missing", None, []
    if any(o == old for _, o in cands):
        return "ok", old, cands
    offs = sorted({o for _, o in cands})
    if len(offs) == 1:
        return "changed", offs[0], cands
    return "ambiguous", None, cands


def check_layout(classes, test, offsets, kind):
    cls = [c for c in classes if test(c)]
    if not cls:
        return "class missing", []
    ok_any = []
    for c in cls:
        good = 0
        for o in offsets:
            e = classes[c].get(o)
            t = e[1] if e else ""
            if (kind == "double" and t == "double") or (kind == "bool" and re.search(r"\b(bool|uint8|int8|char)\b", t)):
                good += 1
        ok_any.append((c, good))
    best = max(ok_any, key=lambda x: x[1])
    return ("ok" if best[1] == len(offsets) else "changed"), ok_any


# --------------------------------------------------------------------------------------------- patching text
class Patcher:
    def __init__(self, path, dry):
        self.path, self.dry = path, dry
        self.text = open(path, encoding="utf-8").read() if os.path.isfile(path) else None
        self.orig = self.text
        self.log = []

    def sub(self, label, pattern, repl, flags=re.M):
        if self.text is None:
            self.log.append((label, "file not found"))
            return False
        new, n = re.subn(pattern, repl, self.text, count=1, flags=flags)
        if n == 0:
            self.log.append((label, "pattern not found (the file differs from what I expect): change it by hand"))
            return False
        changed = new != self.text
        self.text = new
        self.log.append((label, "updated" if changed else "already current"))
        return changed

    def save(self):
        if self.text is None or self.text == self.orig:
            return False
        if not self.dry:
            shutil.copy2(self.path, self.path + ".bak_" + time.strftime("%Y%m%d_%H%M%S"))
            with open(self.path, "w", encoding="utf-8", newline="") as f:
                f.write(self.text)
        return True


def hx(v):
    return "0x%X" % v


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", help="the Dumper-7 output folder (default: the newest one under C:\\Dumper-7)")
    ap.add_argument("--dir", default=None, help="folder holding woth2lib.py and trainer_gui.py (default: next to this script)")
    ap.add_argument("--dry-run", action="store_true", help="report only; change nothing")
    a = ap.parse_args(argv)
    here = a.dir or os.path.dirname(os.path.abspath(__file__))

    sdk = find_dump(a.dump)
    if not sdk:
        print("I can't find a Dumper-7 dump (looking for CppSDK\\SDK\\Basic.hpp under C:\\Dumper-7).\n"
              "Re-dump the CURRENT game with Dumper-7 first, or pass --dump \"<folder>\".")
        return 2
    age = (time.time() - os.path.getmtime(os.path.join(sdk, "Basic.hpp"))) / 86400
    print(f"Using dump: {sdk}\n  (written {age:.1f} days ago{'; is that from AFTER the game update?' if age > 3 else ''})\n")

    eng = read_engine_offsets(sdk)
    need = ("GWorld", "GObjects", "AppendString")
    if not all(k in eng for k in need):
        print("Basic.hpp does not contain GWorld / GObjects / AppendString. Is this a complete Dumper-7 dump?")
        return 2
    classes, by_name = parse_fields(sdk)
    print(f"Read {len(classes):,} classes/structs from the dump.\n")

    attention, patched_files = [], []
    lib = Patcher(os.path.join(here, "woth2lib.py"), a.dry_run)
    gui = Patcher(os.path.join(here, "trainer_gui.py"), a.dry_run)

    # ---- engine offsets (module-relative) ----
    print("ENGINE OFFSETS (these move with every game build)")
    for k in need:
        old, new = OLD_ENGINE[k], eng[k]
        print(f"  {k:13} trainer has {hx(old):>11}   new dump says {hx(new):>11}   {'same' if old == new else 'CHANGED'}")
    lib.sub("GWORLD", r"^(GWORLD\s*=\s*)0x[0-9A-Fa-f]+", lambda m: m.group(1) + hx(eng["GWorld"]))
    lib.sub("GOBJECTS / APPEND_STRING", r"^(GOBJECTS,\s*APPEND_STRING\s*=\s*)0x[0-9A-Fa-f]+\s*,\s*0x[0-9A-Fa-f]+",
            lambda m: m.group(1) + f"{hx(eng['GObjects'])}, {hx(eng['AppendString'])}")
    # a clear message instead of a silent exit
    lib.sub("clear error message", r"raise SystemExit\(\s*(?:\\?[\"'])Could not locate FNamePool\.(?:\\?[\"'])\s*\)",
            'raise SystemExit("The name table was not found: the game was probably updated, so the saved offsets are out of date. '
            'Re-run Dumper-7 on the current game, then run woth2_update.py")')

    # ---- by-name offsets ----
    print("\nGAME OFFSETS (checked by NAME in the new dump)")
    new_vals = {}
    for label, field, test, old, key in NAME_CHECKS:
        state, new, cands = resolve(by_name, field, test, old)
        if state == "ok":
            print(f"  [ok]       {label:38} {hx(old)}")
            new_vals[key] = old
        elif state == "changed":
            print(f"  [CHANGED]  {label:38} {hx(old)} -> {hx(new)}")
            new_vals[key] = new
        elif state == "ambiguous":
            print(f"  [?]        {label:38} several different offsets: {sorted({hx(o) for _, o in cands})}")
            attention.append(f"{label}: ambiguous in the new dump ({', '.join(f'{c}@{hx(o)}' for c, o in cands[:4])})")
            new_vals[key] = old
        else:
            print(f"  [MISSING]  {label:38} not in the new dump (renamed or removed)")
            attention.append(f"{label}: the field no longer exists under that name")
            new_vals[key] = old

    c = new_vals
    gui.sub("player chain", r"for o in \(0x[0-9A-Fa-f]+, 0x[0-9A-Fa-f]+, 0, 0x[0-9A-Fa-f]+, 0x[0-9A-Fa-f]+\):",
            lambda m: f"for o in ({hx(c['chain0'])}, {hx(c['chain1'])}, 0, {hx(c['chain3'])}, {hx(c['chain4'])}):")
    gui.sub("character movement", r"rp\(pawn \+ 0x[0-9A-Fa-f]+\)", lambda m: f"rp(pawn + {hx(c['charmove'])})")
    gui.sub("movement fields", r"^(OFF_VEL,\s*OFF_MAXSPD,\s*OFF_ACCEL,\s*OFF_GRAVITY\s*=\s*)(0x[0-9A-Fa-f]+),\s*0x[0-9A-Fa-f]+,\s*0x[0-9A-Fa-f]+,\s*0x[0-9A-Fa-f]+",
            lambda m: f"{m.group(1)}{m.group(2)}, {hx(c['maxspd'])}, {hx(c['accel'])}, {hx(c['gravity'])}")
    gui.sub("health root node", r"^(HP_ROOT,\s*HP_ARR,\s*HP_NUM,\s*HP_VALUE\s*=\s*)0x[0-9A-Fa-f]+",
            lambda m: f"{m.group(1)}{hx(c['hproot'])}")
    gui.sub("economy map", r"dp, n = rp\(e \+ 0x[0-9A-Fa-f]+\), ri\(e \+ 0x[0-9A-Fa-f]+\)",
            lambda m: f"dp, n = rp(e + {hx(c['econ'])}), ri(e + {hx(c['econ'] + 8)})")
    # show the real reason when it cannot connect, instead of 'Waiting for game...' for every failure
    if gui.text is not None and "woth2_update: show why" not in gui.text:
        gui.sub("show the reason when it can't connect",
                r"(?P<ind>[ ]+)L = None\n(?P=ind)while L is None and not S\[\"stop\"\]:\n(?P<body>(?:.*\n){1,4}?)(?P=ind)    except \(Exception, SystemExit\):\n(?P=ind)        S\[\"status\"\] = \"waiting_game\"\n",
                lambda m: (f'{m.group("ind")}L = None\n{m.group("ind")}_why = [None]   # woth2_update: show why\n'
                           f'{m.group("ind")}while L is None and not S["stop"]:\n{m.group("body")}'
                           f'{m.group("ind")}    except (Exception, SystemExit) as _ex:\n'
                           f'{m.group("ind")}        _msg = str(_ex) or type(_ex).__name__\n'
                           f'{m.group("ind")}        if _msg != _why[0]:\n'
                           f'{m.group("ind")}            _why[0] = _msg; log("Cannot connect: " + _msg)\n'
                           f'{m.group("ind")}        S["status"] = "waiting_game"\n'))

    # ---- layout-only checks ----
    print("\nGAME-SPECIFIC LAYOUTS (field names unknown to me, so only the TYPES at the known offsets are checked)")
    for label, test, offs, kind in LAYOUT_CHECKS:
        state, detail = check_layout(classes, test, offs, kind)
        if state == "ok":
            print(f"  [ok]       {label}")
        elif state == "class missing":
            print(f"  [MISSING]  {label}: no such class in the new dump")
            attention.append(f"{label}: class not found, do not use that feature until it is re-mapped")
        else:
            print(f"  [CHANGED]  {label}: the layout at the old offsets no longer matches")
            attention.append(f"{label}: layout changed, so leave that switch OFF until it is re-mapped (send me this output)")
    attention.append("Health node/leaf internals (+0x50/+0x58/+0x48) and the fall-damage curve cannot be checked by name: "
                     "test Max health and No fall damage once, in a safe spot.")

    # ---- save ----
    print()
    for p in (lib, gui):
        for label, res in p.log:
            if res.startswith(("pattern", "file")):
                attention.append(f"{os.path.basename(p.path)} - {label}: {res}")
        if p.save():
            patched_files.append(os.path.basename(p.path))
    if a.dry_run:
        print("DRY RUN: nothing was changed.")
    elif patched_files:
        print("UPDATED (backup copies saved next to them): " + ", ".join(patched_files))
    else:
        print("Nothing needed changing.")
    if attention:
        print("\nNEEDS ATTENTION")
        for x in attention:
            print("  - " + x)
    if patched_files and not a.dry_run:
        print("\nNEXT: close the trainer, start the game, load into the world, run the trainer again.\n"
              "If you use the .exe, rebuild it, because the offsets are compiled into it:\n"
              "  rmdir /s /q build dist\n"
              "  pyinstaller --clean --onefile --noconsole --uac-admin --name WOTH2Trainer --hidden-import woth2lib "
              "--hidden-import pymem --hidden-import pymem.process --hidden-import keyboard trainer_gui.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
