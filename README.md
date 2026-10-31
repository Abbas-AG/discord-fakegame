# discord-fakegame

Make Discord think you're playing a game, without installing it. Handy for
Discord quests that require playing a game for a few minutes.

Linux only. No dependencies beyond Python 3.8+.

> **Heads up:** this goes against Discord's Terms of Service. Use it at your
> own risk; your account could be flagged.

## How it works

Discord detects games by looking at the names of running processes. `fakegame`
downloads Discord's public list of detectable games, finds the one you asked
for, and starts an idle process (a copy of `sleep`) under the game's executable
name. It uses almost no CPU or memory.

Some games have no executables in Discord's list. For those, `fakegame` sets
"Playing <game>" through Discord's local RPC socket instead (Discord must be
running).

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
fakegame --stop              # stop every running fake game
fakegame --refresh           # re-download Discord's game list
```

Press Ctrl+C to stop the game you started. Discord should show
"Playing <game>" within a few seconds.

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
