"""
artist_normalize.py — Normalize artist names for KV search and folder naming

Handles:
  - KV disambiguation suffixes: "Heart (band)" → "Heart"
  - Common "The" handling: "The Bangles" → search as-is, folder as "Bangles_The"
  - Special characters: "AC/DC" → "ACDC" for folders, "AC/DC" for search
  - Ampersands: "Simon & Garfunkel" → "Simon_and_Garfunkel" for folders
  - All-caps bands: "ABBA", "INXS" — preserved as-is

Usage:
    from artist_normalize import normalize_artist
    
    display, search, folder = normalize_artist("Heart (band)")
    # display = "Heart"
    # search  = "Heart"  
    # folder  = "Heart"
"""

import re


# KV-specific disambiguation suffixes to strip
# KV appends these to distinguish artists from other things with the same name
KV_SUFFIXES = [
    r'\s*\(band\)',
    r'\s*\(singer\)',
    r'\s*\(rapper\)',
    r'\s*\(group\)',
    r'\s*\(musician\)',
    r'\s*\(artist\)',
    r'\s*\(UK\)',
    r'\s*\(US\)',
    r'\s*\(American\)',
    r'\s*\(British\)',
    r'\s*\(Canadian\)',
    r'\s*\(Australian\)',
    r'\s*\(Irish\)',
    r'\s*\(duo\)',
    r'\s*\(trio\)',
    r'\s*feat\..+$',
    r'\s*ft\..+$',
]

# Known manual overrides: how user types → what to search on KV
# Add entries here as you discover mismatches
MANUAL_OVERRIDES = {
    "journey":          "journey",
    "the cars":         "the-cars",
    "heart":            "heart-band",   # KV calls them "Heart (band)"
    "chicago":          "chicago-band", # KV calls them "Chicago (band)"
    "america":          "america-band",
    "europe":           "europe-band",
    "kiss":             "kiss-band",
    "yes":              "yes-band",
    "cream":            "cream-band",
    "foreigner":        "foreigner",
    "boston":           "boston-band",
    "kansas":           "kansas-band",
    "alabama":          "alabama-band",
    "genesis":          "genesis",
    "asia":             "asia-band",
}


def strip_kv_suffix(name: str) -> str:
    """Remove KV disambiguation suffixes from artist name."""
    for pattern in KV_SUFFIXES:
        name = re.sub(pattern, '', name, flags=re.IGNORECASE)
    return name.strip()


def normalize_artist(raw: str) -> tuple[str, str, str]:
    """
    Normalize an artist name for three different uses.
    
    Returns:
        display  — clean name for display/BandHelper: "Heart"
        search   — name to use in KV search: "Heart" or "heart-band"  
        folder   — name for Dropbox folder: "Heart" (used in build_dropbox_folder_name)
    
    Examples:
        "Heart (band)"      → ("Heart", "Heart", "Heart")
        "The Bangles"       → ("The Bangles", "The Bangles", "The_Bangles")
        "AC/DC"             → ("AC/DC", "AC/DC", "ACDC")
        "Simon & Garfunkel" → ("Simon & Garfunkel", "Simon & Garfunkel", "Simon_and_Garfunkel")
    """
    # Strip KV suffixes for display name
    display = strip_kv_suffix(raw).strip()
    
    # Check manual overrides for search (keyed by lowercase display name)
    search_key = display.lower()
    if search_key in MANUAL_OVERRIDES:
        search = MANUAL_OVERRIDES[search_key]
    else:
        search = display
    
    # Folder name: clean for filesystem
    folder = display
    folder = folder.replace("&", "and")
    folder = folder.replace("/", "")
    folder = re.sub(r'[^A-Za-z0-9 _\-]', '', folder)
    folder = folder.replace(" ", "_")
    folder = re.sub(r'_+', '_', folder).strip('_')
    
    return display, search, folder


def clean_kv_artist_result(kv_name: str) -> str:
    """
    Clean an artist name as returned by KV search results.
    Use this when KV returns "Heart (band)" and you want "Heart".
    """
    return strip_kv_suffix(kv_name)


if __name__ == "__main__":
    # Quick test
    test_cases = [
        "Heart (band)",
        "Chicago (band)",
        "The Bangles",
        "AC/DC",
        "Simon & Garfunkel",
        "Alanis Morissette",
        "Doobie Brothers",
        "Electric Light Orchestra",
        "Don't Bring Me Down",  # song, not artist — should pass through cleanly
        "ABBA",
        "INXS",
        "America (band)",
    ]
    
    print(f"{'Input':<35} {'Display':<25} {'Search':<25} {'Folder'}")
    print("-" * 110)
    for t in test_cases:
        d, s, f = normalize_artist(t)
        print(f"{t:<35} {d:<25} {s:<25} {f}")
