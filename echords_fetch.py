"""
echords_fetch.py — Fetch chord sheet from e-chords.com

No browser automation needed. Raw HTML contains chord/lyric content as plain text.
Uses simple HTTP request + BeautifulSoup parsing.

URL format: https://www.e-chords.com/chords/{artist-slug}/{song-slug}

Usage:
    python echords_fetch.py --artist "Electric Light Orchestra" --song "Telephone Line"
    python echords_fetch.py --artist "Doobie Brothers" --song "China Grove"
    python echords_fetch.py --url "https://www.e-chords.com/chords/electric-light-orchestra/telephone-line"
    python echords_fetch.py --artist "ELO" --song "Telephone Line" --output formatted.txt
"""

import argparse
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

try:
    from autoupdate import check_for_updates
    check_for_updates()
except Exception:
    pass  # never block the main script

SEPARATOR = "_______________________________________________"
SCROLL_LINES = 5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Known section labels e-chords uses
SECTION_RE = re.compile(
    r'^(Intro|Verse\s*\d*|Pre-?Chorus|Chorus|Bridge|Outro|Solo|Break|Interlude|'
    r'Hook|Coda|Tag|Refrain|Tab\s*-?\s*Chords?|Instrumental|Fill|Synth.*)[\s:]*$',
    re.IGNORECASE
)

# Chord pattern — a word that looks like a chord
CHORD_TOKEN_RE = re.compile(
    r'\b([A-G][b#]?(?:maj|min|m|M|dim|aug|sus|add)?(?:\d+)?(?:/[A-G][b#]?)?)\b'
)


# ── URL builder ───────────────────────────────────────────────────────────────

def slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r'^the\s+', '', s)
    s = s.replace("'", "").replace("&", "and")
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')


def build_url(artist: str, song: str) -> str:
    return f"https://www.e-chords.com/chords/{slugify(artist)}/{slugify(song)}"


# ── HTTP fetch ────────────────────────────────────────────────────────────────

def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} fetching {url}", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"Error fetching {url}: {e}", file=sys.stderr)
        return ""


# ── Content extraction ────────────────────────────────────────────────────────

def extract_content(html: str) -> str:
    """
    Extract the chord/lyric text from e-chords raw HTML.

    e-chords embeds the content in a <pre id="core"> block.
    Chords appear as <span data-chord="X">X</span> inline with lyrics.
    In the raw HTML source this is plain text with spans.
    """
    # Try <pre id="core"> first
    m = re.search(r'<pre[^>]*id=["\']core["\'][^>]*>(.*?)</pre>', html, re.DOTALL)
    if not m:
        # Fallback: any <pre> block with chord spans
        m = re.search(r'<pre[^>]*>(.*?)</pre>', html, re.DOTALL)
    if not m:
        print("ERROR: Could not find chord content in page HTML.", file=sys.stderr)
        return ""

    raw = m.group(1)

    # Convert <span data-chord="X">...</span> → [X]
    raw = re.sub(
        r'<span[^>]*data-chord=["\']([^"\']*)["\'][^>]*>[^<]*</span>',
        lambda m: f'[{m.group(1).split()[0]}]',
        raw
    )

    # Strip remaining HTML tags
    raw = re.sub(r'<[^>]+>', '', raw)

    # Decode HTML entities
    raw = (raw
        .replace('&amp;', '&').replace('&lt;', '<')
        .replace('&gt;', '>').replace('&quot;', '"')
        .replace('&#39;', "'").replace('&nbsp;', ' '))

    return raw.strip()


# ── ChordPro formatter ────────────────────────────────────────────────────────

CHORD_RE = re.compile(r'\[([A-G][^\]]*)\]')


