---
name: ytscribe
description: >
  Extract transcripts from YouTube videos — single videos, batch lists, playlists, or entire channels.
  Use this skill whenever the user wants to get a transcript, subtitles, or captions from YouTube.
  Trigger on: "transcript", "transcribe", "get subtitles", "captions", "ytscribe", YouTube URLs,
  "download transcript", "pull transcript", "extract text from video", "what did they say in this video",
  or any request involving converting YouTube video speech to text. Also trigger when the user pastes
  a YouTube URL and wants the content in text form, or asks to batch-process multiple videos,
  a playlist, or a channel's recent uploads. Even if the user just pastes a YouTube link and says
  "get me the text" or "what's in this video", use this skill.
---

# ytscribe — YouTube Transcript Extractor

Extract clean, readable transcripts from YouTube videos. Supports single videos, batch lists of URLs,
playlists, and channel recent uploads. Outputs as inline text, individual files, or merged documents.

## Dependencies

This skill requires `yt-dlp`. Install it before first use:

```bash
pip install yt-dlp --break-system-packages -q
```

## How it works

YouTube stores subtitle tracks (both manual and auto-generated) as small text files alongside videos.
`yt-dlp` can download just the subtitle track without touching the video itself — this is fast (~2-3 seconds
per video) and doesn't trigger YouTube's video download rate limits.

The skill pulls subtitles in VTT format, then cleans them: removing duplicate lines (YouTube's auto-captions
repeat text across overlapping timestamps), stripping HTML tags, and optionally removing timestamps to
produce clean prose.

---

## UX Philosophy: deliver first, customize second

The user should NEVER answer a format question before seeing their first result. The flow is:

1. Detect what the user gave you
2. Apply smart defaults
3. Deliver the result immediately
4. AFTER delivery, offer one short line about alternatives

If the user specifies preferences upfront ("give me timestamped .txt files"), honor every preference
they stated and skip all defaults for those choices. Only default what they didn't mention.

---

## Input detection

Parse what the user gave you automatically. Never ask "what type of input is this?"

- **Single URL** → single video mode
- **Multiple URLs** (list, comma-separated, or pasted block) → batch mode
- **Playlist URL** (contains `list=`) → playlist mode
- **Channel URL** (contains `@` or `/c/` or `/channel/`) → channel mode

---

## The three flows

### Flow A: Single video (1 URL)

**Questions to ask: ZERO.**

Just extract and deliver. Smart defaults:
- Clean prose (no timestamps)
- Markdown format with metadata header
- Always save as a .md file and present to the user
- Also display inline in chat only if the video is very short (under ~3 min / ~500 words)
- For longer videos, show only the first 2-3 sentences as a preview, then link the file

After delivering, add one line:
> "This is clean prose. If you'd prefer timestamps, a different format, or just the raw text, let me know."

### Flow B: Small batch (2-9 URLs)

**Questions to ask: ZERO.**

Just extract all of them and deliver. Smart defaults:
- Clean prose (no timestamps)
- Individual markdown files, one per video
- Present the files to the user (auto-zipped if 6+ files)

After delivering, add one line:
> "These are individual markdown files. I can also merge them into one file, add timestamps, or switch to plain text."

### Flow C: Large batch, playlist, or channel (10+ URLs, or playlist/channel URL)

**Questions to ask: ONE — about scope, not format.**

For playlists and channels, first fetch a preview (first 10 videos) and the total count:
```bash
yt-dlp --no-check-certificates --flat-playlist \
  --print "%(id)s ||| %(title)s ||| %(duration)s ||| %(upload_date)s" \
  --playlist-end 10 --max-downloads 10 \
  "{URL}"
```

Never enumerate the full list — playlists can have thousands of videos. Always show a 10-video preview + total count, then ask one scope question:
> "This playlist has {total} videos. Here are the first 10:
> 1. {title} ({duration})
> 2. {title} ({duration})
> ...
> How many would you like? (Max 50 per run)"

If the user already specified a count in their prompt ("the last 7", "the first 20"), skip this question entirely and proceed directly.

For a large batch of pasted URLs — no confirmation needed, just process them all.

Smart defaults:
- Clean prose (no timestamps)
- Single merged markdown file (gives the user one file to work with)
- ALSO provide a zip of individual .md files alongside the merged file
- This way the user gets both options without having to ask

After delivering, add one line:
> "You've got both a merged file and individual files in the zip. Want timestamps, plain text, or a different language?"

---

## Defaults table

| Setting | Default | Override trigger (user says...) |
|---------|---------|-------------------------------|
| Timestamps | OFF (clean prose) | "with timestamps", "timestamped", "I need to reference parts" |
| File format | Markdown (.md) | "text file", "plain text", ".txt", "raw text" |
| Structure | Individual files | "merged", "one file", "combine all" |
| Language | Video's own language | "in English", "in French", "Spanish subtitles", any language name or code |
| Zip | Auto if 6+ individual files | User never needs to request this |

The override rule: if the user mentions ANY preference in their initial message, apply it silently.
Do not confirm what they already told you. Do not say "I see you want timestamps, I'll add those."
Just do it.

---

## Output structure

Each transcript (whether inline, in a file, or as a section in a merged file) includes this metadata:

