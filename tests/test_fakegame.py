import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import fakegame  # noqa: E402

GAMES = [
    {"id": "1", "name": "Marvel Rivals", "executables": [{"name": "marvel-win64-shipping.exe", "os": "win32"}]},
    {"id": "2", "name": "Marvel Snap", "executables": [{"name": "snap.exe", "os": "win32"}]},
    {"id": "3", "name": "Some RPC Game", "executables": []},
    {"id": "4", "name": "Valorant", "executables": [
        {"name": "valorant.exe", "os": "win32"},
        {"name": "riotclient.exe", "os": "win32", "is_launcher": True},
        {"name": "valorant.app", "os": "darwin"},
    ]},
    {"id": "5", "name": "Pathy", "executables": [
        {"name": ">win64/pathy.exe", "os": "win32"},
        {"name": "../../evil", "os": "linux"},
    ]},
]


def names(matches):
    return [g["name"] for g in matches]


def test_exact_match_wins():
    m, rpc = fakegame.find_matches(GAMES, "marvel rivals")
    assert names(m) == ["Marvel Rivals"] and not rpc


def test_substring_matches():
    m, rpc = fakegame.find_matches(GAMES, "marvel")
    assert names(m) == ["Marvel Rivals", "Marvel Snap"] and not rpc


def test_rpc_fallback():
    m, rpc = fakegame.find_matches(GAMES, "rpc game")
    assert names(m) == ["Some RPC Game"] and rpc


def test_loose_word_match():
    m, _ = fakegame.find_matches(GAMES, "rivals marvel 2025")
    assert names(m) == ["Marvel Rivals"]


def test_no_match():
    assert fakegame.find_matches(GAMES, "nothing here") == ([], False)


def test_exe_names_skip_launchers_and_mac():
    assert fakegame.exe_names(GAMES[3]) == ["valorant.exe"]


def test_exe_names_keep_folder_but_block_escape():
    assert fakegame.exe_names(GAMES[4]) == ["win64/pathy.exe"]
