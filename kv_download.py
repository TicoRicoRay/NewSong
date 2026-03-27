"""
kv_download.py — Download all stems from Karaoke-Version.com

Verified against live HTML. Uses exact field IDs and download mechanism.

Usage:
    python kv_download.py --artist "Doobie Brothers" --song "China Grove"
    python kv_download.py --url "https://www.karaoke-version.com/custombackingtrack/the-doobie-brothers/china-grove.html" --artist "Doobie Brothers" --song "China Grove"
"""

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright, Download, TimeoutError as PWTimeout

from config import KV_EMAIL, KV_PASSWORD, DOWNLOADS_DIR
from utils import build_dropbox_folder_name
from artist_normalize import normalize_artist, clean_kv_artist_result

KV_LOGIN_URL = "https://www.karaoke-version.com/my/login.html"
# Index 0 is always the HTML click/count track — always skip it
SKIP_INDICES = {0}

# Chromatic scale for semitone calculation
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTE_ALIASES = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}


def note_to_index(note: str) -> int:
    """Convert note name to chromatic index 0-11."""
    note = note.strip()
    note = NOTE_ALIASES.get(note, note)
    return NOTES.index(note)


def semitone_offset(original_key: str, target_key: str) -> int:
    """
    Calculate semitone offset to transpose from original_key to target_key.
    Returns value in range -6 to +6 (shortest path).
    Example: B -> A = -2
    """
    orig  = note_to_index(original_key)
    tgt   = note_to_index(target_key)
    diff  = (tgt - orig) % 12
    # Use shortest path: prefer -5 over +7 etc.
    if diff > 6:
        diff -= 12
    return diff

# Map \n-separated suffixes to clean underscore versions
# Verified from live mixer.setTracksDescription() output across multiple songs
SUFFIX_MAP = {
    "(left)":    "Left",
    "(right)":   "Right",
    "(center)":  "Center",
    "(centre)":  "Center",
    "(treble)":  "Treble",
    "(bass)":    "Bass",
    "(tremolo)": "Tremolo",
    "(lead)":    "Lead",
    "(rhythm)":  "Rhythm",
    "1":         "1",
    "2":         "2",
    "3":         "3",
    "4":         "4",
}


def clean_track_name(raw: str) -> str:
    """
    Clean a raw track name from mixer.setTracksDescription().

    Handles:
    - Index 0 HTML blob → returns None (caller skips it)
    - "Electric Guitar\n1" → "Electric_Guitar_1"
    - "Rhythm Electric Guitar\n(left)" → "Rhythm_Electric_Guitar_Left"
    - "Piano\n(treble)" → "Piano_Treble"
    - "Arr. Electric Guitar\n(left)" → "Arr_Electric_Guitar_Left"
    - Plain "Drum Kit" → "Drum_Kit"
    """
    # Index 0 check — contains HTML tags
    if '<' in raw or '&nbsp;' in raw:
        return None  # skip

    name = raw

    # Handle \n separator — split into base + suffix
    if '\n' in name:
        parts = name.split('\n', 1)
        base   = parts[0].strip()
        suffix = parts[1].strip().lower()
        clean_suffix = SUFFIX_MAP.get(suffix, suffix.strip('()').title())
        name = f"{base} {clean_suffix}"

    # Strip trailing periods (e.g. "Arr." → "Arr")
    name = name.replace('.', '')

    # Replace spaces with underscores, strip non-alphanumeric
    name = re.sub(r'[^A-Za-z0-9 ]+', '', name)
    name = re.sub(r' +', '_', name.strip())

    return name


def safe_filename(name: str) -> str:
    """Convert a already-cleaned track name to a safe filename."""
    name = re.sub(r'[^A-Za-z0-9 ]+', '', name)
    name = re.sub(r' +', '_', name.strip())
    return name + ".mp3"


