#!/usr/bin/env python3
"""
ytscribe — YouTube Transcript Extractor
Extracts, cleans, and formats YouTube video transcripts using yt-dlp.

Usage:
  python3 ytscribe.py --videos "ID1,ID2,ID3" --format md --merge true --output-dir ./output
  python3 ytscribe.py --videos "dQw4w9WgXcQ" --format txt --timestamps true
"""

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

# Delay between requests to avoid YouTube 429 rate limits.
# YouTube throttles subtitle downloads after ~15-20 rapid requests.
BATCH_DELAY_SECONDS = 2
RETRY_DELAY_SECONDS = 5
MAX_RETRIES = 3


def run_ytdlp(args: list[str], capture_output=True) -> subprocess.CompletedProcess:
    """Run yt-dlp with standard flags."""
    cmd = ["yt-dlp", "--no-check-certificates", "--no-warnings"] + args
    return subprocess.run(cmd, capture_output=capture_output, text=True, timeout=120)


def parse_chapters_from_description(description: str) -> list[dict]:
    """Parse chapter timestamps from a YouTube video description.

    YouTube chapters are lines in the description that start with a timestamp
    like '0:00 Introduction' or '1:23:45 Deep dive into topic'.

    Returns a list of dicts: [{"time_seconds": 0, "time_label": "0:00", "title": "Introduction"}, ...]
    Returns an empty list if no chapters are found (graceful fallback).
    """
    if not description:
        return []

    # Match timestamps at the start of a line: 0:00, 12:34, 1:23:45
    chapter_pattern = re.compile(
        r"^[\s\-\•]*(\d{1,2}:\d{2}(?::\d{2})?)\s*[-–—:]?\s*(.+)$",
        re.MULTILINE
    )

    matches = chapter_pattern.findall(description)

    # YouTube requires at least 3 chapters starting from 0:00 to display them.
    # We use the same rule: fewer than 3 timestamp lines = probably not chapters.
    if len(matches) < 3:
        return []

    chapters = []
    for time_str, title in matches:
        parts = time_str.split(":")
        if len(parts) == 3:
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        else:
            seconds = int(parts[0]) * 60 + int(parts[1])

        chapters.append({
            "time_seconds": seconds,
            "time_label": time_str,
            "title": title.strip()
        })

    # Must start at or near 0:00 (YouTube's own rule)
    if chapters and chapters[0]["time_seconds"] > 5:
        return []

    # Sort by time (descriptions are usually in order, but be safe)
    chapters.sort(key=lambda c: c["time_seconds"])

    return chapters


def get_video_metadata(video_id: str, include_description: bool = False) -> dict:
    """Fetch video metadata without downloading. Retries up to 3 times on failure.

    Always fetches rich metadata (view count, like count, thumbnail, tags).
    If include_description is True, the video description is included in
    the returned dict (needed for chapter parsing). The full JSON blob is
    always downloaded regardless; this flag only controls the return value.
    """
    # Use --dump-json for reliable parsing -- avoids delimiter issues with
    # fields like description that can contain arbitrary text.
    for attempt in range(1, MAX_RETRIES + 1):
        result = run_ytdlp([
            "--skip-download",
            "--dump-json",
            f"https://www.youtube.com/watch?v={video_id}"
        ])

        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                duration = int(data.get("duration") or 0)
                date_raw = str(data.get("upload_date") or "")
                date_formatted = (
                    f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
                    if len(date_raw) == 8 else date_raw
                )
                meta = {
                    "title": data.get("title") or f"Video {video_id}",
                    "channel": data.get("channel") or data.get("uploader") or "Unknown",
                    "duration": duration,
                    "date": date_formatted,
                    "view_count": data.get("view_count"),
                    "like_count": data.get("like_count"),
                    "thumbnail": data.get("thumbnail") or "",
                    "tags": data.get("tags") or [],
                }
                if include_description:
                    meta["description"] = data.get("description") or ""
                return meta
            except (json.JSONDecodeError, KeyError):
                pass  # fall through to retry logic

        # Check for rate limiting
        stderr = result.stderr or ""
        if "429" in stderr or "Too Many Requests" in stderr:
            if attempt < MAX_RETRIES:
                wait = RETRY_DELAY_SECONDS * attempt
                print(f"  ⏳ Metadata rate limited. Waiting {wait}s before retry {attempt + 1}/{MAX_RETRIES}...", flush=True)
                time.sleep(wait)
                continue

        # Non-429 failure — no point retrying
        break

    return {
        "title": f"Video {video_id}", "channel": "Unknown", "duration": 0,
        "date": "Unknown", "view_count": None, "like_count": None,
        "thumbnail": "", "tags": []
    }


