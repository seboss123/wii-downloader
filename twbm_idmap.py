#!/usr/bin/env python3
"""
Offline Wii/NGC game title map — exact port of TinyWiiBackupManager's crates/idmap.

Data: GameTDB wiitdb.txt (original language) + wiitdb-en.txt (English),
bundled as assets in mq1/TinyWiiBackupManager.
Game IDs are base-36 encoded.

Ported from:
  crates/idmap/src/lib.rs   (get_title / get_ascii_title)
  crates/idmap/build.rs     (parse_titles_txt / make_ascii_map)

Usage:
    from twbm_idmap import get_title, get_ascii_title
    print(get_ascii_title("SMNE01"))   # "New Super Mario Bros. Wii"
"""

import os
from pathlib import Path

# Assets live beside this module (wiitdb.txt, wiitdb-en.txt)
_ASSETS = Path(__file__).resolve().parent

_title_map: dict[str, str] = {}
_ascii_title_map: dict[str, str] = {}
_loaded = False


def _parse_titles_txt(path: Path) -> list[tuple[str, str]]:
    """Parse 'ID = Title' lines (skipping the TITLES = header line)."""
    entries = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f.read().splitlines()[1:]:
                if " = " not in line:
                    continue
                gid, title = line.split(" = ", 1)
                entries.append((gid.strip(), title))
    except FileNotFoundError:
        pass
    return entries


def _make_ascii_map(title_map: dict[str, str],
                    en_title_map: dict[str, str]) -> dict[str, str]:
    """Port of build.rs make_ascii_map.

    Only entries whose ORIGINAL title is non-ASCII are added; the English
    title is preferred when ASCII, otherwise non-ASCII chars are stripped.
    """
    entries: dict[str, str] = {}
    for gid, title in title_map.items():
        if title.isascii():
            continue  # already ASCII — handled by falling back to the original
        en = en_title_map.get(gid)
        if en and en.isascii():
            entries[gid] = en
        else:
            src = en or title
            ascii_title = "".join(c for c in src if c.isascii())
            ascii_title = ascii_title.lstrip()
            ascii_title = ascii_title[:len(ascii_title.rstrip())]
            if ascii_title:
                entries[gid] = ascii_title
    return entries


def _load() -> None:
    global _loaded
    if _loaded:
        return
    orig = _parse_titles_txt(_ASSETS / "wiitdb.txt")
    en = _parse_titles_txt(_ASSETS / "wiitdb-en.txt")
    _title_map.update(dict(orig))
    en_map = dict(en)
    _ascii_title_map.update(_make_ascii_map(dict(orig), en_map))
    _loaded = True


def get_title(game_id: str) -> str | None:
    """TinyWii's twbm_idmap::get_title."""
    _load()
    return _title_map.get(game_id)


def get_ascii_title(game_id: str) -> str | None:
    """TinyWii's twbm_idmap::get_ascii_title."""
    _load()
    return _ascii_title_map.get(game_id) or _title_map.get(game_id)


if __name__ == "__main__":
    import sys
    gid = sys.argv[1] if len(sys.argv) > 1 else "SMNE01"
    print(f"get_title({gid})       = {get_title(gid)!r}")
    print(f"get_ascii_title({gid}) = {get_ascii_title(gid)!r}")