async def login(page, email: str, password: str) -> bool:
    """Login using verified field IDs: #frm_login, #frm_password, #sbm"""
    await page.goto(KV_LOGIN_URL, wait_until="domcontentloaded")
    await page.wait_for_selector("#frm_login", timeout=10000)

    await page.fill("#frm_login", email)
    await page.fill("#frm_password", password)
    await page.click("#sbm")

    # KV redirects to homepage on success
    try:
        await page.wait_for_url(lambda url: "login" not in url, timeout=10000)
        print(f"  Logged in. URL: {page.url}")
        return True
    except Exception:
        print(f"  Login failed. URL: {page.url}", file=sys.stderr)
        return False


async def get_track_names(page) -> dict:
    """
    Extract and clean track names from mixer.setTracksDescription([...]).
    Returns dict of {index: cleaned_name}, skipping index 0 (click/HTML track).
    """
    content = await page.content()
    m = re.search(r'mixer\.setTracksDescription\(\[(.*?)\]\)', content, re.DOTALL)
    if not m:
        print("  WARNING: mixer.setTracksDescription not found, falling back to DOM")
        tracks = {}
        captions = await page.locator("div.track__caption").all()
        for i, cap in enumerate(captions):
            if i == 0:
                continue  # always skip index 0
            text = (await cap.inner_text()).strip()
            cleaned = clean_track_name(text)
            if cleaned:
                tracks[i] = cleaned
        return tracks

    # Parse the JS array — strings may contain escaped quotes and \n
    raw = m.group(1)
    # Unescape \/ back to / so HTML detection works
    raw = raw.replace('\\/', '/')
    names = re.findall(r'"((?:[^"\\]|\\.)*)"', raw)

    tracks = {}
    for i, name in enumerate(names):
        if i == 0:
            continue  # always skip — this is the HTML click/count blob
        # KV levels string uses 1-based track indices where:
        #   index 1 = precount (skipped above as i==0 in enumerate)
        #   index 2 = first real track (Drum Kit) = enumerate i==1
        # So KV track number = enumerate index + 1
        kv_index = i + 1
        name = name.replace('\\n', '\n')
        cleaned = clean_track_name(name)
        if cleaned:
            tracks[kv_index] = cleaned

    return tracks


async def get_original_key(page) -> str | None:
    """
    Extract the original key from the KV song page.
    KV shows: "In the same key as the original: B"
    """
    content = await page.content()
    m = re.search(r'In the same key as the original:\s*<[^>]+>([A-G][b#]?)', content)
    if not m:
        m = re.search(r'In the same key as the original:\s*([A-G][b#]?)', content)
    return m.group(1).strip() if m else None


async def get_song_info(page) -> dict:
    """
    Extract song ID, product ID, family ID and track count from page.
    All verified from live HTML inspection.
    """
    content = await page.content()

    # parent_id hidden input: value="25131"
    song_id = re.search(r'id="parent_id"[^>]*value="(\d+)"', content)
    # mixer.uri = '/my/begin_download.html?id=10787342&famid=5'
    prod_id = re.search(r'begin_download\.html\?id=(\d+)', content)
    fam_id  = re.search(r'famid=(\d+)', content)
    # Track count from preset data: levels=1,0.2,100.3,100...
    preset  = re.search(r'data-preset="([^"]+)"', content)

    track_count = 0
    if preset:
        # Format: 1,0.2,100.3,100...13,100.0  — count the trackIndex entries
        parts = preset.group(1).split(".")
        # Each part is "trackIndex,volume" — last part is pitch offset
        track_count = len(parts) - 1  # subtract the pitch entry

    return {
        "song_id":    song_id.group(1) if song_id else None,
        "prod_id":    prod_id.group(1) if prod_id else None,
        "fam_id":     fam_id.group(1)  if fam_id  else "5",
        "track_count": track_count,
    }


