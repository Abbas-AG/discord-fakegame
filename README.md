# discord-fakegame

Make Discord think you're playing a game, without installing it. Handy for
Discord quests that require playing a game for a few minutes.

Linux only. No dependencies beyond Python 3.10+.

> **Heads up:** this goes against Discord's Terms of Service. Use it at your
> own risk; your account could be flagged.

## How it works

Discord detects games by looking at the names of running processes. `fakegame`
downloads Discord's public list of detectable games, finds the one you asked
for, and starts an idle process (a copy of `sleep`) under the game's executable
name. It uses almost no CPU or memory.

Some games (often brand-new ones) have no executables in Discord's list, so
Discord can't detect them by process name and quests won't count a fake
process. For those, use **console mode** (below). Without it, `fakegame` only
sets "Playing <game>" through Discord's local RPC socket, which shows on your
profile but doesn't count for quests.

## Install

```sh
pipx install git+https://github.com/Abbas-AG/discord-fakegame
```

Or copy the single file:

```sh
curl -o ~/.local/bin/fakegame https://raw.githubusercontent.com/Abbas-AG/discord-fakegame/main/fakegame.py
chmod +x ~/.local/bin/fakegame
```

## Usage

```sh
fakegame "marvel rivals"     # run it (pick from a list if several match)
fakegame --list marvel       # show matching games and their executables
fakegame --console fc 27     # script for games Discord can't detect (see below)
fakegame --stop              # stop every running fake game
fakegame --refresh           # re-download Discord's game list
```

Press Ctrl+C to stop the game you started. Discord should show
"Playing <game>" within a few seconds.

Use `fakegame --exe "folder/game.exe" "game name"` to run a specific
executable name instead of the ones Discord lists.

## Console mode (games Discord can't detect)

```sh
fakegame --console "ea sports fc 27"
```

This prints a short script (and copies it to your clipboard if `wl-copy`,
`xclip` or `xsel` is installed). The script adds the game straight to the
Discord app's list of running games, which is what quests track. It works for
any game in Discord's list, even one with no executables.

1. In the Discord **desktop app**, accept the quest.
2. Press **Ctrl+Shift+I** and open the **Console** tab. If nothing opens, quit
   Discord completely and run `fakegame --enable-devtools` once.
3. Paste the script and press Enter. If the console refuses to paste, type
   `allow pasting` first.
4. Leave Discord open until the quest completes. Run `fakegameStop()` in the
   console, or press Ctrl+R, to stop.

> Never paste console scripts from people you don't trust: the console has
> full access to your account. This one is generated locally by `fakegame`,
> and its source is the `CONSOLE_JS` block in `fakegame.py`.

## Files

Everything lives in `~/.local/share/fakegames` (or `$XDG_DATA_HOME/fakegames`):

- `detectable.json`: Discord's game list, refreshed once a day
- `run/`: the fake executables

Delete that folder to remove all traces.

## Development

```sh
python -m pytest
```

## License

MIT