def is_chord_only(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    without = CHORD_RE.sub('', stripped)
    without = re.sub(r'\(\s*x\d+\s*\)|\bx\d+\b', '', without)
    return without.strip() == ''


def is_section_header(line: str) -> bool:
    return bool(SECTION_RE.match(line.strip()))


def is_tab_header(line: str) -> bool:
    return bool(re.match(r'^(Tab\s*-?\s*Chords?|TAB|Chords?:?\s*$)', line.strip(), re.I))


def merge_chords_into_lyrics(chord_line: str, lyric_line: str) -> str:
    """Insert chords from chord_line inline into lyric_line at correct columns."""
    positions = []
    bracket_width = 0
    for m in CHORD_RE.finditer(chord_line):
        col = m.start() - bracket_width
        positions.append((col, m.group(0)))
        bracket_width += len(m.group(0))

    if not positions:
        return lyric_line

    lyric = lyric_line
    max_col = max(c for c, _ in positions)
    if len(lyric) < max_col:
        lyric += ' ' * (max_col - len(lyric))

    for col, chord in reversed(positions):
        pos = min(max(col, 0), len(lyric))
        lyric = lyric[:pos] + chord + lyric[pos:]

    return lyric.rstrip()


def section_has_chords(content: list[str]) -> bool:
    return any(CHORD_RE.search(line) for line in content)


def lyric_words(content: list[str]) -> list[str]:
    """Extract plain lyric words from a section (no chords) for similarity comparison."""
    words = []
    for line in content:
        plain = CHORD_RE.sub('', line).strip()
        if plain:
            words.extend(plain.lower().split())
    return words


def section_similarity(a: list[str], b: list[str]) -> float:
    """Rough similarity score between two sections based on line count and word overlap."""
    # Line count similarity
    lyric_a = [l for l in a if CHORD_RE.sub('', l).strip()]
    lyric_b = [l for l in b if CHORD_RE.sub('', l).strip()]
    if not lyric_a or not lyric_b:
        return 0.0
    line_ratio = min(len(lyric_a), len(lyric_b)) / max(len(lyric_a), len(lyric_b))
    return line_ratio


def apply_chord_pattern(source: list[str], target: list[str]) -> list[str]:
    """
    Copy chord pattern from source lines onto target lyric lines.
    Matches source and target line-by-line (skipping blank lines).
    For each source line with chords, applies those chords to the
    corresponding target lyric line at the same relative positions.
    """
    # Get non-blank lyric lines from source (with chords) and target (without)
    src_lines = [l for l in source if CHORD_RE.sub('', l).strip() or CHORD_RE.search(l)]
    tgt_lines = [l for l in target if l.strip()]

    if not src_lines:
        return target

    result = list(target)
    tgt_idx = 0  # index into non-blank target lines
    tgt_positions = [i for i, l in enumerate(result) if l.strip()]

    for src_line in src_lines:
        if tgt_idx >= len(tgt_positions):
            break
        if not CHORD_RE.search(src_line):
            tgt_idx += 1
            continue

        # Extract just the chord positions from the source line
        chord_only = CHORD_RE.sub(lambda m: m.group(0), src_line)
        # Build a chord-only version for merging
        chord_marker_line = re.sub(r'[^\[\]A-Za-z0-9#b/ ]', ' ', src_line)
        chord_marker_line = re.sub(r'(?<=\])([^\[])', lambda m: ' ' * len(m.group(1)), chord_marker_line)

        tgt_pos = tgt_positions[tgt_idx]
        tgt_lyric = result[tgt_pos]
        # Strip any existing chords from target line first
        tgt_lyric_clean = CHORD_RE.sub('', tgt_lyric).strip()
        # Merge source chords into target lyric
        merged = merge_chords_into_lyrics(src_line, tgt_lyric_clean)
        result[tgt_pos] = merged
        tgt_idx += 1

    return result


def complete_missing_chords(sections: list[tuple]) -> list[tuple]:
    """
    For any section with no chords, find the most similar previous section
    that has chords and copy the chord pattern onto the bare lyrics.
    Prints a note when it does this.
    """
    completed = []
    for i, (label, content) in enumerate(sections):
        if section_has_chords(content):
            completed.append((label, content))
            continue

        # Find best matching previous section with chords
        best_score = 0.0
        best_source = None
        for prev_label, prev_content in completed:
            if not section_has_chords(prev_content):
                continue
            score = section_similarity(prev_content, content)
            if score > best_score:
                best_score = score
                best_source = prev_content

        if best_source and best_score >= 0.5:
            filled = apply_chord_pattern(best_source, content)
            print(f"  Pattern completion: filled chords into section '{label or i}' "
                  f"(similarity {best_score:.0%})", file=sys.stderr)
            completed.append((label, filled))
        else:
            completed.append((label, content))

    return completed


def format_to_chordpro(raw: str) -> str:
    """Convert raw e-chords text to Ray's ChordPro format."""
    lines = raw.splitlines()

    # ── Pass 1: Remove TAB section and clean ─────────────────────────────────
    cleaned = []
    skip_tab = False
    for line in lines:
        line = line.rstrip()
        if is_tab_header(line):
            skip_tab = True
            continue
        if skip_tab:
            continue
        cleaned.append(line)

    # ── Pass 2: Strip leading whitespace + collapse multiple blank lines ──────
    collapsed = []
    prev_blank = False
    for line in cleaned:
        line = line.lstrip()  # remove indentation from source formatting
        is_blank = not line.strip()
        if is_blank and prev_blank:
            continue
        collapsed.append(line)
        prev_blank = is_blank

    # ── Pass 3: Merge chord-above-lyric pairs ─────────────────────────────────
    merged = []
    i = 0
    while i < len(collapsed):
        line = collapsed[i]
        if is_chord_only(line) and i + 1 < len(collapsed):
            next_line = collapsed[i + 1]
            if (next_line.strip()
                    and not CHORD_RE.search(next_line)
                    and not is_section_header(next_line)):
                merged.append(merge_chords_into_lyrics(line, next_line))
                i += 2
                continue
        merged.append(line)
        i += 1

    # ── Pass 4: Build sections ────────────────────────────────────────────────
    sections = []
    current_label = None
    current_lines = []
    verse_counter = 0

    for line in merged:
        if is_section_header(line):
            if current_label is not None or any(l.strip() for l in current_lines):
                sections.append((current_label, list(current_lines)))
            label = line.strip().rstrip(':').strip()
            # Normalize verse numbering
            if re.match(r'^verse\s*$', label, re.I):
                verse_counter += 1
                label = f"Verse {verse_counter}"
            elif re.match(r'^verse\s*(\d+)$', label, re.I):
                verse_counter = int(re.search(r'\d+', label).group())
                label = f"Verse {verse_counter}"
            current_label = label.title()
            current_lines = []
        else:
            current_lines.append(line)

    if current_label is not None or any(l.strip() for l in current_lines):
        sections.append((current_label, list(current_lines)))

    # ── Pass 5: Pattern completion ───────────────────────────────────────────
    sections = complete_missing_chords(sections)

    # ── Pass 6: Render ───────────────────────────────────────────────────────
    parts = []
    for label, content in sections:
        while content and not content[0].strip():
            content.pop(0)
        while content and not content[-1].strip():
            content.pop()
        if not content and not label:
            continue

        block = [SEPARATOR]
        if label:
            block.append(label)
        block.extend(content)
        parts.append('\n'.join(block))

    result = '\n'.join(parts)
    result = result.rstrip()
    result += f'\n{SEPARATOR}\n{SEPARATOR}\n'
    result += '\n' * SCROLL_LINES

    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def fetch_chord_sheet(artist: str = None, song: str = None, url: str = None) -> str:
    if not url:
        url = build_url(artist, song)
    print(f"Fetching: {url}")

    html = fetch_html(url)
    if not html:
        return ""

    raw = extract_content(html)
    if not raw:
        return ""

    return format_to_chordpro(raw)


def main():
    parser = argparse.ArgumentParser(description="Fetch chords from e-chords.com")
    parser.add_argument("--artist", help="Artist name")
    parser.add_argument("--song",   help="Song title")
    parser.add_argument("--url",    help="Direct e-chords URL")
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
