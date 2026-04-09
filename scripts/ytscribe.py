#!/usr/bin/env python3
"""
ytscribe — YouTube Transcript Extractor
Extracts, cleans, and formats YouTube video transcripts using yt-dlp.

Usage:
  python3 ytscribe.py --videos "ID1,ID2,ID3" --format md --merge true --output-dir ./output
  python3 ytscribe.py --videos "dQw4w9WgXcQ" --format txt --timestamps true
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from datetime import timedelta
from pathlib import Path

# Delay between requests to avoid YouTube 429 rate limits.
# YouTube throttles subtitle downloads after ~15-20 rapid requests.
BATCH_DELAY_SECONDS = 2
RETRY_DELAY_SECONDS = 5
MAX_RETRIES = 3


def run_ytdlp(args: list[str], capture_output=True) -> subprocess.CompletedProcess:
    """Run yt-dlp with standard flags."""
    cmd = ["yt-dlp", "--no-check-certificates", "--no-warnings"] + args
    return subprocess.run(cmd, capture_output=capture_output, text=True, timeout=60)


def parse_chapters_from_description(description: str, video_duration: int = 0) -> list[dict]:
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


def get_video_metadata(video_id: str, fetch_description: bool = False) -> dict:
    """Fetch video metadata without downloading. Retries up to 3 times on failure.

    Always fetches rich metadata (view count, like count, thumbnail, tags).
    If fetch_description is True, also fetches the video description
    (needed for chapter parsing).
    """
    # Use JSON dump for reliable parsing -- avoids delimiter issues with
    # fields like description that can contain arbitrary text.
    json_fields = [
        "title", "channel", "duration", "upload_date",
        "view_count", "like_count", "thumbnail", "tags"
    ]
    if fetch_description:
        json_fields.append("description")

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
                if fetch_description:
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


def _vtt_timestamp_to_seconds(ts: str) -> int:
    """Convert a VTT timestamp like '00:12:34.567' to integer seconds."""
    ts = ts.split(".")[0]  # drop milliseconds
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return 0


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
    with open(vtt_path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    # First pass: extract (seconds, display_timestamp, text) tuples
    entries = []
    seen = set()
    current_raw_ts = None  # full VTT timestamp for seconds conversion
    current_display_ts = None  # simplified display timestamp

    for line in lines:
        # Skip VTT header and metadata
        if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue

        # Capture timestamp
        ts_match = re.match(r"^(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->", line)
        if ts_match:
            current_raw_ts = ts_match.group(1)
            # Simplify timestamp: remove hours if 00, remove milliseconds
            ts = current_raw_ts.split(".")[0]
            if ts.startswith("00:"):
                ts = ts[3:]
            current_display_ts = ts
            continue

        # Skip empty lines
        if not line.strip():
            continue

        # Strip HTML tags (YouTube uses <c> tags for word-level timing)
        clean = re.sub(r"<[^>]+>", "", line).strip()

        if clean and clean not in seen:
            seen.add(clean)
            seconds = _vtt_timestamp_to_seconds(current_raw_ts) if current_raw_ts else 0
            entries.append((seconds, current_display_ts, clean))

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


def _format_count(n) -> str:
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
    lang: str = "en",
    chapters: bool = True
) -> dict:
    """Process a list of video IDs and produce output files.

    Args:
        chapters: If True (default), detect and use YouTube chapters when
                  available. Falls back gracefully to flat output when a
                  video has no chapters.

    Returns a summary dict with results.
    """
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

    for i, vid in enumerate(video_ids, 1):
        vid = vid.strip()
        if not vid:
            continue

        print(f"[{i}/{len(video_ids)}] Processing: {vid}", flush=True)

        # Get metadata (fetch description too if chapters are enabled)
        meta = get_video_metadata(vid, fetch_description=chapters)
        print(f"  Title: {meta['title']}", flush=True)

        # Parse chapters from description if available
        video_chapters = []
        if chapters and meta.get("description"):
            video_chapters = parse_chapters_from_description(
                meta["description"], meta.get("duration", 0)
            )
            if video_chapters:
                print(f"  📑 Found {len(video_chapters)} chapters", flush=True)

        # Download transcript
        vtt_path = download_transcript(vid, work_dir, lang)

        if vtt_path is None:
            print(f"  ⚠ No transcript available", flush=True)
            results["no_subs"].append({"id": vid, "title": meta["title"]})
            continue

        # Clean the VTT file (pass chapters if found, otherwise None for flat output)
        try:
            transcript = clean_vtt(
                vtt_path, keep_timestamps,
                chapters=video_chapters if video_chapters else None,
                video_id=vid,
                fmt=fmt
            )
            word_count = len(transcript.split())
            print(f"  ✓ Extracted {word_count:,} words", flush=True)
        except Exception as e:
            print(f"  ✗ Failed to clean transcript: {e}", flush=True)
            results["failed"].append({"id": vid, "title": meta["title"], "error": str(e)})
            continue
        
        # Format output
        formatted = format_output(vid, meta, transcript, fmt)
        
        if merge:
            merged_content.append(formatted)
        else:
            # Save individual file
            safe_title = sanitize_filename(meta["title"])
            ext = fmt
            filepath = os.path.join(output_dir, f"{safe_title}.{ext}")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(formatted)
            results["output_files"].append(filepath)
        
        results["success"].append({
            "id": vid,
            "title": meta["title"],
            "words": word_count,
            "duration": meta["duration"],
            "chapters": len(video_chapters)
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
    
    # Auto-zip if 6+ individual files
    if not merge and len(results["output_files"]) >= 6:
        from datetime import datetime
        date_str = datetime.now().strftime("%Y-%m-%d")
        zip_path = os.path.join(output_dir, f"ytscribe_{len(results['output_files'])}_transcripts_{date_str}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fp in results["output_files"]:
                zf.write(fp, os.path.basename(fp))
        results["zip_file"] = zip_path
        print(f"\n📦 Zipped {len(results['output_files'])} transcripts → {os.path.basename(zip_path)}", flush=True)
    
    # Clean up work directory
    import shutil
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


def main():
    parser = argparse.ArgumentParser(description="ytscribe — YouTube Transcript Extractor")
    parser.add_argument("--videos", required=True, help="Comma-separated video IDs")
    parser.add_argument("--format", choices=["txt", "md"], default="md", help="Output format")
    parser.add_argument("--merge", type=lambda x: x.lower() == "true", default=False, help="Merge into single file")
    parser.add_argument("--output-dir", default="./ytscribe_output", help="Output directory")
    parser.add_argument("--timestamps", type=lambda x: x.lower() == "true", default=False, help="Keep timestamps")
    parser.add_argument("--lang", default="en", help="Subtitle language code")
    parser.add_argument("--chapters", type=lambda x: x.lower() == "true", default=True,
                        help="Detect and use YouTube chapters (default: true)")

    args = parser.parse_args()
    
    video_ids = [v.strip() for v in args.videos.split(",") if v.strip()]
    
    if not video_ids:
        print("Error: No video IDs provided", file=sys.stderr)
        sys.exit(1)
    
    if len(video_ids) > 50:
        print(f"Warning: {len(video_ids)} videos requested. Processing first 50.", file=sys.stderr)
        video_ids = video_ids[:50]
    
    results = process_videos(
        video_ids=video_ids,
        output_dir=args.output_dir,
        fmt=args.format,
        merge=args.merge,
        keep_timestamps=args.timestamps,
        lang=args.lang,
        chapters=args.chapters
    )
    
    # Output results as JSON for Claude to parse
    print("\n---JSON_RESULTS---")
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
