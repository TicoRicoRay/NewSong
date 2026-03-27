"""
autoupdate.py — Auto-update from GitHub

Call check_for_updates() at the top of any script to silently pull
the latest code from GitHub, then re-launch the script with the same args.
"""

import sys
import subprocess
from pathlib import Path

INSTALL_DIR = Path(r"C:\Tools\NewSong")


def check_for_updates(silent: bool = True):
    """
    Run git pull. If new commits were pulled, relaunch the script.
    silent=True suppresses output when already up to date.
    """
    result = subprocess.run(
        ["git", "pull", "origin", "main"],
        capture_output=True, text=True,
        cwd=str(INSTALL_DIR)
    )

    if result.returncode != 0:
        if not silent:
            print(f"Update check failed: {result.stderr}", file=sys.stderr)
        return

    if "Already up to date." in result.stdout:
        if not silent:
            print("Already up to date.")
        return

    # New commits pulled — relaunch
    print("Updated. Relaunching...")
    subprocess.run([sys.executable] + sys.argv)
    sys.exit(0)
