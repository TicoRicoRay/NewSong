"""
bandhelper.py — Upload chord sheet to BandHelper Personal Lyrics

SAFETY: Only writes to Ray's Personal Lyrics field (id="personal_lyrics").
        NEVER touches Shared Lyrics (id="lyrics") or other members' fields
        (id="personal_lyrics_20635" Buck, id="personal_lyrics_100932" Donna, etc.)

Usage:
    python bandhelper.py --song "China Grove" --file china_grove_chords.txt
    python bandhelper.py --song "China Grove" --file china_grove_chords.txt --dry-run

The script:
1. Logs in to BandHelper
2. Searches for the song by title
3. Opens the song edit page
4. Verifies it's writing to Ray's Personal Lyrics ONLY
5. Pastes the chord sheet content
6. Saves (or previews with --dry-run)
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

BH_LOGIN_URL   = "https://www.bandhelper.com/account/login.html"
BH_SONGS_URL   = "https://www.bandhelper.com/repertoire/songs.html"
BH_EDIT_URL    = "https://www.bandhelper.com/repertoire/song_edit.html"

# Ray's Personal Lyrics field ID — verified from live HTML inspection
# Other members: personal_lyrics_20635 (Buck), _100932 (Donna), _47517 (Kyle), _106126 (Sound)
RAYS_FIELD_ID  = "personal_lyrics"


async def login(page, account: str, username: str, password: str) -> bool:
    """Login using verified field IDs from live HTML inspection."""
    await page.goto(BH_LOGIN_URL, wait_until="domcontentloaded")
    await page.wait_for_selector("#accountname", timeout=10000)

    await page.fill("#accountname", account)
    await page.fill("#username", username)
    await page.fill("#password", password)
    await page.click("input[type='submit'].button")
    await page.wait_for_timeout(3000)

    # Check we're no longer on the login page
    if "login" not in page.url:
        print(f"  Logged in. URL: {page.url}")
        return True
    print(f"  Login failed. URL: {page.url}", file=sys.stderr)
    return False


async def find_song(page, song_title: str) -> str | None:
    """
    Search BandHelper songs list for a song by title.
    Song titles are plain text (not links). Each row has an Edit link.
    We find the row containing the title text, then get its Edit link.
    China Grove confirmed edit URL: song_edit.html?ID=NSZcSH
    """
    await page.goto(BH_SONGS_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)

    # Use the filter input (likely id='filter_text' based on JS patterns)
    for selector in ["#filter_text", "input[name='filter_text']", "input[placeholder*='text']"]:
        try:
            el = page.locator(selector).first
            if await el.count() > 0:
                await el.fill(song_title, timeout=3000)
                await page.wait_for_timeout(1500)
                break
        except Exception:
            continue

    # Songs are in table rows. Title is plain text, Edit link is the only href per row.
    # Find a row whose text contains the song title, then get its Edit link.
    rows = await page.locator("tr").all()
    for row in rows:
        row_text = (await row.inner_text()).strip()
        if song_title.lower() in row_text.lower():
            # Found the row — get its Edit link
            edit_link = row.locator("a[href*='song_edit']").first
            try:
                href = await edit_link.get_attribute("href", timeout=2000)
                if href:
                    url = href if href.startswith("http") else f"https://www.bandhelper.com{href}"
                    print(f"  Found: '{song_title}' → {url}")
                    return url
            except Exception:
                continue

    print(f"  Song '{song_title}' not found. Check title matches BandHelper exactly.", file=sys.stderr)
    return None


async def get_personal_lyrics(page) -> str:
    """Read current content of Ray's Personal Lyrics field."""
    try:
        content = await page.evaluate("() => get_html_content('personal_lyrics')")
        return content or ""
    except Exception:
        return ""


