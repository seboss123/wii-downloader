#!/usr/bin/env python3
"""
Wii Import CLI — conveyor-belt downloader → WBFS → FAT32 USB.

Reuses TinyWiiBackupManager's file-organization logic (Game Name [GAMEID]/GAMEID.wbfs)
but as a command-line tool. Conversion engines: nodtool (encounter/nod) or wit (Wiimms ISO Tools).

Usage:
  python wii_import_cli.py watch ./downloads E:                  # watch folder, import to E:/wbfs
  python wii_import_cli.py import ./downloads/game.rvz E:        # single file
  python wii_import_cli.py import ./downloads/game.iso E:        # single file

Prerequisites (standalone binaries, not Python packages):
  - nodtool.exe  (from https://github.com/encounter/nod-rs/releases)  OR
  - wit.exe      (from https://wit.wiimm.de/)
"""

import argparse
import csv
import io
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CSV_PATH = Path("wii_games.csv")

# Conversion engines (checked in order)
CMD_NODTOOL = shutil.which("nodtool") or shutil.which("nodtool.exe")
CMD_WIT = shutil.which("wit") or shutil.which("wit.exe")

# TinyWii's exact split size: 4 GiB - 32 KiB
SPLIT_SIZE = 4_294_934_528  # 4 GiB - 32 KiB
BUF_SIZE = 4 * 1024 * 1024  # 4 MiB


# ---------------------------------------------------------------------------
# Conversion engine helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Disc metadata (port of wii_disc_info::Meta::read)
# ---------------------------------------------------------------------------

class DiscMeta:
    """Parsed disc metadata — port of wii_disc_info::Meta."""

    def __init__(self, game_id: str, title: str, region: str,
                 is_wii: bool, format_str: str, disc_number: int = 0):
        self.game_id = game_id
        self.title = title
        self.region = region
        self.is_wii = is_wii
        self.format = format_str
        self.disc_number = disc_number

    def __repr__(self):
        return f"DiscMeta(id={self.game_id!r}, title={self.title!r}, region={self.region!r})"


def read_wii_header(path_or_stream) -> DiscMeta | None:
    """Read Wii disc header: game ID at 0x0000, title at 0x20, region at 0x3E."""
    try:
        if hasattr(path_or_stream, 'read'):
            f = path_or_stream
        else:
            f = open(path_or_stream, 'rb')

        f.seek(0x0000)
        gid_bytes = f.read(6)
        if len(gid_bytes) < 6:
            return None
        game_id = gid_bytes.decode('ascii', errors='ignore').strip()

        f.seek(0x0006)
        disc_num_bytes = f.read(2)
        disc_number = int.from_bytes(disc_num_bytes, 'big') if len(disc_num_bytes) == 2 else 0

        f.seek(0x0020)
        title_bytes = f.read(64)
        title = title_bytes.split(b'\x00')[0].decode('ascii', errors='ignore').strip()

        f.seek(0x003E)
        region_byte = f.read(1)
        region = region_byte.decode('ascii', errors='ignore') if region_byte else '?'

        if not game_id or not re.match(r'^[A-Z0-9]{6}$', game_id):
            return None

        if region == '?' and len(game_id) >= 4:
            region = game_id[3]

        is_wii = game_id[0] in ('R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z')
        fmt = 'wbfs'

        return DiscMeta(game_id, title, region, is_wii, fmt, disc_number)
    except Exception:
        return None
    finally:
        if not hasattr(path_or_stream, 'read'):
            f.close()


def read_meta(src_path: str) -> DiscMeta | None:
    """Read disc metadata from file, handling .zip by extracting first entry."""
    p = Path(src_path)
    if p.suffix.lower() == '.zip':
        try:
            with zipfile.ZipFile(p) as zf:
                names = zf.namelist()
                for name in names:
                    if not name.endswith('/'):
                        with zf.open(name) as entry:
                            data = entry.read()
                        return read_wii_header(io.BytesIO(data))
        except Exception:
            return None
    else:
        return read_wii_header(src_path)


