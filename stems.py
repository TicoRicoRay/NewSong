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

    confirmed_keys = None  # will be set during upfront prompt

    # Step 1: Get stem list upfront (login + search, no download yet)
    if not args.skip_download:
        from kv_download import get_stem_list, download_all_stems
        from mixdown import classify_stem

        print("Fetching stem list from Karaoke-Version...")
        stem_info = asyncio.run(get_stem_list(
            artist=args.artist,
            song=args.song,
            song_url=args.url,
            target_key=args.key,
        ))
        if not stem_info:
            print("ERROR: Could not fetch stem list.", file=sys.stderr)
            sys.exit(1)

        track_names = stem_info["track_names"]

        # Show stems with auto-classification
        print()
        print("Stems found:")
        for i, name in track_names.items():
            role = classify_stem(name)
            marker = "  [KEYS]" if role == 'keys' else ""
            print(f"  {name}{marker}")

        keys_detected = [name for name in track_names.values() if classify_stem(name) == 'keys']
        print()
        if keys_detected:
            print(f"Keys detected: {keys_detected}")
        else:
            print("No keys stems detected.")

        # Ask upfront — all human interaction before slow download
        answer = input("Keys correct? Press Enter to confirm, or type stem names to override (comma-separated): ").strip()
        if answer:
            confirmed_keys = [k.strip() for k in answer.split(",")]
            print(f"  Using keys: {confirmed_keys}")
        else:
            confirmed_keys = keys_detected
            print("  Confirmed.")

        print()

        # Step 2: Download all stems (slow — no more prompts after this)
        paths = asyncio.run(download_all_stems(
            artist=args.artist,
            song=args.song,
            song_url=stem_info["song_url"],
            target_key=args.key,
        ))
        if not paths:
            print("ERROR: No stems downloaded.", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"Skipping KV download — using existing files in {stems_dir}")

    # Step 3: Dropbox sync happens automatically via desktop app
    print(f"\nStems saved to: {stems_dir}")

    # Step 4: Create mixdowns (auto_confirm=True since keys already confirmed above)
    print()
    from mixdown import create_mixdowns
    create_mixdowns(Path(stems_dir), make_learning=True, make_practice=True,
                    auto_confirm=True, confirmed_keys=confirmed_keys)

    # Step 4: Upload mixdowns to BandHelper
    print()
    print("Uploading mixdowns to BandHelper...")
    learning_mp3 = Path(stems_dir) / f"{folder}_learning.mp3"
    practice_mp3 = Path(stems_dir) / f"{folder}_practice.mp3"

    if not learning_mp3.exists() or not practice_mp3.exists():
        print("WARNING: Mixdown files not found — skipping BandHelper upload", file=sys.stderr)
    else:
        from bandhelper import login, find_song, upload_recording
        from config import BH_ACCOUNT, BH_USERNAME, BH_PASSWORD
        from playwright.async_api import async_playwright

        async def run_upload():
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=False)
                page    = await browser.new_page()
                if not await login(page, BH_ACCOUNT, BH_USERNAME, BH_PASSWORD):
                    await browser.close()
                    return
                song_url = await find_song(page, args.song)
                if not song_url:
                    await browser.close()
                    return
                if "song_edit" not in song_url:
                    import re
                    song_id = re.search(r'ID=([^&]+)', song_url)
                    if song_id:
                        from bandhelper import BH_EDIT_URL
                        song_url = f"{BH_EDIT_URL}?ID={song_id.group(1)}"
                await page.goto(song_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
                await upload_recording(page, str(learning_mp3), f"{args.song} - Learning")
                await upload_recording(page, str(practice_mp3), f"{args.song} - Practice")
                await browser.close()

        asyncio.run(run_upload())

    print()
    print("Done — stems + mixdowns + BandHelper upload complete.")


if __name__ == "__main__":
    main()
