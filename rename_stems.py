"""
rename_stems.py — Rename stem files to match naming convention

Convention: NN_Stem_Name.mp3
  - NN = 2-digit sequence number based on file modification time (oldest = 00)
  - Stem name: cleaned, title-cased, underscores, no HTML entities
    - (left) → _Left, (right) → _Right, (center) → _Center, (bass) → _Bass, (treble) → _Treble
    - &nbsp; and stray artifacts removed
    - Spaces → underscores

Usage:
    # Rename files in a specific folder:
    python rename_stems.py --folder "C:\\Users\\myers\\Dropbox\\_Tracks\\Doobie_Brothers-China_Grove"

    # Rename using artist/song (uses Dropbox _Tracks folder from config):
    python rename_stems.py --artist "Doobie Brothers" --song "China Grove"

    # Preview without renaming:
    python rename_stems.py --artist "Doobie Brothers" --song "China Grove" --dry-run
"""

import argparse
import os
import re
import sys
from pathlib import Path


def clean_stem_name(raw: str) -> str:
    """
    Convert a raw stem filename (without extension) to clean convention.

    Examples:
        Pianonbass                       → Piano_Bass
        Pianontreble                     → Piano_Treble
        Rhythm_Electric_Guitarnleft      → Rhythm_Electric_Guitar_Left
        Rhythm_Electric_Guitarnright     → Rhythm_Electric_Guitar_Right
        Arr_Electric_Guitarncenter       → Arr_Electric_Guitar_Center
        Intro_countanbspnbspnbspClick    → Intro_Count_Click
        Backing_Vocals                   → Backing_Vocals
        Lead_Vocal                       → Lead_Vocal
        Drum_Kit                         → Drum_Kit
    """
    name = raw

    # Remove file extension if present
    name = re.sub(r'\.mp3$', '', name, flags=re.IGNORECASE)

    # Strip &nbsp; artifacts — show up as "nbsp" or "anbsp" in filenames
    name = re.sub(r'a?nbsp', '', name, flags=re.IGNORECASE)

    # Fix "n" suffix before direction/position words — e.g. "Guitarnleft" → "Guitar_Left"
    # These come from HTML entities like \n bleeding into names
    direction_map = {
        'nleft':   '_Left',
        'nright':  '_Right',
        'ncenter': '_Center',
        'nbass':   '_Bass',
        'ntreble': '_Treble',
        'nleft':   '_Left',
    }
    for pattern, replacement in direction_map.items():
        name = re.sub(pattern, replacement, name, flags=re.IGNORECASE)

    # Clean up any remaining stray characters
    name = re.sub(r'[^A-Za-z0-9_]+', '_', name)

    # Collapse multiple underscores
    name = re.sub(r'_+', '_', name)

    # Strip leading/trailing underscores
    name = name.strip('_')

    return name


def rename_stems_in_folder(folder: Path, dry_run: bool = False) -> list[tuple]:
    """
    Rename all .mp3 files in folder by modification time order.
    Returns list of (old_name, new_name) tuples.
    """
    mp3s = sorted(folder.glob("*.mp3"), key=lambda f: f.stat().st_mtime)

    if not mp3s:
        print(f"No .mp3 files found in {folder}")
        return []

    renames = []
    for i, mp3 in enumerate(mp3s):
        clean = clean_stem_name(mp3.stem)
        new_name = f"{i:02d}_{clean}.mp3"
        renames.append((mp3, folder / new_name))

    # Preview
    print(f"\n{'DRY RUN — ' if dry_run else ''}Renaming {len(renames)} files in:")
    print(f"  {folder}\n")
    max_old = max(len(r[0].name) for r in renames)
    for old, new in renames:
        print(f"  {old.name:<{max_old}}  →  {new.name}")

    if dry_run:
        print("\nDry run complete — no files changed.")
        return renames

    print()
    # Do the renames — use temp names first to avoid collisions
    for old, new in renames:
        if old == new:
            continue
        tmp = old.with_name("__tmp_" + old.name)
        old.rename(tmp)

    tmp_files = sorted(folder.glob("__tmp_*.mp3"), key=lambda f: f.stat().st_mtime)
    for tmp, (_, new) in zip(tmp_files, renames):
        tmp.rename(new)
        print(f"  Renamed: {new.name}")

    print(f"\nDone — {len(renames)} files renamed.")
    return renames


def main():
    p = argparse.ArgumentParser(description="Rename stem files to NN_Name.mp3 convention")
    p.add_argument("--folder",   help="Full path to stems folder")
    p.add_argument("--artist",   help="Artist name (uses _Tracks folder from config)")
    p.add_argument("--song",     help="Song title")
    p.add_argument("--dry-run",  action="store_true", help="Preview renames without changing files")
    args = p.parse_args()

    if args.folder:
        folder = Path(args.folder)
    elif args.artist and args.song:
        from utils import build_dropbox_folder_name
        folder_name = build_dropbox_folder_name(args.artist, args.song)
        # Read DOWNLOADS_DIR from config
        from config import DOWNLOADS_DIR
        folder = Path(DOWNLOADS_DIR) / folder_name
        if not folder.exists():
            # Try Dropbox _Tracks path directly
            dropbox_path = Path(os.path.expanduser("~")) / "Dropbox" / "_Tracks" / folder_name
            if dropbox_path.exists():
                folder = dropbox_path
            else:
                print(f"ERROR: Folder not found:\n  {folder}\n  {dropbox_path}", file=sys.stderr)
                sys.exit(1)
    else:
        print("ERROR: Provide --folder or both --artist and --song", file=sys.stderr)
        sys.exit(1)

    if not folder.exists():
        print(f"ERROR: Folder not found: {folder}", file=sys.stderr)
        sys.exit(1)

    rename_stems_in_folder(folder, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
