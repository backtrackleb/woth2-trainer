# Way of the Hunter 2 Trainer

A single-player trainer for **Way of the Hunter 2**, written in Python. Built by [Backtrackleb](https://github.com/backtrackleb).

![WOTH2 Trainer screenshot](PASTE-YOUR-EXISTING-SCREENSHOT-LINK-OR-UPLOAD-IT-TO-A-docs-FOLDER)

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
| Tested game version | `REPLACE-WITH-BUILD-NUMBER` (Steam / Epic) |
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
| Speed boost | `REPLACE` |
| High jump | `REPLACE` |
| Superman (fly) | `REPLACE` |
| Max health | `REPLACE` |
| No fall damage | `REPLACE` |
| Add money | `REPLACE` |
| Weather control | `REPLACE` |
| Time of day | `REPLACE` |

To change them, edit the `KEYS` block at the top of `trainer_gui.py`.

## Run from source

```bash
pip install -r requirements.txt
python trainer_gui.py
```

Run it from an administrator prompt, with the game running and your character in the world.

## Build an exe

```bash
pyinstaller --clean --onefile --noconsole --uac-admin --name WOTH2Trainer --hidden-import woth2lib --hidden-import pymem --hidden-import pymem.process trainer_gui.py
```

The output is written to `dist/WOTH2Trainer.exe`.

## Updating for a new game version

1. Generate a new SDK with [Dumper-7](https://github.com/Encryqed/Dumper-7).
2. Update `GWORLD`, `GOBJECTS` and `APPEND_STRING` in `woth2lib.py`.
3. Re-check the class offsets in `trainer_gui.py` against the new dump (see `tools/`).

## Troubleshooting

- **Nothing happens / features don't work:** the game was probably patched. Check the tested version above and open an issue.
- **Antivirus flags the exe:** this is common for memory-editing tools. Build from source or verify the SHA-256 hash.
- **Trainer can't attach:** run it as administrator and make sure the game is fully loaded into the world.

## Reporting issues

Open an [issue](../../issues) and include your game version (and store: Steam / Epic), what you were doing, and any error text.

## Disclaimer

Not affiliated with or endorsed by Nine Rocks Games or THQ Nordic. Use at your own risk.

## License

[MIT](LICENSE)
