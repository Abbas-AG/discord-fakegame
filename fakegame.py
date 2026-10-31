#!/usr/bin/env python3
"""Pretend to run a game so Discord detects it (e.g. for Discord quests).

Discord detects games by the name of running processes. fakegame looks up the
game in Discord's public list of detectable applications and starts a harmless
idle process (a copy of `sleep`) with the right executable name.

Games with no executables listed can't be detected that way. For those,
`fakegame --console GAME` prints a script to paste into Discord's developer
console that adds the game straight to the client's list of running games,
which is what quests track. Without it, fakegame falls back to setting
"Playing <game>" over Discord's RPC socket (shows on your profile, but quests
don't count it).
"""
import argparse
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

__version__ = "1.1.0"

API = "https://discord.com/api/v9/applications/detectable"
CACHE_MAX_AGE = 86400  # seconds
MAX_LISTED = 30

# Executables for games Discord lists without any (keyed by game name, lowercase)
EXTRA_EXES = {
    "firefox": ["firefox", "firefox.exe"],
}


class FakegameError(Exception):
    pass


def data_dir():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "fakegames")


def run_dir():
    return os.path.join(data_dir(), "run")


# --- game list -------------------------------------------------------------

def download_games(cache):
    req = urllib.request.Request(API, headers={"User-Agent": f"fakegame/{__version__}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    json.loads(data)  # refuse to cache a broken response
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(cache))
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, cache)


def load_games(refresh=False):
    os.makedirs(data_dir(), exist_ok=True)
    cache = os.path.join(data_dir(), "detectable.json")
    stale = not os.path.exists(cache) or time.time() - os.path.getmtime(cache) > CACHE_MAX_AGE
    if refresh or stale:
        try:
            download_games(cache)
        except (urllib.error.URLError, OSError, ValueError) as e:
            if not os.path.exists(cache):
                raise FakegameError(f"Couldn't download Discord's game list: {e}")
            print(f"warning: couldn't refresh game list ({e}); using cached copy", file=sys.stderr)
    with open(cache) as f:
        games = json.load(f)
    for g in games:
        extra = EXTRA_EXES.get(g["name"].lower())
        if extra and not g.get("executables"):
            g["executables"] = [{"name": n, "os": "linux", "is_launcher": False} for n in extra]
    return games


def find_matches(games, query):
    """Return (matches, use_rpc). use_rpc means the matches have no executables."""
    query = query.lower().strip()
    with_exe = [g for g in games if g.get("executables")]
    no_exe = [g for g in games if not g.get("executables") and query in g["name"].lower()]

    exact = [g for g in with_exe if g["name"].lower() == query]
    if exact:
        return exact, False
    contains = [g for g in with_exe if query in g["name"].lower()]
    if contains:
        return contains, False
    exact_no_exe = [g for g in no_exe if g["name"].lower() == query]
    if exact_no_exe:
        return exact_no_exe, True
    if no_exe:
        return no_exe, True
    words = [w for w in query.split() if not w.isdigit()]
    loose = [g for g in with_exe if g["name"].lower() in query] \
        or [g for g in with_exe if words and all(w in g["name"].lower() for w in words)]
    return loose, False


def pick(matches):
    if len(matches) == 1:
        return matches[0]
    shown = matches[:MAX_LISTED]
    for i, g in enumerate(shown, 1):
        print(f"{i:2}) {g['name']}")
    if len(matches) > MAX_LISTED:
        print(f"... and {len(matches) - MAX_LISTED} more; try a more specific name.")
    while True:
        try:
            choice = input("Pick number: ").strip()
        except EOFError:
            raise FakegameError("No game picked.")
        if choice.isdigit() and 1 <= int(choice) <= len(shown):
            return shown[int(choice) - 1]
        print(f"Enter a number from 1 to {len(shown)}.")


def exe_names(game):
    exes = [e for e in game["executables"] if e.get("os") != "darwin" and not e.get("is_launcher")] \
        or game["executables"][:1]
    # Names may include a parent folder (e.g. "win64/game.exe"); Discord matches the path suffix,
    # so keep it. Strip anything that could escape the run directory.
    names = (os.path.normpath(e["name"].lstrip(">")).lstrip("/") for e in exes)
    return list(dict.fromkeys(n for n in names if not n.startswith("..")))


# --- running ---------------------------------------------------------------

def wait_until_stopped(wait, cleanup):
    """Block in wait() until it returns (or Ctrl+C / SIGTERM), then clean up."""
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    cleanup()
    print("\nStopped.")


def sleep_forever():
    while True:
        time.sleep(3600)


