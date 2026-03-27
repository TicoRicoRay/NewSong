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
    p.add_argument("--skip-chords",   action="store_true", help="Skip UG chord fetch + BandHelper upload")
    p.add_argument("--chords-only",   action="store_true", help="Fetch chords + upload to BandHelper only, skip stems/mixdowns")
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

    from mixdown import classify_stem

    # Step 0: Fetch chords from UG + upload to BandHelper Personal Lyrics
    # SAFETY: upload_lyrics never overwrites if field already has content
    if not args.skip_chords:
        print("Fetching chords from Ultimate Guitar...")
        try:
            from ug_fetch import fetch_chord_sheet
            chord_sheet = fetch_chord_sheet(artist=args.artist, song=args.song)
            if chord_sheet:
                from bandhelper import upload_lyrics
                asyncio.run(upload_lyrics(
                    song_title=args.song,
                    content=chord_sheet,
                    account="", username="", password="",
                ))
            else:
                print("  No chords found — skipping Personal Lyrics upload.")
        except Exception as e:
            print(f"  Chords step failed ({e}) — continuing.", file=sys.stderr)
        print()

    if args.chords_only:
        print("Done — chords only.")
        return

    # Step 1a: Show stems + ask about keys BEFORE any slow work
    if not args.skip_download:
        from kv_download import get_stem_list
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
        stem_names = list(stem_info["track_names"].values())
    else:
        # --skip-download: read existing stems from disk
        print(f"Skipping KV download — using existing files in {stems_dir}")
        existing = sorted(Path(stems_dir).glob("*.mp3"))
        existing = [s for s in existing if not any(
            tag in s.name.lower() for tag in ["_learning", "_practice", "_mix"]
        )]
        stem_names = [s.stem for s in existing]  # strip .mp3
        stem_info  = None

    if not stem_names:
        print("No stems found on disk. Run without --skip-download to fetch from KV.")
        return

    # Show stems with auto-classification
    print()
    print("Stems found:")
    col_width = max(len(n) for n in stem_names) + 2
    for i, name in enumerate(stem_names, 1):
        role   = classify_stem(name)
        marker = "\U0001F3B9" if role == 'keys' else ""
        print(f"  {i:2}. {name:<{col_width}}{marker}")

    keys_detected = [name for name in stem_names if classify_stem(name) == 'keys']
    key_nums      = [i+1 for i, n in enumerate(stem_names) if classify_stem(n) == 'keys']
    print()
    if keys_detected:
        print(f"Keys detected: {key_nums} ({', '.join(keys_detected)})")
    else:
        print("No keys stems detected.")

    # Ask upfront — only human interaction in the whole workflow
    answer = input("Keys correct? Press Enter to confirm, or enter track numbers to override (e.g. 3,5): ").strip()
    if answer:
        # Accept either numbers or names
        confirmed_keys = []
        for token in answer.split(","):
            token = token.strip()
            if token.isdigit():
                idx = int(token) - 1
                if 0 <= idx < len(stem_names):
                    confirmed_keys.append(stem_names[idx])
            else:
                confirmed_keys.append(token)
        print(f"  Using keys: {confirmed_keys}")
    else:
        confirmed_keys = keys_detected
        print("  Confirmed.")
    print()

    # Step 1b: Download stems (slow — runs unattended from here)
    if not args.skip_download:
        from kv_download import download_all_stems
        paths = asyncio.run(download_all_stems(
            artist=args.artist,
            song=args.song,
            song_url=stem_info["song_url"],
            target_key=args.key,
        ))
        if not paths:
            print("ERROR: No stems downloaded.", file=sys.stderr)
            sys.exit(1)

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
    learning_mp3 = Path(stems_dir) / f"{folder}_Learning.mp3"
    practice_mp3 = Path(stems_dir) / f"{folder}_Practice.mp3"

    if not learning_mp3.exists() or not practice_mp3.exists():
        print("WARNING: Mixdown files not found — skipping BandHelper upload", file=sys.stderr)
    else:
        from bandhelper import login, find_song, upload_recording, midi_preset_exists, add_midi_preset, BH_EDIT_URL
        from config import BH_ACCOUNT, BH_USERNAME, BH_PASSWORD
        from playwright.async_api import async_playwright
        import re

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
                    song_id = re.search(r'ID=([^&]+)', song_url)
                    if song_id:
                        song_url = f"{BH_EDIT_URL}?ID={song_id.group(1)}"
                await page.goto(song_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)

                # Upload recordings
                await upload_recording(page, str(learning_mp3), f"{args.song} - Learning")
                await upload_recording(page, str(practice_mp3), f"{args.song} - Practice")

                # Create MIDI preset if one doesn't already exist for this song
                print(f"  Checking for MIDI preset: {args.song}")
                if not await midi_preset_exists(page, args.song):
                    await add_midi_preset(page, args.song)
                else:
                    print(f"  MIDI preset already exists — skipping.")

                await browser.close()

        asyncio.run(run_upload())

    print()
    print("Done — stems + mixdowns + BandHelper upload complete.")


if __name__ == "__main__":
    main()
