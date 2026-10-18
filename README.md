# Way of the Hunter 2 Trainer

A single-player trainer for **Way of the Hunter 2**, written in Python. Built by [Backtrackleb](https://github.com/backtrackleb).

<img width="320" alt="WOTH2 Trainer screenshot" src="https://github.com/user-attachments/assets/f3cff284-158c-476e-b443-60ca84349af7" />

> **Single-player only.** Do not use it in the game's multiplayer or co-op modes.
> It does not bypass any anti-cheat, and no support will be given for that.

## Features

- Speed boost
- High jump
- Superman mode (fly)
- Max health
- No fall damage
- Money editing
- Weather control
- Time-of-day control

## Compatibility

| Item | Value |
| --- | --- |
| Game | Way of the Hunter 2 |
| Tested game version | 1.3 (`5.7.4-215031+++WOTH2+R-1.3`) (Steam / Epic) |
| Platform | Windows 10 / 11 |
| Python | 3.10+ (if running from source) |

All memory offsets belong to one game build and **will break after a game patch**. See [Updating for a new game version](#updating-for-a-new-game-version).

## Download

Grab the latest `WOTH2Trainer.exe` from the [Releases](../../releases) page. The SHA-256 hash is listed in each release's notes so you can verify the file.

Antivirus software often flags tools that read other processes' memory. If you would rather not trust a prebuilt binary, build it yourself from this source (see below).

## Usage

1. Start Way of the Hunter 2 and load into the world with your character.
2. Run the trainer **as administrator**.
3. Toggle features with the hotkeys or the GUI.

> Back up your save first. Money edits are written to it.

## Hotkeys

| Feature | Default key |
| --- | --- |
| Speed boost | `F9` |
| High jump | `F10` |
| Superman (fly) | `INSERT` |
| Max health | `F3` |
| No fall damage | `F4` |
| Add money | `F5-F6` |
| Weather control | `F8` |
| Time of day | `F7` |


## Run from source

```bash
pip install -r requirements.txt
python trainer_gui.py
```

Run it from an administrator prompt, with the game running and your character in the world.

## Build an exe

```bash
rmdir /s /q build dist
pyinstaller --clean --onefile --noconsole --uac-admin --name WOTH2Trainer --hidden-import woth2lib --hidden-import pymem --hidden-import pymem.process --hidden-import keyboard trainer_gui.py
```

The output is written to `dist/WOTH2Trainer.exe`. The offsets are compiled into the exe, so **rebuild it after every offset update**.

## Updating for a new game version

After a patch the trainer may sit on "Waiting for game..." or fail to connect, because the offsets belong to one game build.

1. Generate a new SDK of the **updated** game with [Dumper-7](https://github.com/Encryqed/Dumper-7): build it as an x64 Release DLL, inject it into the running game (offline, single-player only), and wait for `Generating SDK took ...`.
2. Run the updater from the trainer folder. It finds the newest dump under `C:\Dumper-7`:

   ```bash
   python woth2_update.py --dry-run   # report only, changes nothing
   python woth2_update.py             # applies what it can verify, keeps .bak copies
   ```

   Or point it at a dump: `python woth2_update.py --dump "C:\Dumper-7\<folder>" --dir "<trainer folder>"`.
3. Read the **NEEDS ATTENTION** list it prints. It checks the player chain, movement, health root and economy offsets by name, and checks the layout types of the weather and sky actors. Anything it cannot verify is listed instead of being changed, so leave that feature off until it is re-mapped (see `tools/`). The health node internals and the fall-damage curve cannot be checked by name: test Max health and No fall damage once in a safe spot.
4. Rebuild the exe if you use it, start the game, load into the world, start the trainer.

## Troubleshooting

- **"Waiting for game..." although the game is running:** the Log panel shows the real reason. If it says the name table was not found, the game was updated: follow [Updating for a new game version](#updating-for-a-new-game-version).
- **Nothing happens / features don't work:** the game was probably patched. Check the tested version above and open an issue.
- **Antivirus flags the exe:** this is common for memory-editing tools. Build from source or verify the SHA-256 hash.
- **Trainer can't attach:** run it as administrator and make sure the game is fully loaded into the world.

## Reporting issues

Open an [issue](../../issues) and include your game version (and store: Steam / Epic), what you were doing, and any error text.

## Disclaimer

Not affiliated with or endorsed by Nine Rocks Games or THQ Nordic. Use at your own risk.

## License

[MIT](LICENSE)