def run_process(game):
    sleep = shutil.which("sleep")
    if not sleep:
        raise FakegameError("`sleep` not found in PATH.")
    names = exe_names(game)
    procs = []
    for name in names:
        path = os.path.join(run_dir(), game["id"], name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            shutil.copy(sleep, path)
        procs.append(subprocess.Popen([path, "infinity"], cwd=os.path.dirname(path)))

    def wait():  # returns once `fakegame --stop` has killed every process
        for p in procs:
            p.wait()

    def cleanup():
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait()

    print(f"Running '{game['name']}' as {', '.join(names)}  (Ctrl+C to stop)")
    wait_until_stopped(wait, cleanup)


def ipc_socket_path():
    run = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    dirs = [run, os.path.join(run, "app/com.discordapp.Discord"), os.path.join(run, "snap.discord")]
    for d in dirs:
        for i in range(10):
            p = os.path.join(d, f"discord-ipc-{i}")
            if os.path.exists(p):
                return p
    return None


def run_rpc(game):
    """Set 'Playing <game>' over Discord's local RPC socket (for games with no executables)."""
    path = ipc_socket_path()
    if not path:
        raise FakegameError("Discord isn't running (no discord-ipc socket found).")
    s = socket.socket(socket.AF_UNIX)
    s.connect(path)

    def send(op, data):
        b = json.dumps(data).encode()
        s.sendall(struct.pack("<II", op, len(b)) + b)

    def recv_exact(n):
        buf = b""
        while len(buf) < n:
            chunk = s.recv(n - len(buf))
            if not chunk:
                raise FakegameError("Discord closed the RPC connection.")
            buf += chunk
        return buf

    def recv():
        _, n = struct.unpack("<II", recv_exact(8))
        return json.loads(recv_exact(n))

    send(0, {"v": 1, "client_id": game["id"]})
    recv()
    send(1, {"cmd": "SET_ACTIVITY", "nonce": str(uuid.uuid4()),
             "args": {"pid": os.getpid(), "activity": {"timestamps": {"start": int(time.time())}}}})
    reply = recv()
    if reply.get("evt") == "ERROR":
        raise FakegameError(f"Discord rejected the activity: {reply['data']}")

    print(f"Showing 'Playing {game['name']}' via Discord RPC (no executables listed)  (Ctrl+C to stop)")
    wait_until_stopped(sleep_forever, s.close)


# --- console mode ----------------------------------------------------------

# Pasted into Discord's developer console (Ctrl+Shift+I). Finds the RunningGameStore
# and dispatcher in Discord's webpack modules, then makes the store report the game
# as running. Quests track that store, so this works for games Discord can't detect
# by process name. Reloading Discord (Ctrl+R) or running fakegameStop() undoes it.
CONSOLE_JS = r"""
(() => {
  const GAME = __GAME__;
  let req;
  webpackChunkdiscord_app.push([[Symbol("fakegame")], {}, r => { req = r; }]);
  webpackChunkdiscord_app.pop();
  const find = test => {
    for (const m of Object.values(req.c)) {
      try {
        const ex = m && m.exports;
        if (!ex || typeof ex !== "object") continue;
        for (const v of [ex, ...Object.values(ex)]) {
          if (v && typeof v === "object" && test(v)) return v;
        }
      } catch (e) {}
    }
  };
  const store = find(v => typeof v.getRunningGames === "function" && typeof v.getGameForPID === "function");
  const flux = find(v => typeof v.dispatch === "function" && typeof v.subscribe === "function"
                         && typeof v.flushWaitQueue === "function");
  if (!store || !flux) return console.error("fakegame: couldn't find Discord's game store (Discord may have changed).");

  const st = window.__fakegame || (window.__fakegame = {
    games: [], getRunningGames: store.getRunningGames, getGameForPID: store.getGameForPID});
  const publish = (added, removed) => {
    const games = [...st.getRunningGames.call(store), ...st.games];
    store.getRunningGames = st.games.length ? () => games : st.getRunningGames;
    store.getGameForPID = st.games.length
      ? pid => st.games.find(g => g.pid === pid) || st.getGameForPID.call(store, pid)
      : st.getGameForPID;
    flux.dispatch({type: "RUNNING_GAMES_CHANGE", added, removed, games});
  };
  window.fakegameStop = () => { const removed = st.games; st.games = []; publish([], removed);
                                console.log("fakegame: stopped."); };

  const pid = 10000 + Math.floor(Math.random() * 50000);
  const game = {
    id: GAME.id, name: GAME.name, pid, pidPath: [pid], processName: GAME.name,
    exeName: GAME.exe, exePath: "c:/program files/" + GAME.name.toLowerCase() + "/" + GAME.exe,
    cmdLine: "C:\\Program Files\\" + GAME.name + "\\" + GAME.exe,
    hostname: "", hidden: false, start: Date.now(),
  };
  st.games.push(game);
  publish([game], []);
  console.log("fakegame: now playing " + GAME.name + ". Keep Discord open; run fakegameStop() to stop.");
})();
"""


def console_snippet(game):
    exes = exe_names(game) if game.get("executables") else []
    exe = os.path.basename(exes[0]) if exes else \
        "".join(c for c in game["name"] if c not in '/\\:*?"<>|') + ".exe"
    args = {"id": game["id"], "name": game["name"], "exe": exe}
    return CONSOLE_JS.replace("__GAME__", json.dumps(args)).strip()


def copy_to_clipboard(text):
    for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "-b", "-i"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text.encode(), check=True, timeout=5)
                return True
            except (OSError, subprocess.SubprocessError):
                pass
    return False


