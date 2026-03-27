"""
autoupdate.py — Auto-update from latest zip in Downloads folder

Call check_for_updates() at the top of any script to silently update
if a newer zip is available, then re-launch the script with the same args.
"""

import os
import sys
import glob
import subprocess
from pathlib import Path

DOWNLOADS   = Path.home() / "Downloads"
INSTALL_DIR = Path(r"C:\Tools\NewSong")
ZIP_PREFIX  = "LRDFW_Stems"
MARKER_FILE = INSTALL_DIR / ".last_update"


def find_latest_zip() -> Path | None:
    pattern = str(DOWNLOADS / f"{ZIP_PREFIX}*.zip")
    matches = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    return Path(matches[0]) if matches else None


def get_installed_mtime() -> float:
    if MARKER_FILE.exists():
        return MARKER_FILE.stat().st_mtime
    return 0.0


def check_for_updates(silent: bool = True):
    """
    If a newer zip exists in Downloads than the last install, update and relaunch.
    silent=True suppresses output when already up to date.
    """
    zip_path = find_latest_zip()
    if not zip_path:
        return  # No zip found, nothing to do

    zip_mtime    = zip_path.stat().st_mtime
    install_mtime = get_installed_mtime()

    if zip_mtime <= install_mtime:
        if not silent:
            print("Already up to date.")
        return

    # Newer zip found — update
    print(f"New version found: {zip_path.name} — updating...")

    result = subprocess.run(
        ["powershell", "-Command",
         f"Expand-Archive -Path '{zip_path}' -DestinationPath 'C:\\Tools' -Force"],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"Update failed: {result.stderr}", file=sys.stderr)
        return

    # Mark install time
    MARKER_FILE.touch()
    print("Updated successfully.")
    print("Please run your command again.")
    sys.exit(0)