async def set_personal_lyrics(page, content: str) -> bool:
    """
    Write content to Ray's Personal Lyrics field ONLY.
    Uses BandHelper's own JS function to set the TinyMCE content safely.

    SAFETY CHECK: Verifies the target field is exactly 'personal_lyrics'
    (no numeric suffix) before writing anything.
    """
    # Safety check: confirm the field exists with no suffix
    field_exists = await page.evaluate("""
        () => {
            const el = document.getElementById('personal_lyrics');
            const bad = document.getElementById('personal_lyrics_20635') ||
                        document.getElementById('personal_lyrics_100932') ||
                        document.getElementById('personal_lyrics_47517');
            return !!el;
        }
    """)

    if not field_exists:
        print("ERROR: Ray's Personal Lyrics field not found on this page.", file=sys.stderr)
        return False

    # Convert plain text ChordPro to HTML (preserve line breaks)
    html_content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html_content = "<br>".join(html_content.splitlines())

    # Set content using BandHelper's own function
    try:
        await page.evaluate(f"""
            () => {{
                set_html_content('personal_lyrics', {repr(html_content)});
            }}
        """)
        print("  Content written to Personal Lyrics field.")
        return True
    except Exception as e:
        print(f"  ERROR writing content: {e}", file=sys.stderr)
        return False


async def upload_recording(page, file_path: str, recording_name: str) -> bool:
    """
    Upload a recording file to BandHelper via the 'Add Recordings' modal.

    BandHelper uses dynamic ref_NNNN IDs — never static IDs like #recording_name.
    We find fields positionally: first visible text input = Name,
    first visible file input = Upload a File.
    Save link is found by text content 'Save' within the modal.
    """
    print(f"  Uploading recording: {recording_name}")

    # Click 'Add Recordings' link — find by text since ID may vary
    await page.evaluate("""
        () => {
            const link = document.getElementById('add_recordings_link');
            if (link) { link.click(); return; }
            const all = [...document.querySelectorAll('a')];
            const found = all.find(a => a.textContent.trim() === 'Add Recordings');
            if (found) found.click();
        }
    """)

    # Wait for modal to render
    await page.wait_for_timeout(2000)

    # Find first visible text input (= Name field) and first visible file input
    fields = await page.evaluate("""
        () => {
            const inputs = [...document.querySelectorAll('input')];
            const visible = inputs.filter(el => el.offsetParent !== null);
            const textEl  = visible.find(el => el.type === 'text');
            const fileEl  = visible.find(el => el.type === 'file');
            return {
                textId: textEl ? textEl.id : null,
                fileId: fileEl ? fileEl.id : null
            };
        }
    """)
    print(f"  Modal fields: text={fields.get('textId')}  file={fields.get('fileId')}")

    text_id = fields.get('textId')
    file_id = fields.get('fileId')

    if not text_id:
        print("  ERROR: Could not find Name text input in modal", file=sys.stderr)
        return False
    if not file_id:
        print("  ERROR: Could not find file input in modal", file=sys.stderr)
        return False

    # Fill in the recording name
    await page.evaluate(f"""
        () => {{
            const el = document.getElementById('{text_id}');
            el.value = {repr(recording_name)};
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
        }}
    """)
    await page.wait_for_timeout(300)

    # Uncheck all Users except Ray — find checkboxes in the Users section
    # Users section labels contain the username as text next to the checkbox
    await page.evaluate("""
        () => {
            // Find all visible checkboxes and their associated labels
            const checks = [...document.querySelectorAll('input[type=checkbox]')]
                .filter(el => el.offsetParent !== null);
            checks.forEach(cb => {
                // Get label text: check nextSibling text or parent label
                const label = cb.closest('label') ||
                              document.querySelector(`label[for='${cb.id}']`);
                const text = label ? label.textContent.trim() : '';
                // Uncheck everyone except Ray; skip non-user checkboxes (Active, Pinned, etc.)
                const userKeywords = ['Ben','Buck','Don','Donna','Kyle','Sound','Ray'];
                const isUser = userKeywords.some(k => text.startsWith(k));
                if (isUser) {
                    const shouldCheck = text.startsWith('Ray');
                    if (cb.checked !== shouldCheck) {
                        cb.click();
                    }
                }
            });
        }
    """)
    await page.wait_for_timeout(300)

    # Upload file — use Playwright file chooser triggered by clicking the file input
    async with page.expect_file_chooser() as fc_info:
        await page.evaluate(f"document.getElementById('{file_id}').click()")
    fc = await fc_info.value
    await fc.set_files(file_path)
    await page.wait_for_timeout(1000)

    # Click Save — find visible link/button with text 'Save'
    saved = await page.evaluate("""
        () => {
            const all = [...document.querySelectorAll('a, button')];
            const visible = all.filter(el => el.offsetParent !== null);
            const save = visible.find(el => el.textContent.trim() === 'Save');
            if (save) { save.click(); return true; }
            return false;
        }
    """)
    if not saved:
        print("  ERROR: Could not find Save button in modal", file=sys.stderr)
        return False

    # Wait for upload to complete (file upload can be slow)
    await page.wait_for_timeout(6000)
    print(f"  Uploaded: {recording_name}")
    return True