def show_console_snippet(game):
    js = console_snippet(game)
    print(js)
    copied = copy_to_clipboard(js)
    print(f"""
--- How to use ({game['name']}) ---
1. In the Discord desktop app, accept the quest.
2. Press Ctrl+Shift+I and open the Console tab{' (the script above is already copied)' if copied else ''}.
   If nothing opens, run `fakegame --enable-devtools` once (with Discord closed).
3. Paste the script and press Enter (if pasting is blocked, type `allow pasting` first).
4. Leave Discord open until the quest completes. Run fakegameStop() or press Ctrl+R to stop.""",
          file=sys.stderr)


DEVTOOLS_KEY = "DANGEROUS_ENABLE_DEVTOOLS_ONLY_ENABLE_IF_YOU_KNOW_WHAT_YOURE_DOING"


def discord_settings_files():
    config = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    flatpak = os.path.expanduser("~/.var/app/com.discordapp.Discord/config")
    dirs = [os.path.join(c, d) for c in (config, flatpak) for d in ("discord", "discordptb", "discordcanary")]
    return [os.path.join(d, "settings.json") for d in dirs if os.path.isdir(d)]


def discord_running():
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/comm") as f:
                if f.read().strip() in ("Discord", "DiscordPTB", "DiscordCanary"):
                    return True
        except OSError:
            pass
    return False


def enable_devtools():
    files = discord_settings_files()
    if not files:
        raise FakegameError("No Discord settings found. Start Discord once, then try again.")
    if discord_running():
        raise FakegameError("Fully quit Discord first (it overwrites its settings on exit).")
    for path in files:
        try:
            with open(path) as f:
                settings = json.load(f)
        except FileNotFoundError:
            settings = {}
        except ValueError:
            raise FakegameError(f"Couldn't parse {path}; not touching it.")
        if settings.get(DEVTOOLS_KEY) is True:
            print(f"Already enabled: {path}")
            continue
        settings[DEVTOOLS_KEY] = True
        with open(path, "w") as f:
            json.dump(settings, f, indent=2)
        print(f"Enabled developer console: {path}")
    print("Start Discord again; Ctrl+Shift+I now opens the console.")


def stop():
    root = run_dir() + "/"
    n = 0
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            exe = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            continue
        if exe.startswith(root):
            try:
                os.kill(int(pid), signal.SIGTERM)
                n += 1
            except ProcessLookupError:
                pass
    print(f"Stopped {n} fake game(s).")


# --- cli -------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="fakegame",
        description="Pretend to run a game so Discord detects it.",
        epilog='examples:\n  fakegame "marvel rivals"\n  fakegame --list valorant\n'
               '  fakegame --console "ea sports fc 27"\n  fakegame --stop',
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game", nargs="*", help="game name (or part of it)")
    ap.add_argument("--stop", action="store_true", help="stop all running fake games")
    ap.add_argument("--list", action="store_true", help="list matching games and exit")
    ap.add_argument("--refresh", action="store_true", help="re-download Discord's game list")
    ap.add_argument("--console", action="store_true",
                    help="print a script for Discord's developer console that marks the game as "
                         "running; works for games Discord can't detect by process name")
    ap.add_argument("--enable-devtools", action="store_true",
                    help="turn on Discord's developer console (Ctrl+Shift+I); run with Discord closed")
    ap.add_argument("--exe", action="append", metavar="NAME",
                    help="run this executable name instead of the listed ones (repeatable), "
                         'e.g. --exe "ea sports fc 27/fc27.exe"')
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = ap.parse_args(argv)

    if not sys.platform.startswith("linux"):
        ap.exit(1, "fakegame only supports Linux.\n")

    try:
        if args.stop:
            return stop()
        if args.enable_devtools:
            return enable_devtools()
        if not args.game:
            if args.refresh:
                load_games(refresh=True)
                return print("Game list updated.")
            ap.print_help()
            return 1
        matches, use_rpc = find_matches(load_games(args.refresh), " ".join(args.game))
        if not matches:
            raise FakegameError(f"No detectable game matching '{' '.join(args.game)}'.")
        if args.list:
            for g in matches:
                print(f"{g['name']}  [{', '.join(exe_names(g)) if g.get('executables') else 'RPC'}]")
            return
        game = pick(matches)
        if args.exe:
            return run_process(dict(game, executables=[{"name": n, "os": "linux"} for n in args.exe]))
        if args.console:
            return show_console_snippet(game)
        if use_rpc:
            print(f"Note: Discord can't detect '{game['name']}' by process name, so quests won't count "
                  f"this.\nFor quests use:  fakegame --console \"{game['name']}\"\n", file=sys.stderr)
            return run_rpc(game)
        run_process(game)
    except FakegameError as e:
        print(f"fakegame: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
