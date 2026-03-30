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


def get_video_metadata(video_id: str) -> dict:
    """Fetch video metadata without downloading."""
    result = run_ytdlp([
        "--skip-download",
        "--print", "%(title)s|||%(channel)s|||%(duration)s|||%(upload_date)s",
        f"https://www.youtube.com/watch?v={video_id}"
    ])
    if result.returncode != 0:
        return {"title": f"Video {video_id}", "channel": "Unknown", "duration": 0, "date": "Unknown"}
    
    parts = result.stdout.strip().split("|||")
    if len(parts) >= 4:
        duration = int(parts[2]) if parts[2].isdigit() else 0
        date_raw = parts[3]
        date_formatted = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}" if len(date_raw) == 8 else date_raw
        return {
            "title": parts[0],
            "channel": parts[1],
            "duration": duration,
            "date": date_formatted
        }
    return {"title": f"Video {video_id}", "channel": "Unknown", "duration": 0, "date": "Unknown"}


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


def clean_vtt(vtt_path: str, keep_timestamps: bool = False) -> str:
    """Clean VTT subtitle file to plain text.
    
    YouTube auto-generated VTT files have duplicate lines because captions
    are shown progressively with overlapping timestamps. This function
    deduplicates while preserving speaking order.
    """
    with open(vtt_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    lines = content.split("\n")
    text_lines = []
    seen = set()
    current_timestamp = None
    
    for line in lines:
        # Skip VTT header and metadata
        if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        
        # Capture timestamp if needed
        ts_match = re.match(r"^(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->", line)
        if ts_match:
            current_timestamp = ts_match.group(1)
            # Simplify timestamp: remove hours if 00, remove milliseconds
            ts = current_timestamp
            if ts.startswith("00:"):
                ts = ts[3:]
            ts = ts.split(".")[0]  # Remove milliseconds
            current_timestamp = ts
            continue
        
        # Skip empty lines
        if not line.strip():
            continue
        
        # Strip HTML tags (YouTube uses <c> tags for word-level timing)
        clean = re.sub(r"<[^>]+>", "", line).strip()
        
        if clean and clean not in seen:
            seen.add(clean)
            if keep_timestamps and current_timestamp:
                text_lines.append(f"[{current_timestamp}] {clean}")
            else:
                text_lines.append(clean)
    
    if keep_timestamps:
        return "\n".join(text_lines)
    else:
        # Join into flowing prose with spaces
        return " ".join(text_lines)


def format_output(video_id: str, metadata: dict, transcript: str, fmt: str) -> str:
    """Format a single transcript with metadata."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    duration = format_duration(metadata["duration"])
    
    if fmt == "md":
        header = f"""# {metadata['title']}

- **Channel:** {metadata['channel']}
- **Duration:** {duration}
- **URL:** {url}
- **Date:** {metadata['date']}

---

"""
        return header + transcript + "\n"
    
    else:  # txt
        header = f"""{metadata['title']}
Channel: {metadata['channel']}
Duration: {duration}
URL: {url}
Date: {metadata['date']}
{'=' * 60}

"""
        return header + transcript + "\n"


def sanitize_filename(title: str, max_length: int = 80) -> str:
    """Create a safe filename from a video title."""
    # Remove or replace problematic characters
    safe = re.sub(r'[<>:"/\\|?*]', '', title)
    safe = re.sub(r'\s+', '_', safe)
    safe = safe.strip('._')
    return safe[:max_length] if safe else "untitled"


def process_videos(
    video_ids: list[str],
    output_dir: str,
    fmt: str = "md",
    merge: bool = False,
    keep_timestamps: bool = False,
    lang: str = "en"
) -> dict:
    """Process a list of video IDs and produce output files.
    
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
        
        # Get metadata
        meta = get_video_metadata(vid)
        print(f"  Title: {meta['title']}", flush=True)
        
        # Download transcript
        vtt_path = download_transcript(vid, work_dir, lang)
        
        if vtt_path is None:
            print(f"  ⚠ No transcript available", flush=True)
            results["no_subs"].append({"id": vid, "title": meta["title"]})
            continue
        
        # Clean the VTT file
        try:
            transcript = clean_vtt(vtt_path, keep_timestamps)
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
            "duration": meta["duration"]
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
        zip_path = os.path.join(output_dir, f"ytscribe_batch_{len(results['output_files'])}_videos.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fp in results["output_files"]:
                zf.write(fp, os.path.basename(fp))
        results["zip_file"] = zip_path
        print(f"\n📦 Zipped {len(results['output_files'])} files → {zip_path}", flush=True)
    
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
        lang=args.lang
    )
    
    # Output results as JSON for Claude to parse
    print("\n---JSON_RESULTS---")
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
