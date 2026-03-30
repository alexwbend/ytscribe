<img src="assets/banner.png" alt="ytscribe — YouTube Transcript Extractor" width="100%" />

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-ef4444.svg" alt="MIT License" /></a>
  <img src="https://img.shields.io/badge/Python-3.8+-3b82f6.svg?logo=python&logoColor=white" alt="Python 3.8+" />
  <img src="https://img.shields.io/badge/Powered%20by-yt--dlp-22c55e.svg" alt="yt-dlp" />
  <img src="https://img.shields.io/badge/AI-Skill-8b5cf6.svg" alt="AI Skill" />
  <img src="https://img.shields.io/badge/Open%20Source-♥-f472b6.svg" alt="Open Source" />
</p>

<p align="center">
  An open-source AI skill that extracts clean, readable transcripts from any YouTube video.<br/>
  Single videos, batch lists, playlists, and entire channels — no code required.
</p>

---

## What is ytscribe?

ytscribe is an **AI skill** — a set of instructions and a Python helper script that gives any AI assistant the ability to extract YouTube transcripts on demand. Paste a URL, get a clean transcript. No browser extensions, no subscriptions, no manual copy-pasting.

It understands four types of input automatically and handles each one with smart defaults, so you get a result immediately without answering setup questions first.

> **Philosophy:** The user should never answer a question before seeing their first result. ytscribe detects what you gave it, applies sensible defaults, delivers immediately, and only then offers alternatives.

---

## Install

Add [`SKILL.md`](SKILL.md) as a knowledge file in your AI assistant's project or custom instructions.

**In Cowork or Claude Code**, that's the whole install. The skill auto-installs its own dependency (`yt-dlp`) the first time it runs — nothing else needed.

**In a plain Claude.ai Project** (web interface without code execution), you'll also need to install `yt-dlp` locally and run the helper script yourself:

```bash
pip install yt-dlp
```

Then add both [`SKILL.md`](SKILL.md) and [`scripts/ytscribe.py`](scripts/ytscribe.py) to your project. Claude will generate the exact command to run based on your request, and you paste it into your terminal.

---

## Four modes, zero friction

ytscribe detects your input automatically.

### Single video
Paste one URL. Get a transcript. Short videos appear inline; long ones are saved as a file.

```
Transcribe: https://youtube.com/watch?v=dQw4w9WgXcQ
```

### Small batch (2–9 URLs)
Paste a list of URLs. Get individual markdown files, one per video, no questions asked.

```
Transcribe: [URL1] [URL2] [URL3]
```

### Playlist
Paste a playlist URL. ytscribe enumerates the videos, shows you the list, asks one scope question, then runs.

```
Get transcripts from this playlist: https://youtube.com/playlist?list=PLxxxxxx
```

### Channel
Paste a channel URL. ytscribe fetches the most recent uploads and asks how many you want before proceeding.

```
Transcribe: https://youtube.com/@lexfridman
```

---

## Output formats

| Format | Default | How to request |
|--------|---------|----------------|
| Clean prose | ✓ | — |
| Timestamped | | "with timestamps" |
| Markdown `.md` | ✓ | — |
| Plain text `.txt` | | "as a text file" |
| Individual files | ✓ | — |
| Merged (1 file) | | "merged", "one file", "combine all" |
| Auto-zipped | ✓ if 6+ files | — |
| Language | Video's own language | "in English", "in French", any language name |

Language note: ytscribe uses the video's original language by default — a French video gives you a French transcript. If you request a different language and subtitles in that language aren't available, it falls back to the video's original language and tells you which one was used.

If you specify a preference in your first message, ytscribe silently honors it.

---

## What you get

Every transcript includes a clean metadata header:

```markdown
# The Intelligence Age — Sam Altman

- **Channel:** Y Combinator
- **Duration:** 47m 12s
- **URL:** https://youtube.com/watch?v=H6eYLpCgAI0
- **Date:** 2024-10-15

---

The transition to the intelligence age is happening faster than most people expected.
What we're building now will define the next century...
```

Batch runs summarize results at the end:

```
✓ Success:     24/25
⚠ No subs:     1/25  (music video — skipped)
📝 Total words: 187,432
📁 Output:      24 individual .md files + ytscribe_batch_24_videos.zip
```

---

## Batch limits

| | |
|---|---|
| Speed | ~3 seconds per video |
| Recommended batch | 25 videos (~2 min) |
| Hard limit | 50 videos per run |
| Rate limiting | Auto-handled with exponential backoff |

YouTube throttles subtitle requests after rapid successive downloads. ytscribe adds a 2-second delay between requests and retries automatically on 429 errors (5s → 10s → 15s).

---

## For developers

The [`scripts/ytscribe.py`](scripts/ytscribe.py) helper runs standalone and can be integrated into any pipeline:

```bash
python3 scripts/ytscribe.py \
  --videos "dQw4w9WgXcQ,H6eYLpCgAI0" \
  --format md \
  --merge true \
  --timestamps false \
  --lang en \
  --output-dir ./output
```

Results are returned as JSON for easy parsing by the AI or downstream tools.

---

## License

MIT — free to use, modify, and distribute. See [LICENSE](LICENSE).

---

<p align="center">
  <sub>Built by a PM, not a developer — because AI skills should be for everyone.</sub>
</p>
