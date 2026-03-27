"""
ug_fetch.py — Fetch chord sheet from Ultimate Guitar mobile API

Uses the reverse-engineered UG Android app API — no Cloudflare, no browser.
Your paid account gives access to Pro/Official tabs.

API base: https://api.ultimate-guitar.com/api/v1
Auth:     PUT /auth/login?username=...&password=...
Tab:      GET /tab/info?tab_id=...
Search:   GET /tab/search?title=...&type[]=300&type[]=800

Usage:
    python ug_fetch.py --artist "Doobie Brothers" --song "China Grove"
    python ug_fetch.py --artist "ELO" --song "Telephone Line" --output elo.txt
    python ug_fetch.py --url "https://tabs.ultimate-guitar.com/tab/the-doobie-brothers/china-grove-chords-15114"
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── API constants (from reverse-engineered Android app) ──────────────────────
UG_API_BASE  = "https://api.ultimate-guitar.com/api/v1"
UG_UA        = "UGT_ANDROID/5.10.0 (Pixel 4; Android 11)"

SEPARATOR    = "_______________________________________________"
SCROLL_LINES = 5

# Tab type IDs: 300=chords, 400=tab, 800=official
PREFERRED_TYPES = [300, 800, 400]


# ── Auth header generation ────────────────────────────────────────────────────

def generate_device_id() -> str:
    """16 hex char random device ID."""
    return secrets.token_hex(8)[:16]


def generate_api_key(device_id: str) -> str:
    """
    X-UG-API-KEY = MD5(deviceID + "YYYY-MM-DD" + ":" + UTChour + "createLog()")
    Rotates every hour.
    """
    now  = datetime.now(timezone.utc)
    date = now.strftime("%Y-%m-%d")
    hour = now.hour
    raw  = f"{device_id}{date}:{hour}createLog()"
    return hashlib.md5(raw.encode()).hexdigest()


def make_headers(device_id: str, token: str = None) -> dict:
    headers = {
        "Accept-Charset": "utf-8",
        "Accept":         "application/json",
        "User-Agent":     UG_UA,
        "Connection":     "close",
        "X-UG-CLIENT-ID": device_id,
        "X-UG-API-KEY":   generate_api_key(device_id),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def api_get(path: str, params: dict, headers: dict) -> dict | None:
    query = urllib.parse.urlencode(params, doseq=True)
    url   = f"{UG_API_BASE}{path}?{query}"
    req   = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        print(f"  HTTP {e.code} on {path}: {body[:200]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Error on {path}: {e}", file=sys.stderr)
        return None


def api_put(path: str, params: dict, headers: dict) -> dict | None:
    query = urllib.parse.urlencode(params)
    url   = f"{UG_API_BASE}{path}?{query}"
    req   = urllib.request.Request(url, headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        print(f"  HTTP {e.code} on {path}: {body[:200]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Error on {path}: {e}", file=sys.stderr)
        return None


# ── Login ─────────────────────────────────────────────────────────────────────

def login(device_id: str, username: str, password: str) -> str | None:
    """Login and return auth token."""
    headers = make_headers(device_id)
    result  = api_put("/auth/login",
                      {"username": username, "password": password},
                      headers)
    if result and "token" in result:
        return result["token"]
    print(f"  Login failed: {result}", file=sys.stderr)
    return None


# ── Search ────────────────────────────────────────────────────────────────────

def search_tabs(artist: str, song: str, device_id: str, token: str = None) -> list[dict]:
    """Search UG API for chord tabs matching artist + song."""
    headers = make_headers(device_id, token)
    query   = f"{artist} {song}"
    # No type filter — let API return all types so Official tabs aren't excluded
    params  = {
        "title": query,
        "page":  1,
    }
    result = api_get("/tab/search", params, headers)
    if not result:
        return []
    tabs = result.get("tabs", [])
    # Filter to only chord/official/pro types — exclude bass tabs, drums, etc.
    wanted = {"chords", "official", "pro", "tabs"}
    return [t for t in tabs if (t.get("type") or "").lower() in wanted]


def pick_best_tab(tabs: list[dict]) -> dict | None:
    """Pick highest quality tab: Official > Chords, sorted by votes."""
    if not tabs:
        return None
    def score(t):
        # Use 'type' field (not 'type_name' which is always None from API)
        tab_type = (t.get("type") or "").lower()
        type_score = 3 if tab_type == "official" else (2 if tab_type == "pro" else (1 if tab_type == "chords" else 0))
        return (type_score, int(t.get("votes") or 0), float(t.get("rating") or 0))
    best = sorted(tabs, key=score, reverse=True)[0]
    return best


# ── Tab content fetching ──────────────────────────────────────────────────────

def fetch_tab_by_id(tab_id: int, device_id: str, token: str = None) -> dict | None:
    headers = make_headers(device_id, token)
    return api_get("/tab/info",
                   {"tab_id": tab_id, "tab_access_type": "public"},
                   headers)


def fetch_tab_by_url(tab_url: str, device_id: str, token: str = None) -> dict | None:
    headers = make_headers(device_id, token)
    return api_get("/tab/url",
                   {"url": urllib.parse.quote(tab_url, safe="")},
                   headers)


def extract_tab_id_from_url(url: str) -> int | None:
    """Extract numeric tab ID from a UG URL like .../china-grove-chords-15114"""
    m = re.search(r'-(\d+)$', url.rstrip('/').split('?')[0])
    return int(m.group(1)) if m else None


# ── Content parsing ───────────────────────────────────────────────────────────

def parse_content(raw: str) -> str:
    """
    Convert UG mobile API content format to Ray's ChordPro style.
    
    UG format:
      [ch]Am[/ch]  → [Am]
      [tab]...[/tab] → stripped
      [Verse 1] / [Chorus] → section labels
    """
    # Convert [ch]X[/ch] → [X]
    content = re.sub(r'\[ch\]([^\[]+?)\[/ch\]', r'[\1]', raw)
    # Remove [tab] wrappers
    content = re.sub(r'\[/?tab\]', '', content)
    return content.strip()


def format_to_chordpro(content: str) -> str:
    """
    Format parsed UG content into Ray's ChordPro style with separators.
    """
    SECTION_RE = re.compile(
        r'^\[?(intro|verse\s*\d*|pre.?chorus|chorus|bridge|outro|solo|break|'
        r'interlude|instrumental|hook|coda|tag|refrain)\]?\s*$',
        re.IGNORECASE
    )

    lines = content.splitlines()
    sections = []
    current_label = None
    current_lines = []
    verse_counter = 0

    for line in lines:
        line = line.rstrip()
        m = SECTION_RE.match(line.strip())
        if m:
            if current_label is not None or any(l.strip() for l in current_lines):
                sections.append((current_label, list(current_lines)))
            label = line.strip().strip('[]')
            # Normalize verse numbering
            if re.match(r'^verse\s*$', label, re.I):
                verse_counter += 1
                label = f"Verse {verse_counter}"
            current_label = label.title()
            current_lines = []
        else:
            current_lines.append(line)

    if current_label is not None or any(l.strip() for l in current_lines):
        sections.append((current_label, list(current_lines)))

    # Render
    parts = []
    for label, content_lines in sections:
        while content_lines and not content_lines[0].strip():
            content_lines.pop(0)
        while content_lines and not content_lines[-1].strip():
            content_lines.pop()
        if not content_lines and not label:
            continue
        block = [SEPARATOR]
        if label:
            block.append(label)
        block.extend(content_lines)
        parts.append('\n'.join(block))

    result = '\n'.join(parts).rstrip()
    result += f'\n{SEPARATOR}\n{SEPARATOR}\n'
    result += '\n' * SCROLL_LINES
    return result


# ── Main entry point ──────────────────────────────────────────────────────────

def fetch_chord_sheet(artist: str = None, song: str = None,
                      url: str = None) -> str:
    from config import UG_EMAIL, UG_PASSWORD

    device_id = generate_device_id()
    print(f"Logging in to UG as {UG_EMAIL}...")
    token = login(device_id, UG_EMAIL, UG_PASSWORD)
    if token:
        print("  Login OK.")
    else:
        print("  Login failed — trying without auth (free tabs only).")

    # Get tab data
    tab_data = None

    if url:
        tab_id = extract_tab_id_from_url(url)
        if tab_id:
            print(f"Fetching tab ID: {tab_id}")
            tab_data = fetch_tab_by_id(tab_id, device_id, token)
        if not tab_data:
            print(f"Fetching by URL: {url}")
            tab_data = fetch_tab_by_url(url, device_id, token)
    else:
        print(f"Searching: {artist} — {song}")
        tabs = search_tabs(artist, song, device_id, token)
        if not tabs:
            print("ERROR: No results found.", file=sys.stderr)
            return ""
        best = pick_best_tab(tabs)
        print(f"  Best match: {best.get('song_name')} by {best.get('artist_name')} "
              f"({best.get('type')}, {best.get('votes')} votes, id={best.get('id')})")
        tab_data = fetch_tab_by_id(best["id"], device_id, token)

    if not tab_data:
        print("ERROR: Could not fetch tab data.", file=sys.stderr)
        return ""

    # Extract content
    # Content can be at top level, or nested in tab_view.wiki_tab
    raw_content = (
        tab_data.get("content")  # top-level (community + official tabs)
        or (tab_data.get("tab_view") or {}).get("wiki_tab", {}).get("content")  # nested
        or ""
    )

    # If no content (Official tabs often gate content), fall back to best Chords tab
    if not raw_content and not url:
        chords_tabs = [t for t in tabs if (t.get("type") or "").lower() == "chords"]
        if chords_tabs:
            fallback = sorted(chords_tabs, key=lambda t: int(t.get("votes") or 0), reverse=True)[0]
            print(f"  No content in Official tab — falling back to Chords tab (id={fallback['id']}, {fallback.get('votes')} votes)...")
            tab_data = fetch_tab_by_id(fallback["id"], device_id, token) or {}
            raw_content = tab_data.get("content") or ""

    if not raw_content:
        print("ERROR: No content in tab response.", file=sys.stderr)
        print(f"  Keys available: {list(tab_data.keys())}", file=sys.stderr)
        return ""

    parsed    = parse_content(raw_content)
    formatted = format_to_chordpro(parsed)
    return formatted


def main():
    parser = argparse.ArgumentParser(description="Fetch chords from Ultimate Guitar mobile API")
    parser.add_argument("--artist", help="Artist name")
    parser.add_argument("--song",   help="Song title")
    parser.add_argument("--url",    help="Direct UG tab URL")
    parser.add_argument("--output", help="Save to file (default: print to screen)")
    args = parser.parse_args()

    if not args.url and not (args.artist and args.song):
        print("ERROR: Provide --url or both --artist and --song", file=sys.stderr)
        sys.exit(1)

    result = fetch_chord_sheet(artist=args.artist, song=args.song, url=args.url)

    if result:
        if args.output:
            Path(args.output).write_text(result, encoding="utf-8")
            print(f"Saved to {args.output}")
        else:
            print(result)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
