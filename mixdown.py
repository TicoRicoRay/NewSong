"""
mixdown.py — Create two mixdowns from a folder of stems

Mix A (Learning):  keys +6dB, everything else 0dB
Mix B (Practice):  keys muted, everything else 0dB

Key stem classification by filename:
  Keys:       Piano, Organ, Synth, Keys, Keyboard, Electric_Piano,
              Brass, Horn, Trumpet, Sax, Saxophone, Flute, Woodwind,
              Strings, Violin, Cello, Viola, Orchestra, String, Harp,
              Harmonica, Accordion, Bandoneon
  Drums:      Drum, Percussion, Tambourine, Cowbell, Shaker, Hi_Hat,
              Cymbal, Snare, Kick, Clap, Beat
  Everything else: Guitar, Bass, Vocal, Voice, Background, Backing, etc.

Usage:
    python mixdown.py --artist "Doobie Brothers" --song "China Grove"
    python mixdown.py --folder "C:\\Users\\myers\\Dropbox\\_Tracks\\Doobie_Brothers-China_Grove"
    python mixdown.py --folder "..." --no-learning   # practice mix only
    python mixdown.py --folder "..." --no-practice   # learning mix only

Requirements:
    ffmpeg must be installed: https://ffmpeg.org/download.html
    Windows: winget install ffmpeg   OR   choco install ffmpeg
    No Python audio packages needed.
"""

import argparse
import os
import re
import sys
from pathlib import Path

try:
    from autoupdate import check_for_updates
    check_for_updates()
except Exception:
    pass  # never block the main script

# Key volume adjustments
KEYS_LEARNING_DB = +6.0   # keys louder in learning mix
KEYS_PRACTICE_DB = None   # None = muted in practice mix

# ── Stem classification ────────────────────────────────────────────────────────

KEYS_KEYWORDS = {
    "piano", "organ", "synth", "keys", "keyboard", "electric_piano",
    "brass", "horn", "trumpet", "trombone", "sax", "saxophone",
    "flute", "woodwind", "clarinet", "oboe", "bassoon",
    "strings", "string", "violin", "cello", "viola", "orchestra",
    "harp", "harmonica", "accordion", "bandoneon", "mellotron",
    "pad", "choir", "choral",  # synth pads/choir often played by keys
}

DRUMS_KEYWORDS = {
    "drum", "percussion", "tambourine", "cowbell", "shaker",
    "hi_hat", "hihat", "cymbal", "snare", "kick", "clap",
    "beat", "bongo", "conga", "timbale",
}


def classify_stem(filename: str) -> str:
    """
    Returns 'keys', 'drums', or 'other' based on filename.
    Uses the stem name (without NN_ prefix and .mp3 extension).
    """
    # Strip sequence number prefix (e.g. "03_") and extension
    name = Path(filename).stem
    name = re.sub(r'^\d+_', '', name).lower()

    for kw in KEYS_KEYWORDS:
        if kw in name:
            return 'keys'
    for kw in DRUMS_KEYWORDS:
        if kw in name:
            return 'drums'
    return 'other'


def print_classification(stems: list[Path]):
    """Print stem classification for user review."""
    print("\nStem classification:")
    print(f"  {'File':<45} {'Role'}")
    print(f"  {'-'*45} ------")
    for stem in sorted(stems):
        role = classify_stem(stem.name)
        marker = "🎹 KEYS" if role == 'keys' else ("🥁 drums" if role == 'drums' else "   other")
        print(f"  {stem.name:<45} {marker}")
    print()


# ── Audio mixing ───────────────────────────────────────────────────────────────

def find_ffmpeg() -> str:
    """Find ffmpeg executable."""
    import shutil
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    for path in [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
        os.path.expandvars(r"%USERPROFILE%\ffmpeg\bin\ffmpeg.exe"),
    ]:
        if os.path.exists(path):
            return path
    return ""


def check_ffmpeg() -> str:
    """Return ffmpeg path or empty string."""
    return find_ffmpeg()


def mix_stems(stems: list[Path], keys_db: float | None, output_path: Path,
              keys_set: set = None):
    """
    Mix stems using ffmpeg amix filter.
    keys_db:  float = volume adjustment in dB, None = mute keys entirely.
    keys_set: set of Path objects pre-identified as keys (overrides classify_stem).
    """
    import subprocess
    import tempfile

    ffmpeg = find_ffmpeg()

    def is_keys(stem: Path) -> bool:
        if keys_set is not None:
            return stem in keys_set
        return classify_stem(stem.name) == 'keys'

    # Build input list — exclude keys entirely for practice mix
    active_stems = []
    for stem in sorted(stems):
        role = 'keys' if is_keys(stem) else 'other'
        if role == 'keys' and keys_db is None:
            print(f"  Excluding (muted): {stem.name}")
            continue
        active_stems.append((stem, role))

    n = len(active_stems)
    if n == 0:
        print("  WARNING: No stems to mix.", file=sys.stderr)
        return False

    # Build ffmpeg command
    inputs = []
    filter_parts = []
    amix_inputs = []

    for idx, (stem, role) in enumerate(active_stems):
        inputs += ["-i", str(stem)]
        if role == 'keys' and keys_db and keys_db != 0:
            filter_parts.append(f"[{idx}:a]volume={keys_db}dB[v{idx}]")
            amix_inputs.append(f"[v{idx}]")
        else:
            amix_inputs.append(f"[{idx}:a]")

    # Mix using amerge then convert to stereo
    # This is more reliable than amix for stem mixing
    if len(filter_parts) > 0:
        # Has volume adjustments — use amix
        amix = f"{''.join(amix_inputs)}amix=inputs={n}:normalize=0[out]"
        filter_complex = ";".join(filter_parts + [amix])
    else:
        # No adjustments — sum inputs directly
        amix = f"{''.join(amix_inputs)}amix=inputs={n}:normalize=0[out]"
        filter_complex = amix

    cmd = [
        ffmpeg, "-y"
    ] + inputs + [
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "libmp3lame",
        "-b:a", "320k",
        str(output_path)
    ]

    print(f"  Mixing {n} stems...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  ERROR: {result.stderr[-500:]}", file=sys.stderr)
        return False

    size_kb = output_path.stat().st_size // 1024
    print(f"  Saved: {output_path.name} ({size_kb} KB)")
    return True


