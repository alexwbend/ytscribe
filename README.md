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
  Single videos, batch lists, playlists, and entire channels.
</p>

---

## What is ytscribe?

ytscribe is an **AI skill** — a set of instructions and a Python helper script that gives any AI assistant the ability to extract YouTube transcripts on demand. Paste a URL, get a clean transcript. No browser extensions, no subscriptions, no manual copy-pasting.

It understands four types of input automatically and handles each one with smart defaults, so you get a result immediately without answering setup questions first.

> **Philosophy:** The user should never answer a question before seeing their first result. ytscribe detects what you gave it, applies sensible defaults, delivers immediately, and only then offers alternatives.

---

## Install

ytscribe runs in any agentic AI environment that can execute code on your machine. Add [`SKILL.md`](SKILL.md) as a knowledge file — that's the whole install. The skill handles the rest automatically, including its own dependency.

Works with: Claude Cowork, Claude Code, Gemini CLI, Codex, Cursor, Windsurf, Cline, and similar tools.

---

## Four modes, zero friction

ytscribe detects your input automatically.

### Single video
Paste one URL. Get a transcript. Short videos appear inline; long ones are saved as a file.

```
Transcribe: https://youtube.com/watch?v=qp0HIF3SfI4
```

### Small batch (2–9 URLs)
Paste a list of URLs. Get individual markdown files, one per video, no questions asked.

```
Transcribe: [URL1] [URL2] [URL3]
```

### Playlist
Paste a playlist URL and ytscribe fetches the total count, shows you the first 10 titles as a preview, and asks how many you want before running. Specify a count in your prompt to skip the question entirely.

"First" and "last" follow the playlist's own order as set by the creator, not upload date.

```
Transcribe: https://youtube.com/playlist?list=PLxxxxxx
```
```
Transcribe the first 10 videos from: https://youtube.com/playlist?list=PLxxxxxx
```
```
Transcribe the last 10 videos from: https://youtube.com/playlist?list=PLxxxxxx
```

### Channel
Paste a channel URL and ytscribe shows you the most recent uploads and asks how many you want. Specify a count in your prompt to skip the question.

"Last N" means most recent N uploads, newest first.

```
Transcribe: https://youtube.com/@TED
```
```
Transcribe the last 7 videos from: https://youtube.com/@TED
```

---

## Output formats

| Format | Default | How to request |
|--------|---------|----------------|
| Clean prose | ✓ | — |
| Timestamped | | "with timestamps" |
| Markdown `.md` | ✓ | — |
| Plain text `.txt` | | "as a text file" |
| JSON `.json` | | "as JSON" |
| CSV `.csv` | | "as CSV" |
| Individual files | ✓ | — |
| Merged (1 file) | | "merged", "one file", "combine all" |
| Auto-zipped | ✓ if 6+ files | — |
| Chapters | ✓ auto-detected | "no chapters" to disable |
| Language | Video's own language | "in English", "in French", any language name |
| Multi-language | | "in English and French", "in en,fr,es" |

Timestamps in markdown output are clickable links that open the video at that exact moment. In plain text, they stay as plain brackets.

JSON export produces one structured object per video (or an array for batches) with full metadata, word count, and transcript text. When timestamps are enabled, a `segments` array is included with per-line time, seconds, URL, and text. CSV produces one row per video that opens directly in Excel or Sheets.

Videos with YouTube chapters are automatically detected and split into labeled sections. Chapters are parsed from the video description using the same rules as YouTube (3+ timestamps starting at 0:00). To disable, say "no chapters" or "flat".

Multi-language pulls transcripts in multiple languages for the same video in one request. Each language gets its own output file (with a language suffix). In JSON, all languages are grouped under a `transcripts` key.

If you specify a preference in your first message, ytscribe silently honors it.

---

## What you get

Every transcript includes a rich metadata header:

```markdown
# The Intelligence Age -- Sam Altman

- **ID:** H6eYLpCgAI0
- **Channel:** Y Combinator
- **Duration:** 47m 12s
- **URL:** https://youtube.com/watch?v=H6eYLpCgAI0
- **Date:** 2024-10-15
- **Views:** 1,234,567
- **Likes:** 45,678
- **Tags:** AI, technology, future
- **Description:** Sam Altman discusses the transition to the intelligence age...

---

The transition to the intelligence age is happening faster than most people expected.
What we're building now will define the next century...
```

Videos with YouTube chapters are automatically split into labeled sections with headings.

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
  --chapters true \
  --output-dir ./output
```

All flags: `--format` (txt, md, json, csv), `--merge` (true/false), `--timestamps` (true/false), `--lang` (comma-separated codes like `en,fr,es`), `--chapters` (true/false), `--output-dir`, `--config` (path to config file).

Results are returned as JSON for easy parsing by the AI or downstream tools.

### Persistent config

Power users can create a `ytscribe.config.json` file to set preferred defaults:

```json
{
  "format": "json",
  "timestamps": true,
  "lang": "en"
}
```

The script auto-detects this file by walking up from the working directory. CLI flags always override config values. All keys are optional. See [SKILL.md](SKILL.md) for the full list of supported keys.

### Running tests

```bash
pip install pytest
python3 -m pytest tests/ -v
```

84 unit tests cover chapter parsing, VTT deduplication, all output formats, config validation, and filename sanitization.

---

## License

MIT — free to use, modify, and distribute. See [LICENSE](LICENSE).

---
