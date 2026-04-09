"""Tests for VTT parsing, clean_vtt, and structured_transcript."""
import os

import ytscribe


class TestVttTimestampToSeconds:
    """Tests for _vtt_timestamp_to_seconds."""

    def test_hhmmss(self):
        assert ytscribe._vtt_timestamp_to_seconds("00:12:34.567") == 754

    def test_mmss(self):
        assert ytscribe._vtt_timestamp_to_seconds("12:34") == 754

    def test_zero(self):
        assert ytscribe._vtt_timestamp_to_seconds("00:00:00.000") == 0

    def test_hours(self):
        assert ytscribe._vtt_timestamp_to_seconds("01:00:00.000") == 3600

    def test_single_segment(self):
        """Single number with no colons should return 0."""
        assert ytscribe._vtt_timestamp_to_seconds("42") == 0


class TestParseVttEntries:
    """Tests for _parse_vtt_entries using the sample fixture."""

    def test_deduplication(self, sample_vtt_path):
        """Duplicate lines in VTT should be removed."""
        entries = ytscribe._parse_vtt_entries(sample_vtt_path)
        texts = [text for _, _, text in entries]
        # "Hello and welcome to the show." appears twice in the VTT but should appear once
        assert texts.count("Hello and welcome to the show.") == 1
        # "testing strategies." also appears twice
        assert texts.count("testing strategies.") == 1

    def test_html_tags_stripped(self, sample_vtt_path):
        """HTML tags like <c.colorCCCCCC> should be removed."""
        entries = ytscribe._parse_vtt_entries(sample_vtt_path)
        texts = [text for _, _, text in entries]
        for text in texts:
            assert "<" not in text
            assert ">" not in text

    def test_timestamps_extracted(self, sample_vtt_path):
        """Each entry should have a valid seconds value and display timestamp."""
        entries = ytscribe._parse_vtt_entries(sample_vtt_path)
        assert len(entries) > 0
        # First entry should be at ~1 second
        assert entries[0][0] == 1
        assert entries[0][1] == "00:01"

    def test_headers_skipped(self, sample_vtt_path):
        """WEBVTT, Kind:, Language: lines should not appear in entries."""
        entries = ytscribe._parse_vtt_entries(sample_vtt_path)
        texts = [text for _, _, text in entries]
        for text in texts:
            assert not text.startswith("WEBVTT")
            assert not text.startswith("Kind:")
            assert not text.startswith("Language:")

    def test_entry_count(self, sample_vtt_path):
        """After deduplication, the sample should have 8 unique lines."""
        entries = ytscribe._parse_vtt_entries(sample_vtt_path)
        assert len(entries) == 8

    def test_empty_vtt_file(self, tmp_path):
        """An empty VTT file should return no entries."""
        empty_vtt = tmp_path / "empty.vtt"
        empty_vtt.write_text("WEBVTT\n\n")
        entries = ytscribe._parse_vtt_entries(str(empty_vtt))
        assert entries == []