async def add_midi_preset(page, preset_name: str) -> bool:
    """
    Create a new MIDI preset with just a name, attached to the current song.
    Flow: click Add MIDI Presets -> New MIDI Preset -> fill name -> Save #1
          (returns to checklist with new preset auto-checked) -> Save #2 (attaches)
    Ray is already checked by default in BandHelper — no checkbox manipulation needed.
    """
    print(f"  Creating MIDI preset: {preset_name}")

    # Step 1: Open 'Add MIDI Presets' modal
    clicked = await page.evaluate("""
        () => {
            const all = [...document.querySelectorAll('a')];
            const found = all.find(a => a.textContent.trim() === 'Add MIDI Presets');
            if (found) { found.click(); return true; }
            return false;
        }
    """)
    if not clicked:
        print("  ERROR: 'Add MIDI Presets' link not found", file=sys.stderr)
        return False
    await page.wait_for_timeout(2000)

    # Step 2: Click 'New MIDI Preset' button
    clicked2 = await page.evaluate("""
        () => {
            const all = [...document.querySelectorAll('a, button')]
                .filter(el => el.offsetParent !== null);
            const btn = all.find(el => el.textContent.trim() === 'New MIDI Preset');
            if (btn) { btn.click(); return true; }
            return false;
        }
    """)
    if not clicked2:
        print("  ERROR: 'New MIDI Preset' button not found", file=sys.stderr)
        return False
    await page.wait_for_timeout(2000)

    # Step 3: Fill in the Name field (first visible text input)
    name_id = await page.evaluate("""
        () => {
            const vis = [...document.querySelectorAll('input[type=text]')]
                .filter(el => el.offsetParent !== null);
            return vis.length > 0 ? vis[0].id : null;
        }
    """)
    if not name_id:
        print("  ERROR: Name field not found", file=sys.stderr)
        return False

    await page.evaluate(f"""
        () => {{
            const el = document.getElementById('{name_id}');
            el.value = {repr(preset_name)};
            el.dispatchEvent(new Event('input', {{bubbles:true}}));
            el.dispatchEvent(new Event('change', {{bubbles:true}}));
        }}
    """)
    await page.wait_for_timeout(500)

    # Step 4: Save #1 — use Playwright locator to click the Save link reliably
    # Find Save by text, clicking the one that's inside the visible modal area
    try:
        save_link = page.locator('a', has_text='Save').first
        await save_link.click(timeout=5000)
    except Exception as e:
        print(f"  ERROR: Save #1 failed: {e}", file=sys.stderr)
        return False
    await page.wait_for_timeout(2500)

    # Step 5: Save #2 — now on the checklist modal with preset auto-checked
    # New preset is at top of list, already checked — just click Save to attach
    try:
        save_link2 = page.locator('a', has_text='Save').first
        await save_link2.click(timeout=5000)
    except Exception as e:
        print(f"  ERROR: Save #2 failed: {e}", file=sys.stderr)
        return False
    await page.wait_for_timeout(2000)

    print(f"  MIDI preset created and attached: {preset_name}")
    return True


async def save_song(page) -> bool:
    """Submit the song edit form."""
    try:
        await page.evaluate("() => submit_form('song_edit')")
        await page.wait_for_timeout(3000)
        print(f"  Saved. URL: {page.url}")
        return True
    except Exception as e:
        # Fallback: click save button
        try:
            save_btn = page.locator("input[type='submit'][value*='Save'], button:has-text('Save')").first
            await save_btn.click()
            await page.wait_for_timeout(3000)
            return True
        except Exception as e2:
            print(f"  ERROR saving: {e2}", file=sys.stderr)
            return False