def build_levels(solo_index: int, track_count: int, pitch: int = 0) -> str:
    """
    Build the ?levels= string to solo one track at a given pitch offset.
    Format confirmed from live page: 1,0.2,100.3,100...trackN,vol.PITCH
      - Entry 1   = precount (always 0, not a real track)
      - Entries 2..track_count+1 = real tracks
      - solo_index must be in range 2..track_count+1
      - Final entry = pitch semitone offset (-6 to +6)
    """
    parts = ["1,0"]  # precount always off
    for i in range(2, track_count + 2):  # real tracks start at 2
        vol = 100 if i == solo_index else 0
        parts.append(f"{i},{vol}")
    parts.append(str(pitch))
    return ".".join(parts)


async def download_stem(page, song_url: str, stem_index: int, stem_name: str,
                        track_count: int, prod_id: str, fam_id: str,
                        outdir: Path, pitch: int = 0) -> str | None:
    # stem_name is already cleaned by get_track_names — just add .mp3
    filename = stem_name + ".mp3"
    outpath  = outdir / filename

    levels   = build_levels(stem_index, track_count, pitch)
    stem_url = f"{song_url}?levels={levels}"

    await page.goto(stem_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)

    print(f"  Triggering download (~60-90s server generation)...")
    try:
        async with page.expect_download(timeout=180_000) as dl_info:
            # Click the download button — verified id starts with "link_addcart_"
            btn = page.locator("a[id^='link_addcart_']").first
            await btn.click()

            # Wait for generation modal to clear
            try:
                modal = page.locator(".modal, [class*='generating'], [class*='progress']")
                await modal.wait_for(state="visible", timeout=8000)
                await modal.wait_for(state="hidden", timeout=120_000)
            except Exception:
                pass

        dl: Download = await dl_info.value
        tmp = await dl.path()
        if tmp:
            import shutil
            shutil.move(tmp, str(outpath))
            print(f"  Saved: {filename}")
            return str(outpath)
    except PWTimeout:
        print(f"  TIMEOUT on {stem_name}", file=sys.stderr)
    except Exception as e:
        print(f"  ERROR on {stem_name}: {e}", file=sys.stderr)

    return None