# ---------------------------------------------------------------------------
# GameTDB title lookup (port of twbm_idmap::get_title / get_ascii_title)
# ---------------------------------------------------------------------------

_GAMETDB_CACHE: dict[str, str] = {}


def gametdb_title(game_id: str) -> str | None:
    """Fetch official title from GameTDB: https://www.gametdb.com/Wii/{GAMEID}"""
    if game_id in _GAMETDB_CACHE:
        return _GAMETDB_CACHE[game_id]
    try:
        url = f"https://www.gametdb.com/Wii/{game_id}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
        m = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
        if m:
            title = m.group(1).strip()
            title = re.sub(r'\s*-\s*GameTDB\s*$', '', title, flags=re.IGNORECASE)
            if title:
                _GAMETDB_CACHE[game_id] = title
                return title
    except Exception:
        pass
    _GAMETDB_CACHE[game_id] = None
    return None


def sanitize_title(ascii_title: str) -> str:
    """TinyWii's sanitize_title: keep ASCII alnum + safe punctuation, max 64 chars."""
    valid = set(" !#$%&'()+,-.;=@^_`{}~")
    title = "".join(
        c for c in ascii_title
        if c.isascii() and (c.isalnum() or c in valid)
    ).strip()[:64]
    return title or "game"


def make_game_dir_name(game_id: str, fallback_title: str) -> str:
    """TinyWii's make_game_dir_name: title from ID map, else fallback."""
    game_title = gametdb_title(game_id) or fallback_title
    title = sanitize_title(game_title)
    return f"{title} [{game_id}]"


# ---------------------------------------------------------------------------
# Import entry (port of import_entry.rs)
# ---------------------------------------------------------------------------

class ImportEntry:
    """Port of ImportEntry: path + meta + disc1/disc2 flags."""

    def __init__(self, path: Path, meta: DiscMeta):
        self.path = path
        self.meta = meta
        name = path.name
        self.is_disc1 = "(Disc 1)" in name
        self.is_disc2 = "(Disc 2)" in name

    @property
    def is_multidisc(self) -> bool:
        return self.is_disc1 or self.is_disc2


# ---------------------------------------------------------------------------
# Conversion (port of import.rs convert + same-format fast path)
# ---------------------------------------------------------------------------