**Markdown format:**
```
# {Video Title}

- **Channel:** {channel name}
- **Duration:** {formatted duration}
- **URL:** {video URL}
- **Date:** {upload date if available}

---

{transcript text}
```

**Plain text format:**
```
{Video Title}
Channel: {channel name}
Duration: {formatted duration}
URL: {video URL}
Date: {upload date if available}
============================================================

{transcript text}
```

**Timestamped format (either md or txt):**
```
[00:00] First line of speech
[00:15] Second line of speech
[00:32] Third line of speech
```

**Clean prose format (default):**
```
First line of speech second line of speech third line of speech...
```

---

## Execution

### Step 1: Install yt-dlp
```bash
pip install yt-dlp --break-system-packages -q 2>/dev/null
```

### Step 2: Download transcripts
Locate and run the Python helper script. Search for it in the workspace:

```bash
SCRIPT=$(find / -name "ytscribe.py" -path "*/scripts/*" 2>/dev/null | head -1)
python3 "$SCRIPT" \
  --videos "VIDEO_ID_1,VIDEO_ID_2,..." \
  --format {txt|md} \
  --merge {true|false} \
  --output-dir ./ytscribe_output \
  --timestamps {true|false} \
  --lang {language_code}
```

If the script cannot be found, check that `scripts/ytscribe.py` has been added as a knowledge file, then write it to a temp location before running.

### Step 3: Clean up the transcript
First, assess the transcript quality:

- **If it already has punctuation, capitalization, and paragraph breaks** (manually uploaded captions): preserve it exactly as-is. Do not reprocess or rephrase.
- **If it is raw auto-generated text** (no punctuation, no capitalization, no paragraphs): clean it up.

When cleaning up raw transcripts:
- Add punctuation (periods, commas, question marks) based on natural speech patterns
- Capitalize the first word of each sentence
- Break into paragraphs at natural topic or speaker shifts
- Remove filler artifacts like `[Music]`, `[Applause]`, `[Laughter]`, `(Laughter)`, `(Applause)`, `(Audience)` and similar bracketed or parenthesised sound cues, unless the user asked for raw output

Apply cleanup automatically for transcripts under ~5,000 words.
For transcripts over ~5,000 words: clean up only if the user requests it (e.g. "clean it up", "add punctuation"). Otherwise deliver the raw extracted text and note: "This is the raw transcript — let me know if you'd like me to clean up punctuation and paragraph breaks."

### Step 4: Present output
Always copy final output files to `/mnt/user-data/outputs/` and use `present_files`.

---

## Batch limits

- **Per-video speed:** ~2-3 seconds download + 2 seconds delay between requests = ~5 seconds per video
- **Recommended batch:** 25 videos (~2 minutes)
- **Hard maximum:** 50 videos per batch (~4 minutes)
- **Beyond 50:** Tell the user to split into multiple batches. Process the first 50, then ask if they want to continue.

YouTube rate-limits subtitle downloads after rapid successive requests (HTTP 429). The script handles this
with automatic 2-second delays between videos and exponential backoff retries (5s, 10s, 15s) on 429 errors.

## yt-dlp flags

Always use:
- `--no-check-certificates` — Required in sandbox environments
- `--skip-download` — Never download the actual video
- `--write-auto-sub` — Get auto-generated subs if manual ones aren't available
- `--sub-lang en` — Default to English; adjust per user request
- `--sub-format vtt` — VTT format for clean parsing

For listing videos:
- `--flat-playlist` — Enumerate without processing
- `--playlist-end N` — Limit enumeration

## Handling failures

Some videos have no subtitles (music videos, very old videos, live streams).
- Log clearly: "⚠ No transcript available for: {title}"
- Continue processing remaining videos
- Summarize at the end: "Extracted {X}/{Y} transcripts. {Z} had no subtitles available."
- Never stop the batch because one video failed.

## Language support

Default to the video's own language — do not force English. If the user requests a specific language:
- Use `--sub-lang {code}` (e.g., `en`, `fr`, `es`, `de`, `ar`)
- If the requested language is unavailable, fall back to the video's original language
- Mention in the output which language was actually used if it differs from what was requested

---

## Example interactions

**Casual user — zero friction:**
User: "Get me the transcript of this: https://youtube.com/watch?v=abc123"
→ Extract immediately. Save as file always. Show inline only if under ~3 min. No questions. Offer alternatives after.

**Batch user — zero friction:**
User: "I need transcripts for these:" [pastes 6 URLs]
→ Individual markdown files, auto-zipped (6 files triggers zip). No questions. Deliver. Offer alternatives after.

**Power user — honor stated preferences:**
User: "Download timestamped .txt transcripts for the last 20 videos on @hubermanlab, individual files"
→ The user specified: timestamps ON, .txt format, individual files, channel mode, 20 videos.
→ Enumerate 20 videos, show list, confirm scope, then deliver exactly what they asked for.
→ No post-delivery "want timestamps?" because they already said timestamps.

**Channel user — one scope question:**
User: "Get me all the transcripts from @lexfridman"
→ Enumerate recent uploads. Show list. Ask "I found 450+ videos. Want the latest 25, or a different number?"
→ After they pick, deliver with defaults. Offer alternatives after.

**Explicit format request — silent compliance:**
User: "Transcribe this playlist as individual text files with timestamps"
→ The user told you everything. Don't confirm, don't ask, don't narrate. Just do it and deliver.