def create_mixdowns(folder: Path, make_learning: bool = True, make_practice: bool = True,
                    auto_confirm: bool = False, confirmed_keys: list = None):
    """
    Create learning and/or practice mixdowns from a stems folder.
    confirmed_keys: list of stem name strings (without path/extension) pre-confirmed
                    as keys by the user upfront in stems.py. If provided, skips prompt.
    """
    stems = sorted(folder.glob("*.mp3"))

    # Exclude any existing mixdown files
    stems = [s for s in stems if not any(
        tag in s.name for tag in ["_learning", "_practice", "_mix"]
    )]

    if not stems:
        print(f"ERROR: No .mp3 stems found in {folder}", file=sys.stderr)
        return False

    # If confirmed_keys provided, override auto-classification
    if confirmed_keys is not None:
        # Match by stem name fragment (case-insensitive)
        def is_confirmed_key(stem_path: Path) -> bool:
            name = stem_path.stem.lower()  # strip .mp3, lowercase
            return any(k.lower() in name or name in k.lower() for k in confirmed_keys)
        keys_stems = [s for s in stems if is_confirmed_key(s)]
        print(f"Keys stems (confirmed): {[s.name for s in keys_stems]}")
    else:
        print_classification(stems)
        keys_stems = [s for s in stems if classify_stem(s.name) == 'keys']
        print(f"Keys stems ({len(keys_stems)}): {[s.name for s in keys_stems]}")
        print()

        # Confirm with user unless auto_confirm
        if not auto_confirm:
            answer = input("Classifications look correct? (y/n): ").strip().lower()
            if answer == 'n':
                print("Aborting. Edit KEYS_KEYWORDS in mixdown.py to adjust classification.")
                return False

    print()

    # Build keys_set for mix_stems (set of Path objects)
    keys_set = set(keys_stems) if keys_stems else None

    success = True

    if make_learning:
        out = folder / f"{folder.name}_learning.mp3"
        print(f"\nMix A — Learning (keys +{KEYS_LEARNING_DB}dB):")
        success &= mix_stems(stems, KEYS_LEARNING_DB, out, keys_set=keys_set)

    if make_practice:
        out = folder / f"{folder.name}_practice.mp3"
        print(f"\nMix B — Practice (keys muted):")
        success &= mix_stems(stems, KEYS_PRACTICE_DB, out, keys_set=keys_set)

    return success


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Create learning + practice mixdowns from stems")
    p.add_argument("--artist",       help="Artist name (uses Dropbox _Tracks folder)")
    p.add_argument("--song",         help="Song title")
    p.add_argument("--folder",       help="Direct path to stems folder")
    p.add_argument("--no-learning",  action="store_true", help="Skip learning mix")
    p.add_argument("--no-practice",  action="store_true", help="Skip practice mix")
    args = p.parse_args()

    # Resolve folder
    if args.folder:
        folder = Path(args.folder)
    elif args.artist and args.song:
        from utils import build_dropbox_folder_name
        from config import DOWNLOADS_DIR
        folder_name = build_dropbox_folder_name(args.artist, args.song)
        folder = Path(DOWNLOADS_DIR) / folder_name
    else:
        print("ERROR: Provide --folder or both --artist and --song", file=sys.stderr)
        sys.exit(1)

    if not folder.exists():
        print(f"ERROR: Folder not found: {folder}", file=sys.stderr)
        sys.exit(1)

    # Check ffmpeg — only dependency needed
    ffmpeg = check_ffmpeg()
    if not ffmpeg:
        print("ERROR: ffmpeg not found.", file=sys.stderr)
        print("  Install: winget install ffmpeg", file=sys.stderr)
        print("  Or download from: https://ffmpeg.org/download.html", file=sys.stderr)
        sys.exit(1)
    print(f"ffmpeg: {ffmpeg}")

    print(f"\nCreating mixdowns for: {folder.name}")
    print()
    print(f"Source: {folder}")

    ok = create_mixdowns(
        folder,
        make_learning=not args.no_learning,
        make_practice=not args.no_practice,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
