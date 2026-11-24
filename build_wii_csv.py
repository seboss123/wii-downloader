"""Build wii_games.csv from the Top 100 checklist. One row per game."""
import csv, re

SRC = "wii_checklist.txt"
OUT = "wii_games.csv"

rows, genre = [], ""
for line in open(SRC, encoding="utf-8"):
    m = re.match(r"##\s*\d+\.\s*(.+)", line)
    if m:
        genre = m.group(1).split("(")[0].strip()
    m = re.match(r"- \[[ x]\] \*\*(\d+)\.\s*(.+?)\*\*\s*\(~([\d.]+)\s*GB\)\s*(.*)", line)
    if m:
        num, name, size, note = m.groups()
        rows.append([int(num), genre, name.strip(), float(size),
                     "yes" if "Dual-layer" in note else "no",
                     "yes" if "MotionPlus" in note or "Requires Wii MotionPlus" in note else "no",
                     note.strip()])

with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["num", "genre", "title", "size_gb", "dual_layer", "motionplus", "notes",
                "status", "vault_id", "download_url", "local_file"])
    w.writerows(r + ["wanted", "", "", ""] for r in rows)

print(f"{len(rows)} games -> {OUT}, total {sum(r[3] for r in rows):.1f} GB")
assert len(rows) == 100, f"expected 100, got {len(rows)}"