def convert_to_wbfs(src: str, out_dir: Path, split: bool) -> list[Path]:
    """Convert a disc image to WBFS in out_dir. Returns list of .wbfs/.wbf1 paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    src_ext = Path(src).suffix.lower()

    # Already WBFS → just copy (TinyWii's "same format" fast path)
    if src_ext == ".wbfs":
        meta = read_meta(src)
        game_id = meta.game_id if meta else "UNKNOWN"
        dst = out_dir / f"{game_id}.wbfs"
        shutil.copy2(src, dst)
        return _split_if_needed(dst, out_dir, split) if split else [dst]

    # Need conversion: ISO/RVZ/WIA/CISO/GCZ → WBFS
    if CMD_WIT or CMD_NODTOOL:
        meta = read_meta(src)
        game_id = meta.game_id if meta else "UNKNOWN"

        # Step 1: non-ISO formats → ISO
        #   nodtool handles RVZ/WIA/CISO/GCZ → ISO (wit can't read those)
        #   wit handles ISO → WBFS
        tmp_iso = out_dir / ".tmp.iso"
        src_for_wbfs = src
        try:
            if src_ext in (".rvz", ".w", ".gcz", ".ciso", ".wia"):
                if CMD_NODTOOL:
                    # nodtool converts RVZ/WIA/CISO → ISO
                    subprocess.run(
                        [CMD_NODTOOL, "convert", src, str(tmp_iso)],
                        check=True, timeout=900,
                    )
                    src_for_wbfs = str(tmp_iso)
                elif CMD_WIT:
                    # wit can try RVZ directly (may fail on some)
                    src_for_wbfs = src

            # Step 2: ISO → WBFS
            if CMD_WIT:
                subprocess.run(
                    [CMD_WIT, "COPY", src_for_wbfs, "-v", "-B", "--wbfs", str(out_dir)],
                    check=True, timeout=900,
                )
            else:
                raise RuntimeError("wit.exe required for ISO → WBFS")
        finally:
            if tmp_iso.exists():
                tmp_iso.unlink()

        produced = sorted(out_dir.glob("*.wbfs"))
        if not produced:
            produced = sorted(out_dir.glob("*.wbf*"))
        if produced:
            return _split_if_needed(produced[0], out_dir, split)
        return []


def _split_if_needed(src: Path, out_dir: Path, split: bool) -> list[Path]:
    """Split a .wbfs file > SPLIT_SIZE into .wbfs + .wbf1 + .wbf2 …"""
    if not split or src.stat().st_size <= SPLIT_SIZE:
        return [src]

    parts = []
    part_num = 0
    with open(src, "rb") as f:
        while True:
            chunk = f.read(SPLIT_SIZE)
            if not chunk:
                break
            if part_num == 0:
                part_name = src.name  # GAMEID.wbfs
            else:
                part_name = src.stem + f".wbf{part_num}"  # GAMEID.wbf1, .wbf2…
            part_path = out_dir / part_name
            with open(part_path, "wb") as pf:
                pf.write(chunk)
            parts.append(part_path)
            part_num += 1
    src.unlink()  # remove unsplit original
    return parts


# ---------------------------------------------------------------------------
# File organization (TinyWiiBackupManager style)
# ---------------------------------------------------------------------------

def organize_on_usb(wbfs_files: list[Path], usb_root: Path,
                    entry: ImportEntry) -> list[Path]:
    """Move .wbfs/.wbf1 files into USB:/wbfs/Game Name [GAMEID]/ structure."""
    meta = entry.meta
    game_dir_name = make_game_dir_name(meta.game_id, meta.title or entry.path.stem)
    wbfs_root = usb_root / "wbfs"
    game_dir = wbfs_root / game_dir_name
    game_dir.mkdir(parents=True, exist_ok=True)

    placed = []
    for f in wbfs_files:
        dest = game_dir / f.name
        shutil.move(str(f), str(dest))
        placed.append(dest)
    return placed


# ---------------------------------------------------------------------------
# CSV tracking
# ---------------------------------------------------------------------------

def update_csv(game_num: int, title: str, usb_path: Path):
    """Mark a game as downloaded in wii_games.csv."""
    if not CSV_PATH.exists():
        return
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    h = rows[0]
    try:
        i_status = h.index("status")
        i_local = h.index("local_file")
    except ValueError:
        return
    for r in rows[1:]:
        if int(r[0]) == game_num:
            r[i_status] = "downloaded"
            r[i_local] = str(usb_path)
            break
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


# ---------------------------------------------------------------------------
# Import single file
# ---------------------------------------------------------------------------

def import_file(src_path: str, usb_root: Path, game_num: int | None = None,
                split: bool = True) -> str:
    """Import one downloaded file to the USB drive as WBFS."""
    src = Path(src_path)
    if not src.exists():
        raise FileNotFoundError(f"Not found: {src_path}")

    meta = read_meta(str(src))
    if not meta:
        raise RuntimeError(f"Could not read disc metadata from {src_path}")

    entry = ImportEntry(src, meta)
    game_id = meta.game_id
    game_name = make_game_dir_name(game_id, meta.title or src.stem)

    wbfs_files = convert_to_wbfs(str(src), src.parent, split=split)
    placed = organize_on_usb(wbfs_files, usb_root, entry)
    update_csv(game_num, game_name, placed[0])

    return f"Imported {game_name} [{game_id}] → {placed[0]}"


# ---------------------------------------------------------------------------
# Watch / conveyor-belt mode
# ---------------------------------------------------------------------------

def watch_folder(folder: str, usb_root: Path, poll: int = 10, split: bool = True):
    """Watch a folder for new disc images and import them automatically."""
    folder_path = Path(folder)
    seen: set[str] = set()
    imported_ids: set[str] = set()

    # Seed seen with existing files
    for f in folder_path.iterdir():
        if f.is_file():
            seen.add(str(f))

    print(f"Watching {folder} for new Wii disc images… (Ctrl+C to stop)")
    try:
        while True:
            for f in sorted(folder_path.iterdir()):
                if not f.is_file():
                    continue
                path_str = str(f)
                if path_str in seen:
                    continue
                ext = f.suffix.lower()
                if ext not in (".rvz", ".iso", ".wbfs", ".w", ".gcz", ".ciso", ".wia", ".zip"):
                    continue
                seen.add(path_str)
                print(f"\nNew file: {f.name}")
                try:
                    meta = read_meta(path_str)
                    if meta:
                        entry = ImportEntry(f, meta)
                        # Dedup: skip if same game_id already imported (unless multi-disc)
                        if entry.is_multidisc or meta.game_id not in imported_ids:
                            result = import_file(path_str, usb_root, split=split)
                            imported_ids.add(meta.game_id)
                            print(f"  {result}")
                        else:
                            print(f"  Skipped (already imported): {meta.game_id}")
                    else:
                        print(f"  ERROR: could not read metadata")
                except Exception as e:
                    print(f"  ERROR: {e}")
            time.sleep(poll)
    except KeyboardInterrupt:
        print("\nStopped watching.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Wii Import CLI — RVZ/ISO → WBFS → FAT32 USB")
    sub = ap.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import", help="Import a single disc image")
    p_import.add_argument("file", help="Path to .rvz/.iso/.wbfs/.wia/.gcz/.zip")
    p_import.add_argument("usb", help="USB drive root (e.g. E:)")
    p_import.add_argument("--game-num", type=int, help="Game number from wii_games.csv")
    p_import.add_argument("--no-split", action="store_true",
                          help="Don't split >4GiB files")

    p_watch = sub.add_parser("watch", help="Watch a folder and import new files automatically")
    p_watch.add_argument("folder", help="Folder to watch for new disc images")
    p_watch.add_argument("usb", help="USB drive root (e.g. E:)")
    p_watch.add_argument("--poll", type=int, default=10,
                         help="Poll interval in seconds")
    p_watch.add_argument("--no-split", action="store_true",
                         help="Don't split >4GiB files")

    p_check = sub.add_parser("check", help="Check conversion tools are available")
    args = ap.parse_args()

    if args.command == "check":
        found = []
        if CMD_NODTOOL:
            found.append(f"nodtool: {CMD_NODTOOL}")
        if CMD_WIT:
            found.append(f"wit: {CMD_WIT}")
        if found:
            print("Conversion binaries found:")
            for f in found:
                print(f"  {f}")
        else:
            print("ERROR: No conversion binaries found.")
            print("  Install nodtool: https://github.com/encounter/nod-rs/releases")
            print("  Install wit:     https://wit.wiimm.de/")
            sys.exit(1)
        return

    if not CMD_WIT:
        print("ERROR: wit.exe not found on PATH. Required for WBFS output.")
        print("  Install: https://wit.wiimm.de/")
        sys.exit(1)

    usb_root = Path(args.usb)
    if not usb_root.exists():
        print(f"ERROR: USB drive not found: {usb_root}")
        sys.exit(1)

    if args.command == "import":
        print(import_file(args.file, usb_root, args.game_num,
                          split=not args.no_split))
    elif args.command == "watch":
        watch_folder(args.folder, usb_root, poll=args.poll,
                     split=not args.no_split)


if __name__ == "__main__":
    main()