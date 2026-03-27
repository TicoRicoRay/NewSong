# Live Radio DFW — Stem Downloader

Downloads all stems from Karaoke-Version.com, renames them to convention, and syncs to Dropbox automatically.

---

## One Command

```
cd C:\Tools\lrdfw_v2
python stems.py --artist "Doobie Brothers" --song "China Grove"
```

Walk away. Come back in ~15 minutes. Files are in Dropbox.

---

## One-Time Setup

### 1. Install dependencies
```
cd C:\Tools\lrdfw_v2
pip install -r requirements.txt
playwright install chromium
```

### 2. Install Dropbox desktop app
Download from https://www.dropbox.com/install, sign in. This creates `C:\Users\myers\Dropbox\` and syncs automatically.

### 3. Configure config.py
```python
KV_EMAIL     = "rmyers@futurebright.com"
KV_PASSWORD  = "your_kv_password"
DOWNLOADS_DIR = r"C:\Users\myers\Dropbox\_Tracks"
```

---

## File Naming Convention

Files are named by download order (oldest = 00):
```
00_Drum_Kit.mp3
01_Percussion.mp3
02_Bass.mp3
03_Rhythm_Electric_Guitar_Left.mp3
...
12_Lead_Vocal.mp3
```

Folder name: `ARTIST_NAME-SONG_NAME`
- Spaces → underscores
- Apostrophes and special chars removed
- Example: `Electric_Light_Orchestra-Dont_Bring_Me_Down`

---

## Updating Scripts

When a new zip arrives from Perplexity:
```
C:\Tools\lrdfw_v2\update.bat
```

Preserves `config.py` and `.env`.

---

## Options

| Flag | Description |
|------|-------------|
| `--artist` | Artist name (required) |
| `--song` | Song title (required) |
| `--url` | Direct KV song URL (skips search) |
| `--skip-download` | Skip KV download, use existing stems |

---

## Rename Only

To rename stems in an existing folder:
```
python rename_stems.py --folder "C:\Users\myers\Dropbox\_Tracks\Doobie_Brothers-China_Grove"
python rename_stems.py --folder "C:\Users\myers\Dropbox\_Tracks\Doobie_Brothers-China_Grove" --dry-run
```

---

## Known Limitations

- KV login uses browser automation (Playwright/Chromium) — requires internet
- Each stem takes ~75 seconds server-side to generate — 12 stems ≈ 15 min
- The Click/count-in track (index 0) is skipped — not useful for live performance
- Artist names with KV disambiguation (e.g. "Heart (band)") are auto-cleaned

---

## Roadmap

1. **Mixdowns** — auto-generate full mix + no-vocals mix using pydub/ffmpeg
2. **BandHelper upload** — attach mixdowns to songs in BandHelper
3. **Chord fetching** — fetch chord sheets from alternative sites (not Ultimate Guitar)
4. **Artist normalization** — expanded lookup table for KV name mismatches
