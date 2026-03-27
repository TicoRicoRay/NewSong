"""
stems.py — Download KV stems → rename → Dropbox (via desktop app sync)

Usage:
    python stems.py --artist "Doobie Brothers" --song "China Grove"
    python stems.py --artist "The Bangles" --song "Walk Like an Egyptian"
    python stems.py --url "https://www.karaoke-version.com/custombackingtrack/..." --artist "X" --song "Y"
"""

import argparse
import asyncio
import sys
from pathlib import Path

try:
    from autoupdate import check_for_updates
    check_for_updates()
except Exception:
    pass  # never block the main script


def parse_song_arg(args):
    """
    Allow natural language: python stems.py "The Joker - Steve Miller Band"
    Parses as song - artist (the natural way people say it).
    Falls back to --artist / --song flags if provided.
    """
    if args.artist and args.song:
        return args.artist, args.song

    # Check for positional free-form argument
    if args.freeform:
        text = " ".join(args.freeform)
        if " - " in text:
            parts = text.split(" - ", 1)
            song   = parts[0].strip()
            artist = parts[1].strip()
            print(f"Parsed: Artist='{artist}' | Song='{song}'")
            return artist, song
        else:
            print("ERROR: Free-form input must be 'Song Title - Artist Name'", file=sys.stderr)
            sys.exit(1)

    print("ERROR: Provide --artist and --song, or 'Song - Artist' as argument", file=sys.stderr)
    sys.exit(1)


def main():
    p = argparse.ArgumentParser(
        description="Download KV stems + mixdowns",
        epilog='Example: python stems.py "The Joker - Steve Miller Band"'
    )
    p.add_argument("freeform",        nargs="*", help="'Song Title - Artist Name' (alternative to --artist/--song)")
    p.add_argument("--artist",        help="Artist name")
    p.add_argument("--song",          help="Song title")
    p.add_argument("--url",           help="Direct KV song URL (skips search)")
    p.add_argument("--key",           help="Target key to transpose to (e.g. A, Bb, F#)")
    p.add_argument("--skip-download", action="store_true", help="Skip KV download (use existing stems)")
    args = p.parse_args()

    args.artist, args.song = parse_song_arg(args)

    from utils import build_dropbox_folder_name
    from config import DOWNLOADS_DIR

    folder    = build_dropbox_folder_name(args.artist, args.song)
    stems_dir = str(Path(DOWNLOADS_DIR) / folder)

    print()
    print("=" * 55)
    print(f"  {args.artist} — {args.song}")
    print(f"  Folder: {folder}")
    print("=" * 55)
    print()

    # Step 1: Download stems from KV
    if not args.skip_download:
        from kv_download import download_all_stems
        paths = asyncio.run(download_all_stems(
            artist=args.artist,
            song=args.song,
            song_url=args.url,
            target_key=args.key,
        ))
        if not paths:
            print("ERROR: No stems downloaded.", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"Skipping KV download — using existing files in {stems_dir}")

    # Step 2: Dropbox sync happens automatically via desktop app
    print(f"\nStems saved to: {stems_dir}")

    # Step 3: Create mixdowns
    print()
    from mixdown import create_mixdowns
    create_mixdowns(Path(stems_dir), make_learning=True, make_practice=True, auto_confirm=True)

    print()
    print("Done — stems + mixdowns complete.")


if __name__ == "__main__":
    main()
