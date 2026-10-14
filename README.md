\# WOTH2 Trainer



A single-player trainer for Way of the Hunter 2 by Backtrackleb.

Speed boost, high jump, Superman (fly), max health, No fall damage, money,

weather and time-of-day control.



\*\*Single-player only.\*\* Do not use it in the game's multiplayer or co-op modes.

It does not bypass any anti-cheat, and no support will be given for that.

Not affiliated with or endorsed by Nine Rocks Games or THQ Nordic.

Use at your own risk, and back up your save first (money edits are written to it).



\## Run from source

&#x20;   pip install -r requirements.txt

&#x20;   python trainer\_gui.py        (from an administrator prompt, game running, character in the world)



\## Build an exe

&#x20;   pyinstaller --clean --onefile --noconsole --uac-admin --name WOTH2Trainer --hidden-import woth2lib --hidden-import pymem --hidden-import pymem.process trainer\_gui.py



Antivirus software often flags tools that read other processes' memory.

Build it yourself from this source if you want to be sure what it contains.



\## Updating for a new game version

All offsets belong to one game build and will break after a patch.

1\. Generate a new SDK with Dumper-7 (github.com/Encryqed/Dumper-7).

2\. Update `GWORLD`, `GOBJECTS` and `APPEND\_STRING` in `woth2lib.py`.

3\. Re-check the class offsets in `trainer\_gui.py` against the new dump (see `tools/`).



\## Hotkeys

Edit the `KEYS` block at the top of `trainer\_gui.py`.



\## License

MIT