async def upload_lyrics(song_title: str, content: str,
                        account: str, username: str, password: str,
                        dry_run: bool = False) -> bool:
    from config import BH_ACCOUNT, BH_USERNAME, BH_PASSWORD
    account  = account  or BH_ACCOUNT
    username = username or BH_USERNAME
    password = password or BH_PASSWORD

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page    = await browser.new_page()

        print("Logging in to BandHelper...")
        if not await login(page, account, username, password):
            await browser.close()
            return False

        print(f"Searching for song: {song_title}")
        song_url = await find_song(page, song_title)
        if not song_url:
            await browser.close()
            return False

        # Navigate to edit page
        # Convert view URL to edit URL if needed
        if "song_edit" not in song_url:
            song_id = re.search(r'[?&]ID=([^&]+)', song_url)
            if song_id:
                song_url = f"{BH_EDIT_URL}?ID={song_id.group(1)}"
            else:
                song_url = song_url.replace("song_view", "song_edit")

        print(f"Opening edit page: {song_url}")
        await page.goto(song_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        # Show current content status
        current = await get_personal_lyrics(page)
        if current and current.strip() and len(current.strip()) > 10:
            print(f"  Personal Lyrics: has content ({len(current)} chars)")
        else:
            print("  Personal Lyrics: empty")

        if dry_run:
            print("\n--- DRY RUN: Would write this content ---")
            print(content[:500])
            print("--- (not saving) ---")
            input("\nPress Enter to close browser...")
            await browser.close()
            return True

        # SAFETY: Never overwrite existing Personal Lyrics
        current = await get_personal_lyrics(page)
        if current and current.strip() and len(current.strip()) > 10:
            print(f"\nSKIPPED: Personal Lyrics already has content ({len(current)} chars).")
            print("  Delete the existing lyrics in BandHelper first if you want to replace them.")
            await browser.close()
            return False

        # Write content (only if empty)
        print("Personal Lyrics is empty. Writing chord sheet...")
        if not await set_personal_lyrics(page, content):
            await browser.close()
            return False

        # Save
        print("Saving...")
        ok = await save_song(page)
        await browser.close()
        return ok


def main():
    p = argparse.ArgumentParser(description="BandHelper automation — upload lyrics or recordings")
    p.add_argument("--song",      required=True, help="Song title (must match BandHelper exactly)")
    p.add_argument("--file",      help="Chord sheet text file (for --lyrics mode)")
    p.add_argument("--learning",  help="Path to learning mixdown MP3")
    p.add_argument("--practice",  help="Path to practice mixdown MP3")
    p.add_argument("--dry-run",   action="store_true", help="Preview without saving")
    p.add_argument("--account",   default="", help="BandHelper account (default: from config)")
    p.add_argument("--username",  default="", help="BandHelper username (default: from config)")
    p.add_argument("--password",  default="", help="BandHelper password (default: from config)")
    args = p.parse_args()

    from config import BH_ACCOUNT, BH_USERNAME, BH_PASSWORD
    account  = args.account  or BH_ACCOUNT
    username = args.username or BH_USERNAME
    password = args.password or BH_PASSWORD

    # Mode: upload recordings (mixdowns)
    if args.learning or args.practice:
        async def run_recordings():
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=False)
                page    = await browser.new_page()
                print("Logging in to BandHelper...")
                if not await login(page, account, username, password):
                    await browser.close()
                    return False
                print(f"Finding song: {args.song}")
                song_url = await find_song(page, args.song)
                if not song_url:
                    await browser.close()
                    return False
                if "song_edit" not in song_url:
                    song_id = re.search(r'ID=([^&]+)', song_url)
                    if song_id:
                        song_url = f"{BH_EDIT_URL}?ID={song_id.group(1)}"
                await page.goto(song_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)

                if args.learning:
                    name = f"{args.song} - Learning"
                    if args.dry_run:
                        print(f"DRY RUN: Would upload '{name}' from {args.learning}")
                    else:
                        await upload_recording(page, args.learning, name)

                if args.practice:
                    name = f"{args.song} - Practice"
                    if args.dry_run:
                        print(f"DRY RUN: Would upload '{name}' from {args.practice}")
                    else:
                        await upload_recording(page, args.practice, name)

                await browser.close()
                return True

        ok = asyncio.run(run_recordings())
        sys.exit(0 if ok else 1)

    # Mode: upload lyrics
    if not args.file:
        print("ERROR: Provide --file for lyrics or --learning/--practice for recordings", file=sys.stderr)
        sys.exit(1)

    content = Path(args.file).read_text(encoding="utf-8")
    if not content.strip():
        print("ERROR: Chord file is empty.", file=sys.stderr)
        sys.exit(1)

    ok = asyncio.run(upload_lyrics(
        song_title=args.song,
        content=content,
        account=account,
        username=username,
        password=password,
        dry_run=args.dry_run,
    ))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