async def get_stem_list(artist: str, song: str, song_url: str = None, target_key: str = None) -> dict:
    """
    Login to KV, find the song, return stem names WITHOUT downloading anything.
    Returns dict with keys: song_url, track_names, pitch, display_artist, folder
    Used by stems.py to show stems and ask about keys BEFORE the slow download.
    """
    display_artist, search_artist, folder_artist = normalize_artist(artist)
    folder = build_dropbox_folder_name(display_artist, song)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(accept_downloads=True)
        page    = await context.new_page()

        print("Logging in to Karaoke-Version...")
        if not await login(page, KV_EMAIL, KV_PASSWORD):
            await browser.close()
            return {}

        if not song_url:
            query  = f"{search_artist} {song}".replace(" ", "+")
            search = f"https://www.karaoke-version.com/custombackingtrack/search.html?navcat=1&query={query}"
            await page.goto(search, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            link = page.locator("a.song__name[href*='/custombackingtrack/']").first
            href = await link.get_attribute("href", timeout=5000)
            if not href:
                print("ERROR: Song not found.", file=sys.stderr)
                await browser.close()
                return {}
            song_url = "https://www.karaoke-version.com" + href if href.startswith("/") else href
            print(f"Found: {song_url}")

        song_url = song_url.split("?")[0]
        await page.goto(song_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        pitch = 0
        if target_key:
            original_key = await get_original_key(page)
            if original_key:
                pitch = semitone_offset(original_key, target_key)
                print(f"Key: {original_key} → {target_key} ({pitch:+d} semitones)")

        track_names = await get_track_names(page)
        await browser.close()

    return {
        "song_url":      song_url,
        "track_names":   track_names,
        "pitch":         pitch,
        "display_artist": display_artist,
        "folder":        folder,
    }


async def download_all_stems(artist: str, song: str, song_url: str = None, target_key: str = None) -> list[str]:
    # Normalize artist name for display, KV search, and folder naming
    display_artist, search_artist, folder_artist = normalize_artist(artist)
    if display_artist != artist:
        print(f"Artist normalized: '{artist}' → '{display_artist}'")

    # Pass display_artist (spaces intact) so title_case_words works correctly
    folder = build_dropbox_folder_name(display_artist, song)
    outdir = Path(DOWNLOADS_DIR) / folder

    # Clear any stale files from previous runs before downloading
    if outdir.exists():
        stale = list(outdir.glob("*.mp3"))
        if stale:
            print(f"Clearing {len(stale)} stale files from previous run...")
            for f in stale:
                f.unlink()
    outdir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(accept_downloads=True)
        page    = await context.new_page()

        # Login
        print("Logging in to Karaoke-Version...")
        if not await login(page, KV_EMAIL, KV_PASSWORD):
            print("ERROR: Login failed.", file=sys.stderr)
            await browser.close()
            return []

        # Find song page if not provided
        if not song_url:
            query  = f"{search_artist} {song}".replace(" ", "+")
            search = f"https://www.karaoke-version.com/custombackingtrack/search.html?navcat=1&query={query}"
            print(f"Searching KV: {search}")
            await page.goto(search, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            # Use verified CSS class from HTML inspection
            link = page.locator("a.song__name[href*='/custombackingtrack/']").first
            href = await link.get_attribute("href", timeout=5000)
            if not href:
                print("ERROR: Song not found.", file=sys.stderr)
                await browser.close()
                return []
            song_url = "https://www.karaoke-version.com" + href if href.startswith("/") else href
            print(f"Found: {song_url}")

        # Load song page — append pitch param directly if key requested
        song_url = song_url.split("?")[0]  # strip any existing params
        print(f"Loading song page...")
        await page.goto(song_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Calculate pitch offset if target key requested
        pitch = 0
        if target_key:
            original_key = await get_original_key(page)
            if original_key:
                pitch = semitone_offset(original_key, target_key)
                print(f"Key: {original_key} → {target_key} ({pitch:+d} semitones)")
                # Reload page with pitch param — same as clicking the Reload button
                await page.goto(f"{song_url}?pitch={pitch}", wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
            else:
                print(f"WARNING: Could not detect original key — downloading in original key")

        # Get song info and track names
        info        = await get_song_info(page)
        track_names = await get_track_names(page)
        track_count = info["track_count"] or len(track_names)

        print(f"  Found {len(track_names)} stems | Song ID: {info['song_id']}")
        print(f"  Output: {outdir}\n")

        # Download each stem
        downloaded = []
        stems_to_dl = [(i, name) for i, name in track_names.items() if i not in SKIP_INDICES]

        print(f"Stems to download ({len(stems_to_dl)}):")
        for i, name in stems_to_dl:
            print(f"  [{i}] {name}")

        est = len(stems_to_dl) * 75
        print(f"\nEstimated time: {est // 60}-{(est + len(stems_to_dl)*15) // 60} minutes\n")

        for n, (idx, name) in enumerate(stems_to_dl, 1):
            print(f"[{n}/{len(stems_to_dl)}] {name}")
            path = await download_stem(
                page, song_url, idx, name,
                track_count, info["prod_id"], info["fam_id"], outdir,
                pitch=pitch
            )
            if path:
                downloaded.append(path)
            if n < len(stems_to_dl):
                await asyncio.sleep(2)

        await browser.close()

    print(f"\nDone: {len(downloaded)}/{len(stems_to_dl)} stems downloaded.")

    # Rename files to NN_Stem_Name.mp3 convention
    if downloaded:
        print("\nRenaming to convention (NN_Stem_Name.mp3)...")
        from rename_stems import rename_stems_in_folder
        rename_stems_in_folder(outdir)

    return downloaded


def main():
    p = argparse.ArgumentParser(description="Download stems from Karaoke-Version.com")
    p.add_argument("--artist", required=True)
    p.add_argument("--song",   required=True)
    p.add_argument("--url",    help="Direct KV song page URL (skips search)")
    args = p.parse_args()

    paths = asyncio.run(download_all_stems(args.artist, args.song, args.url))
    sys.exit(0 if paths else 1)


if __name__ == "__main__":
    main()