class TestCleanVtt:
    """Tests for clean_vtt."""

    def test_prose_mode(self, sample_vtt_path):
        """Default mode: clean prose with no timestamps."""
        result = ytscribe.clean_vtt(sample_vtt_path)
        # Should be a single string of space-joined text
        assert "\n" not in result
        assert "Hello and welcome to the show." in result
        assert "Thanks for watching, goodbye!" in result
        # No timestamps in prose mode
        assert "[0:" not in result

    def test_timestamps_mode(self, sample_vtt_path):
        """With keep_timestamps=True, each line gets a timestamp bracket."""
        result = ytscribe.clean_vtt(sample_vtt_path, keep_timestamps=True)
        lines = result.strip().split("\n")
        assert len(lines) > 0
        # Each line should start with a timestamp bracket
        for line in lines:
            assert line.startswith("[")

    def test_clickable_timestamps_md(self, sample_vtt_path):
        """Markdown format with timestamps should produce clickable links."""
        result = ytscribe.clean_vtt(
            sample_vtt_path, keep_timestamps=True,
            video_id="test123", fmt="md"
        )
        # Should contain markdown links
        assert "](https://youtube.com/watch?v=test123&t=" in result

    def test_plain_timestamps_txt(self, sample_vtt_path):
        """Plain text format should have plain bracket timestamps, no links."""
        result = ytscribe.clean_vtt(
            sample_vtt_path, keep_timestamps=True,
            video_id="test123", fmt="txt"
        )
        # Should NOT contain markdown links
        assert "](https://" not in result
        # Should contain plain brackets
        assert "[00:01]" in result

    def test_chapters_split(self, sample_vtt_path, sample_chapters_text):
        """With chapters, transcript should be split into chapter sections."""
        chapters = ytscribe.parse_chapters_from_description(sample_chapters_text)
        result = ytscribe.clean_vtt(sample_vtt_path, chapters=chapters)
        # Should contain chapter markers
        assert "__CHAPTER__:Introduction" in result
        assert "__CHAPTER__:Testing Strategies" in result
        assert "__CHAPTER__:Conclusion and Wrap-up" in result

    def test_no_chapters_fallback(self, sample_vtt_path):
        """With no chapters (None or []), should produce flat prose."""
        result_none = ytscribe.clean_vtt(sample_vtt_path, chapters=None)
        result_empty = ytscribe.clean_vtt(sample_vtt_path, chapters=[])
        # Both should be identical flat prose
        assert result_none == result_empty
        assert "__CHAPTER__" not in result_none

    def test_chapters_with_timestamps(self, sample_vtt_path, sample_chapters_text):
        """Chapters + timestamps should produce timestamped lines under chapter markers."""
        chapters = ytscribe.parse_chapters_from_description(sample_chapters_text)
        result = ytscribe.clean_vtt(
            sample_vtt_path, keep_timestamps=True, chapters=chapters
        )
        assert "__CHAPTER__:Introduction" in result
        # Timestamped lines within sections
        assert "[00:01]" in result


class TestStructuredTranscript:
    """Tests for structured_transcript (JSON export)."""

    def test_basic_structure(self, sample_vtt_path):
        """Each entry should have time, seconds, url, and text fields."""
        entries = ytscribe.structured_transcript(sample_vtt_path, "test123")
        assert len(entries) > 0
        for entry in entries:
            assert "time" in entry
            assert "seconds" in entry
            assert "url" in entry
            assert "text" in entry
            assert "test123" in entry["url"]

    def test_url_format(self, sample_vtt_path):
        """URLs should point to youtube with the correct video ID and timestamp."""
        entries = ytscribe.structured_transcript(sample_vtt_path, "abc123")
        first = entries[0]
        assert first["url"] == f"https://youtube.com/watch?v=abc123&t={first['seconds']}"

    def test_with_chapters(self, sample_vtt_path, sample_chapters_text):
        """Entries should include a chapter field when chapters are provided."""
        chapters = ytscribe.parse_chapters_from_description(sample_chapters_text)
        entries = ytscribe.structured_transcript(sample_vtt_path, "test123", chapters=chapters)
        # First entry (at 1s) should be in "Introduction" chapter
        assert entries[0]["chapter"] == "Introduction"
        # Entry at 12:34 (754s) should be in "Conclusion and Wrap-up"
        late_entries = [e for e in entries if e["seconds"] >= 754]
        assert len(late_entries) > 0
        assert late_entries[0]["chapter"] == "Conclusion and Wrap-up"

    def test_without_chapters(self, sample_vtt_path):
        """Without chapters, entries should not have a chapter field."""
        entries = ytscribe.structured_transcript(sample_vtt_path, "test123")
        for entry in entries:
            assert "chapter" not in entry

    def test_no_chapter_field_when_none(self, sample_vtt_path):
        """Passing chapters=None should behave same as no chapters."""
        entries = ytscribe.structured_transcript(sample_vtt_path, "test123", chapters=None)
        for entry in entries:
            assert "chapter" not in entry
