# Wii Downloader & WBFS Import CLI

Download Wii games from Vimm's Lair and romspure.cc, then convert to WBFS format for FAT32 USB loaders (USB Loader GX, WiiFlow). CLI port of TinyWiiBackupManager's import logic.

## Structure

```
wii-downloader/
├── wii_import_cli.py      # RVZ/ISO/WIA → WBFS → FAT32 USB import CLI
├── twbm_idmap.py          # Offline Wii/NGC title map (port of TinyWiiBackupManager idmap)
├── wiitdb.txt             # GameTDB title data (original language) — used by twbm_idmap
├── wiitdb-en.txt          # GameTDB title data (English) — used by twbm_idmap
├── format_wii_usb.py      # Format a USB drive to FAT32 with 32KB clusters
├── vimm_camoufox_scraper.py   # Vimm's Lair vault scraper (download links)
├── romspure_scraper.py        # romspure.cc download URL scraper
├── build_wii_csv.py           # Build wii_games.csv from Top 100 checklist
├── .gitignore
└── README.md
```

## Prerequisites

Install standalone binaries (not Python packages) and add to PATH:

| Binary | Source | Role |
|--------|--------|------|
| `wit.exe` | https://wit.wiimm.de/ | ISO → WBFS conversion + FAT32 splitting |
| `wwt.exe` | https://wit.wiimm.de/ | WBFS management |
| `nodtool.exe` | https://github.com/encounter/nod-rs/releases | RVZ/WIA/CISO → ISO |

Verify with:

```bash
python wii_import_cli.py check
```

## Usage

### 1. Get download links

**Vimm's Lair (retail games):**
```bash
python vimm_camoufox_scraper.py "Mario"
python vimm_camoufox_scraper.py --id 63809
```

**romspure.cc (hacks/mods):**
```bash
python romspure_scraper.py "https://romspure.cc/hacks/wii/mario-kart-wii-deluxe/"
python romspure_scraper.py "https://romspure.cc/hacks/wii/mario-kart-wii-deluxe/" --download
```

### 2. Build the game CSV (optional tracking)

```bash
python build_wii_csv.py
```
Reads `wii_checklist.txt` (Top 100 Wii games) and outputs `wii_games.csv` with columns:
`num, genre, title, size_gb, dual_layer, motionplus, notes, status, vault_id, download_url, romspure_size_gb, romspure_url, local_file`

### 3. Import to USB drive

```bash
# Format the USB drive first (FAT32, 32KB clusters)
python format_wii_usb.py D: 32768 WII

# Single file
python wii_import_cli.py import game.rvz E: --game-num 1

# Conveyor-belt: watch a folder for new downloads
python wii_import_cli.py watch ./downloads E:

# Check tools
python wii_import_cli.py check
```

### Output structure on USB

```
USB:/wbfs/
  New Super Mario Bros. Wii [SMNE01]/
    SMNE01.wbfs          (first part, ≤4 GiB)
    SMNE01.wbf1          (split part, if >4 GiB)
```

## Conversion flow (port of TinyWiiBackupManager import.rs)

1. **Read game ID** from disc header at offset 0x0000 (6 ASCII chars)
2. **GameTDB lookup** — fetches official title from gametdb.com by game ID
3. **Title sanitize** — 64-char ASCII whitelist (TinyWii's `sanitize_title`)
4. **If already `.wbfs`** → copy directly (fast path, no conversion)
5. **Convert non-ISO** → ISO via nodtool (RVZ/WIA/CISO/GCZ)
6. **ISO → WBFS** via wit (`wit COPY --wbfs`)
7. **Split > 4 GiB - 32 KiB** into `.wbfs` + `.wbf1` + `.wbf2`…
8. **Place** at `USB:/wbfs/Game Name [GAMEID]/GAMEID.wbfs`
9. **Update CSV** — flip `status` → `downloaded`, fill `local_file`

## Requirements

- Python 3.10+
- Windows (camoufox, camoufox-async)
- `wit.exe` + `nodtool.exe` on PATH
- A FAT32 USB drive (32KB clusters, MBR partition table)

## License

MIT