"""
Shared utility functions for the Live Radio DFW workflow scripts.
"""

import re
import unicodedata


def title_case_words(text: str) -> str:
    """Capitalize first letter of each word."""
    return ' '.join(w.capitalize() for w in text.split())


def slugify_dropbox(text: str) -> str:
    """
    Convert artist/song name to Dropbox folder-safe format:
    - Replace spaces with underscores
    - Remove apostrophes, quotes, and other non-alphanumeric chars (except hyphens and underscores)
    - Normalize unicode (accents → base char, then strip leftovers)

    Examples:
        "Electric Light Orchestra" → "Electric_Light_Orchestra"
        "Don't Bring Me Down"      → "Dont_Bring_Me_Down"
        "Rock 'n' Roll"            → "Rock_n_Roll"
    """
    # Normalize unicode characters (e.g., é → e)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")

    # Remove apostrophes, quotes, and similar punctuation first
    text = re.sub(r"['\"\`]", "", text)

    # Replace spaces with underscores
    text = text.replace(" ", "_")

    # Remove any remaining non-alphanumeric characters except underscore and hyphen
    text = re.sub(r"[^A-Za-z0-9_\-]", "", text)

    # Collapse multiple underscores
    text = re.sub(r"_+", "_", text)

    return text


def build_dropbox_folder_name(artist: str, song: str) -> str:
    """
    Build the Dropbox subfolder name: ARTIST_NAME-SONG_NAME
    Each word is capitalized (title case).
    Example: "Electric Light Orchestra", "Don't Bring Me Down"
             → "Electric_Light_Orchestra-Dont_Bring_Me_Down"
    """
    # title_case_words must run BEFORE slugify (which replaces spaces with underscores)
    return f"{slugify_dropbox(title_case_words(artist))}-{slugify_dropbox(title_case_words(song))}"


def sanitize_filename(name: str) -> str:
    """Safe filename (no path separators or special chars)."""
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    return name.strip()