def format_duration(seconds: int) -> str:
    """Convert seconds to human-readable duration."""
    if seconds <= 0:
        return "Unknown"
    td = timedelta(seconds=seconds)
    hours, remainder = divmod(int(td.total_seconds()), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def download_transcript(video_id: str, work_dir: str, lang: str = "en") -> str | None:
    """Download transcript VTT file with retry logic for 429 rate limits.
    
    Returns path to VTT file or None.
    """
    output_template = os.path.join(work_dir, f"{video_id}")
    
    for attempt in range(1, MAX_RETRIES + 1):
        # Try manual subs first, then auto-generated
        for sub_flag in ["--write-sub", "--write-auto-sub"]:
            result = run_ytdlp([
                sub_flag,
                "--sub-lang", lang,
                "--sub-format", "vtt",
                "--skip-download",
                "-o", output_template,
                f"https://www.youtube.com/watch?v={video_id}"
            ])
            
            # Check if VTT file was created
            vtt_path = f"{output_template}.{lang}.vtt"
            if os.path.exists(vtt_path):
                return vtt_path
        
        # Try without language specification (get whatever is available)
        result = run_ytdlp([
            "--write-auto-sub",
            "--skip-download",
            "-o", output_template,
            f"https://www.youtube.com/watch?v={video_id}"
        ])
        
        # Look for any VTT file
        for f in os.listdir(work_dir):
            if f.startswith(video_id) and f.endswith(".vtt"):
                return os.path.join(work_dir, f)
        
        # Check if we got rate-limited (429)
        stderr = result.stderr or ""
        stdout = result.stdout or ""
        if "429" in stderr or "429" in stdout or "Too Many Requests" in stderr or "Too Many Requests" in stdout:
            if attempt < MAX_RETRIES:
                wait = RETRY_DELAY_SECONDS * attempt
                print(f"  ⏳ Rate limited (429). Waiting {wait}s before retry {attempt + 1}/{MAX_RETRIES}...", flush=True)
                time.sleep(wait)
                continue
            else:
                print(f"  ✗ Rate limited after {MAX_RETRIES} retries", flush=True)
                return None
        
        # If no 429, subtitles genuinely don't exist for this video
        break
    
    return None


def download_transcripts_multi(video_id: str, work_dir: str, langs: list[str]) -> dict[str, str | None]:
    """Download transcripts in multiple languages for a single video.

    Returns a dict mapping each requested language to its VTT path,
    or None if that language was not available.

    Edge case: if a language is unavailable, it is skipped gracefully.
    The caller decides what to do with the results.
    """
    results = {}
    for lang in langs:
        # Use a language-specific subdirectory to avoid filename collisions
        lang_dir = os.path.join(work_dir, f"{video_id}_{lang}")
        os.makedirs(lang_dir, exist_ok=True)
        vtt_path = download_transcript(video_id, lang_dir, lang)
        results[lang] = vtt_path
        if vtt_path:
            print(f"    ✓ [{lang}] downloaded", flush=True)
        else:
            print(f"    ⚠ [{lang}] not available", flush=True)
        # Small delay between language downloads to be safe
        if len(langs) > 1:
            time.sleep(1)
    return results


def _vtt_timestamp_to_seconds(ts: str) -> int:
    """Convert a VTT timestamp like '00:12:34.567' to integer seconds."""
    ts = ts.split(".")[0]  # drop milliseconds
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return 0


def _parse_vtt_entries(vtt_path: str) -> list[tuple[int, str, str]]:
    """Parse a VTT file into deduplicated (seconds, display_timestamp, text) tuples.

    Shared by clean_vtt (for text output) and structured_transcript (for JSON).
    """
    with open(vtt_path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    entries = []
    seen = set()
    current_raw_ts = None
    current_display_ts = None

    for line in lines:
        if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue

        ts_match = re.match(r"^(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->", line)
        if ts_match:
            current_raw_ts = ts_match.group(1)
            ts = current_raw_ts.split(".")[0]
            if ts.startswith("00:"):
                ts = ts[3:]
            current_display_ts = ts
            continue

        if not line.strip():
            continue

        clean = re.sub(r"<[^>]+>", "", line).strip()

        if clean and clean not in seen:
            seen.add(clean)
            seconds = _vtt_timestamp_to_seconds(current_raw_ts) if current_raw_ts else 0
            entries.append((seconds, current_display_ts, clean))

    return entries


def structured_transcript(vtt_path: str, video_id: str, chapters: list[dict] | None = None) -> list[dict]:
    """Return transcript as a list of structured entries for JSON export.

    Each entry: {"time": "12:34", "seconds": 754, "url": "https://...", "text": "..."}
    If chapters are present, entries also include a "chapter" field.
    """
    entries = _parse_vtt_entries(vtt_path)

    # Build chapter lookup if available
    boundaries = [(ch["time_seconds"], ch["title"]) for ch in chapters] if chapters else []

    def _get_chapter(seconds: int) -> str | None:
        if not boundaries:
            return None
        chapter_title = boundaries[0][1]
        for boundary_sec, title in boundaries:
            if seconds >= boundary_sec:
                chapter_title = title
            else:
                break
        return chapter_title

    result = []
    for seconds, display_ts, text in entries:
        entry = {
            "time": display_ts,
            "seconds": seconds,
            "url": f"https://youtube.com/watch?v={video_id}&t={seconds}",
            "text": text
        }
        chapter = _get_chapter(seconds)
        if chapter:
            entry["chapter"] = chapter
        result.append(entry)

    return result


def clean_vtt(
    vtt_path: str,
    keep_timestamps: bool = False,
    chapters: list[dict] | None = None,
    video_id: str | None = None,
    fmt: str = "md"
) -> str:
    """Clean VTT subtitle file to plain text.

    YouTube auto-generated VTT files have duplicate lines because captions
    are shown progressively with overlapping timestamps. This function
    deduplicates while preserving speaking order.

    If chapters are provided, the transcript is split into sections with
    chapter headings inserted at the appropriate positions.

    If keep_timestamps is True and fmt is "md" and video_id is provided,
    timestamps become clickable YouTube links that open the video at that
    exact moment.
    """
    entries = _parse_vtt_entries(vtt_path)

    # Helper: format a single timestamped line
    link_timestamps = keep_timestamps and fmt == "md" and video_id
    def _ts_line(seconds: int, display_ts: str, text: str) -> str:
        if link_timestamps:
            url = f"https://youtube.com/watch?v={video_id}&t={seconds}"
            return f"[{display_ts}]({url}) {text}"
        else:
            return f"[{display_ts}] {text}"

    # If no chapters, produce flat output (v1 behavior)
    if not chapters:
        if keep_timestamps:
            return "\n".join(_ts_line(s, ts, text) for s, ts, text in entries)
        else:
            return " ".join(text for _, _, text in entries)

    # With chapters: bucket entries into chapter sections
    # Build boundary list: [(start_seconds, chapter_title), ...]
    boundaries = [(ch["time_seconds"], ch["title"]) for ch in chapters]

    # Assign each entry to a chapter
    chapter_buckets: dict[int, list[tuple]] = {i: [] for i in range(len(boundaries))}

    for seconds, display_ts, text in entries:
        # Find which chapter this timestamp belongs to
        chapter_idx = 0
        for i, (boundary_sec, _) in enumerate(boundaries):
            if seconds >= boundary_sec:
                chapter_idx = i
            else:
                break
        chapter_buckets[chapter_idx].append((seconds, display_ts, text))

    # Build output with chapter headings
    sections = []
    for i, (_, chapter_title) in enumerate(boundaries):
        bucket = chapter_buckets[i]
        if not bucket:
            continue

        if keep_timestamps:
            body = "\n".join(_ts_line(s, ts, text) for s, ts, text in bucket)
        else:
            body = " ".join(text for _, _, text in bucket)

        # Use a marker that format_output will replace with proper heading syntax
        sections.append(f"__CHAPTER__:{chapter_title}\n\n{body}")

    return "\n\n".join(sections)


def _format_count(n: int | None) -> str:
    """Format a number with commas, or return 'N/A' if unavailable."""
    if n is None:
        return "N/A"
    return f"{int(n):,}"


def format_output(video_id: str, metadata: dict, transcript: str, fmt: str) -> str:
    """Format a single transcript with metadata.

    Includes video ID and rich metadata (views, likes, thumbnail, tags,
    description) when available. Handles chapter markers (__CHAPTER__:Title)
    embedded by clean_vtt, converting them to proper heading syntax.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    duration = format_duration(metadata["duration"])
    views = _format_count(metadata.get("view_count"))
    likes = _format_count(metadata.get("like_count"))
    thumbnail = metadata.get("thumbnail", "")
    tags = metadata.get("tags", [])
    description = metadata.get("description", "")

    if fmt == "md":
        lines = [
            f"# {metadata['title']}",
            "",
            f"- **ID:** {video_id}",
            f"- **Channel:** {metadata['channel']}",
            f"- **Duration:** {duration}",
            f"- **URL:** {url}",
            f"- **Date:** {metadata['date']}",
            f"- **Views:** {views}",
            f"- **Likes:** {likes}",
        ]
        if thumbnail:
            lines.append(f"- **Thumbnail:** {thumbnail}")
        if tags:
            lines.append(f"- **Tags:** {', '.join(tags)}")
        if description:
            # Collapse to first 300 chars to keep header compact
            desc_preview = description[:300].replace("\n", " ").strip()
            if len(description) > 300:
                desc_preview += "..."
            lines.append(f"- **Description:** {desc_preview}")

        lines.append("")
        lines.append("---")
        lines.append("")

        header = "\n".join(lines)
        body = re.sub(r"^__CHAPTER__:(.+)$", r"## \1", transcript, flags=re.MULTILINE)
        return header + body + "\n"

    else:  # txt
        lines = [
            metadata['title'],
            f"ID: {video_id}",
            f"Channel: {metadata['channel']}",
            f"Duration: {duration}",
            f"URL: {url}",
            f"Date: {metadata['date']}",
            f"Views: {views}",
            f"Likes: {likes}",
        ]
        if thumbnail:
            lines.append(f"Thumbnail: {thumbnail}")
        if tags:
            lines.append(f"Tags: {', '.join(tags)}")
        if description:
            desc_preview = description[:300].replace("\n", " ").strip()
            if len(description) > 300:
                desc_preview += "..."
            lines.append(f"Description: {desc_preview}")

        lines.append("=" * 60)
        lines.append("")

        header = "\n".join(lines)

        def _txt_chapter(m):
            title = m.group(1)
            return f"\n{title}\n{'-' * len(title)}"

        body = re.sub(r"^__CHAPTER__:(.+)$", _txt_chapter, transcript, flags=re.MULTILINE)
        return header + body + "\n"


def sanitize_filename(title: str, max_length: int = 80) -> str:
    """Create a safe filename from a video title."""
    # Remove problematic characters including shell-unsafe and punctuation-heavy chars
    safe = re.sub(r"[<>:\"/\\|?*'$&#@!%^(){}[\]+~`]", '', title)
    # Replace whitespace with underscores
    safe = re.sub(r'\s+', '_', safe)
    # Remove leading/trailing dots and underscores
    safe = safe.strip('._')
    # Truncate at last full word boundary to avoid mid-word cuts
    if len(safe) > max_length:
        truncated = safe[:max_length]
        last_underscore = truncated.rfind('_')
        if last_underscore > max_length // 2:
            truncated = truncated[:last_underscore]
        safe = truncated
    return safe if safe else "untitled"


def process_videos(
    video_ids: list[str],
    output_dir: str,
    fmt: str = "md",
    merge: bool = False,
    keep_timestamps: bool = False,
    langs: list[str] | None = None,
    chapters: bool = True
) -> dict:
    """Process a list of video IDs and produce output files.

    Args:
        langs: List of language codes to download. Defaults to ["en"].
               When multiple languages are requested, each gets its own
               output file (with language suffix) or its own key in
               structured exports. Languages that are unavailable for a
               given video are skipped gracefully.
        chapters: If True (default), detect and use YouTube chapters when
                  available. Falls back gracefully to flat output when a
                  video has no chapters.

    Returns a summary dict with results.
    """
    if langs is None:
        langs = ["en"]
    multi_lang = len(langs) > 1

    os.makedirs(output_dir, exist_ok=True)
    work_dir = os.path.join(output_dir, ".work")
    os.makedirs(work_dir, exist_ok=True)

    results = {
        "success": [],
        "no_subs": [],
        "failed": [],
        "output_files": []
    }

    merged_content = []
    structured_records = []  # For JSON/CSV export

    for i, vid in enumerate(video_ids, 1):
        vid = vid.strip()
        if not vid:
            continue

        print(f"[{i}/{len(video_ids)}] Processing: {vid}", flush=True)

        # Get metadata (fetch description too if chapters are enabled)
        meta = get_video_metadata(vid, include_description=chapters)
        print(f"  Title: {meta['title']}", flush=True)

        # Parse chapters from description if available
        video_chapters = []
        if chapters and meta.get("description"):
            video_chapters = parse_chapters_from_description(meta["description"])
            if video_chapters:
                print(f"  📑 Found {len(video_chapters)} chapters", flush=True)

        # Download transcripts (single or multi-language)
        if multi_lang:
            lang_results = download_transcripts_multi(vid, work_dir, langs)
            # Filter to languages that succeeded
            available = {l: p for l, p in lang_results.items() if p is not None}
            if not available:
                print(f"  ⚠ No transcript available in any requested language", flush=True)
                results["no_subs"].append({"id": vid, "title": meta["title"], "languages_tried": langs})
                continue
        else:
            vtt_path = download_transcript(vid, work_dir, langs[0])
            if vtt_path is None:
                print(f"  ⚠ No transcript available", flush=True)
                results["no_subs"].append({"id": vid, "title": meta["title"]})
                continue
            available = {langs[0]: vtt_path}

        # Process each available language
        video_total_words = 0
        lang_transcripts = {}  # For multi-lang JSON

        for lang_code, vtt_path in available.items():
            lang_label = f" [{lang_code}]" if multi_lang else ""

            # Clean the VTT file
            try:
                transcript = clean_vtt(
                    vtt_path, keep_timestamps,
                    chapters=video_chapters if video_chapters else None,
                    video_id=vid,
                    fmt=fmt
                )
                # Strip chapter markers before counting words so they don't inflate the count
                count_text = re.sub(r"^__CHAPTER__:.+$", "", transcript, flags=re.MULTILINE)
                word_count = len(count_text.split())
                video_total_words += word_count
                print(f"  ✓{lang_label} Extracted {word_count:,} words", flush=True)
            except Exception as e:
                print(f"  ✗{lang_label} Failed to clean transcript: {e}", flush=True)
                results["failed"].append({"id": vid, "title": meta["title"], "lang": lang_code, "error": str(e)})
                continue

            # Format and store output
            if fmt in ("json", "csv"):
                # For multi-lang, collect per-language transcripts
                # Strip internal chapter markers from transcript text for structured exports
                clean_transcript = re.sub(r"^__CHAPTER__:.+\n?\n?", "", transcript, flags=re.MULTILINE)
                lang_entry = {"transcript": clean_transcript, "word_count": word_count}
                if fmt == "json" and keep_timestamps:
                    lang_entry["segments"] = structured_transcript(
                        vtt_path, vid,
                        chapters=video_chapters if video_chapters else None
                    )
                lang_transcripts[lang_code] = lang_entry
            else:
                formatted = format_output(vid, meta, transcript, fmt)

                if merge:
                    if multi_lang:
                        # Prefix with language label in merged output
                        formatted = f"**Language: {lang_code}**\n\n{formatted}"
                    merged_content.append(formatted)
                else:
                    safe_title = sanitize_filename(meta["title"])
                    suffix = f"_{lang_code}" if multi_lang else ""
                    ext = fmt
                    filepath = os.path.join(output_dir, f"{safe_title}{suffix}.{ext}")
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(formatted)
                    results["output_files"].append(filepath)

        # Build structured record for JSON/CSV
        if fmt in ("json", "csv") and lang_transcripts:
            record = {
                "id": vid,
                "title": meta["title"],
                "channel": meta["channel"],
                "duration": meta["duration"],
                "duration_formatted": format_duration(meta["duration"]),
                "date": meta["date"],
                "url": f"https://www.youtube.com/watch?v={vid}",
                "views": meta.get("view_count"),
                "likes": meta.get("like_count"),
                "thumbnail": meta.get("thumbnail", ""),
                "tags": meta.get("tags", []),
                "chapters": len(video_chapters),
            }
            if meta.get("description"):
                record["description"] = meta["description"]

            if multi_lang:
                # Multi-language: transcripts keyed by language code
                record["languages"] = list(lang_transcripts.keys())
                record["transcripts"] = {}
                total_words = 0
                for lc, entry in lang_transcripts.items():
                    record["transcripts"][lc] = entry
                    total_words += entry["word_count"]
                record["word_count"] = total_words
            else:
                # Single language: flat transcript (existing behavior)
                single = list(lang_transcripts.values())[0]
                record["word_count"] = single["word_count"]
                record["transcript"] = single["transcript"]
                if "segments" in single:
                    record["segments"] = single["segments"]

            structured_records.append(record)

        results["success"].append({
            "id": vid,
            "title": meta["title"],
            "words": video_total_words,
            "duration": meta["duration"],
            "chapters": len(video_chapters),
            "languages": list(available.keys())
        })

        # Delay between videos to avoid YouTube rate limits
        if i < len(video_ids):
            time.sleep(BATCH_DELAY_SECONDS)
    
    # Write merged file if applicable
    if merge and merged_content:
        separator = "\n\n---\n\n" if fmt == "md" else f"\n\n{'=' * 60}\n\n"
        merged_text = separator.join(merged_content)
        
        # Generate a descriptive filename
        if len(results["success"]) == 1:
            filename = sanitize_filename(results["success"][0]["title"])
        else:
            filename = f"ytscribe_batch_{len(results['success'])}_videos"
        
        filepath = os.path.join(output_dir, f"{filename}.{fmt}")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(merged_text)
        results["output_files"].append(filepath)
    
    # Write structured export (JSON or CSV)
    if fmt in ("json", "csv") and structured_records:
        if len(structured_records) == 1:
            filename = sanitize_filename(structured_records[0]["title"])
        else:
            filename = f"ytscribe_batch_{len(structured_records)}_videos"

        if fmt == "json":
            filepath = os.path.join(output_dir, f"{filename}.json")
            # For single video, output the object directly; for batch, output an array
            json_data = structured_records[0] if len(structured_records) == 1 else structured_records
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(json_data, f, indent=2, ensure_ascii=False, default=str)
            results["output_files"].append(filepath)

        elif fmt == "csv":
            filepath = os.path.join(output_dir, f"{filename}.csv")
            csv_columns = [
                "id", "title", "channel", "duration", "duration_formatted",
                "date", "url", "views", "likes", "thumbnail", "tags",
                "word_count", "chapters", "transcript"
            ]
            with open(filepath, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=csv_columns, extrasaction="ignore")
                writer.writeheader()
                for record in structured_records:
                    row = dict(record)
                    # Flatten tags list to comma-separated string for CSV
                    row["tags"] = ", ".join(row.get("tags", []))
                    writer.writerow(row)
            results["output_files"].append(filepath)

    # Auto-zip if 6+ individual files
    if not merge and len(results["output_files"]) >= 6:
        date_str = datetime.now().strftime("%Y-%m-%d")
        zip_path = os.path.join(output_dir, f"ytscribe_{len(results['output_files'])}_transcripts_{date_str}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fp in results["output_files"]:
                zf.write(fp, os.path.basename(fp))
        results["zip_file"] = zip_path
        print(f"\n📦 Zipped {len(results['output_files'])} transcripts → {os.path.basename(zip_path)}", flush=True)
    
    # Clean up work directory
    shutil.rmtree(work_dir, ignore_errors=True)
    
    # Print summary
    total = len(video_ids)
    print(f"\n{'=' * 40}")
    print(f"ytscribe — Summary")
    print(f"{'=' * 40}")
    print(f"✓ Success:    {len(results['success'])}/{total}")
    if results["no_subs"]:
        print(f"⚠ No subs:    {len(results['no_subs'])}/{total}")
    if results["failed"]:
        print(f"✗ Failed:     {len(results['failed'])}/{total}")
    
    total_words = sum(r["words"] for r in results["success"])
    print(f"📝 Total words: {total_words:,}")
    print(f"📁 Output files: {len(results['output_files'])}")
    
    return results


CONFIG_FILENAME = "ytscribe.config.json"

# Valid keys and their expected types for config validation
CONFIG_SCHEMA = {
    "format": str,
    "merge": bool,
    "timestamps": bool,
    "lang": str,
    "chapters": bool,
    "output_dir": str,
}

VALID_FORMATS = {"txt", "md", "json", "csv"}


def find_config_file(start_dir: str | None = None) -> str | None:
    """Walk up from start_dir looking for ytscribe.config.json.

    Returns the path to the first config file found, or None.
    Stops at the filesystem root.
    """
    current = Path(start_dir) if start_dir else Path.cwd()
    for directory in [current, *current.parents]:
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return str(candidate)
    return None


def load_config(config_path: str | None = None) -> dict:
    """Load and validate a ytscribe config file.

    Returns a dict of validated config values. Unknown keys are ignored.
    Invalid values print a warning and are skipped. Returns an empty
    dict if no config file is found or if it cannot be parsed.
    """
    if config_path is None:
        config_path = find_config_file()
    if config_path is None:
        return {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠ Could not read config file {config_path}: {e}", file=sys.stderr)
        return {}

    if not isinstance(raw, dict):
        print(f"⚠ Config file must be a JSON object, got {type(raw).__name__}", file=sys.stderr)
        return {}

    validated = {}
    for key, expected_type in CONFIG_SCHEMA.items():
        if key not in raw:
            continue
        value = raw[key]
        if not isinstance(value, expected_type):
            print(f"⚠ Config: '{key}' should be {expected_type.__name__}, got {type(value).__name__} — skipping",
                  file=sys.stderr)
            continue
        # Extra validation for constrained values
        if key == "format" and value not in VALID_FORMATS:
            print(f"⚠ Config: 'format' must be one of {sorted(VALID_FORMATS)}, got '{value}' — skipping", file=sys.stderr)
            continue
        validated[key] = value

    unknown_keys = set(raw.keys()) - set(CONFIG_SCHEMA.keys())
    if unknown_keys:
        print(f"⚠ Config: unknown keys ignored: {', '.join(sorted(unknown_keys))}", file=sys.stderr)

    if validated:
        print(f"✓ Loaded config from {config_path}", flush=True)

    return validated


def main():
    # --- First pass: parse only --config to know which config source to use ---
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--config", default=None)
    pre_args, _ = pre_parser.parse_known_args()

    # Load config: explicit path wins, otherwise auto-detect from CWD
    config = load_config(pre_args.config)

    # --- Build argparse with config-aware defaults ---
    # Config values override hardcoded defaults; CLI flags override config.
    parser = argparse.ArgumentParser(description="ytscribe — YouTube Transcript Extractor")
    parser.add_argument("--videos", required=True, help="Comma-separated video IDs")
    parser.add_argument("--format", choices=["txt", "md", "json", "csv"],
                        default=config.get("format", "md"), help="Output format")
    parser.add_argument("--merge", type=lambda x: x.lower() == "true",
                        default=config.get("merge", False), help="Merge into single file")
    parser.add_argument("--output-dir",
                        default=config.get("output_dir", "./ytscribe_output"), help="Output directory")
    parser.add_argument("--timestamps", type=lambda x: x.lower() == "true",
                        default=config.get("timestamps", False), help="Keep timestamps")
    parser.add_argument("--lang",
                        default=config.get("lang", "en"),
                        help="Subtitle language code(s), comma-separated for multi-language (e.g. en,fr,es)")
    parser.add_argument("--chapters", type=lambda x: x.lower() == "true",
                        default=config.get("chapters", True),
                        help="Detect and use YouTube chapters (default: true)")
    parser.add_argument("--config", default=None,
                        help="Path to config file (default: auto-detect ytscribe.config.json)")

    args = parser.parse_args()

    video_ids = [v.strip() for v in args.videos.split(",") if v.strip()]

    if not video_ids:
        print("Error: No video IDs provided", file=sys.stderr)
        sys.exit(1)

    if len(video_ids) > 50:
        print(f"Warning: {len(video_ids)} videos requested. Processing first 50.", file=sys.stderr)
        video_ids = video_ids[:50]

    # Parse language codes (comma-separated)
    lang_list = [l.strip() for l in args.lang.split(",") if l.strip()]
    if not lang_list:
        lang_list = ["en"]

    results = process_videos(
        video_ids=video_ids,
        output_dir=args.output_dir,
        fmt=args.format,
        merge=args.merge,
        keep_timestamps=args.timestamps,
        langs=lang_list,
        chapters=args.chapters
    )
    
    # Output results as JSON for Claude to parse
    print("\n---JSON_RESULTS---")
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
