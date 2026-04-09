"""Tests for format_output, format_duration, _format_count, and sanitize_filename."""
import ytscribe


class TestFormatDuration:
    """Tests for format_duration."""

    def test_zero(self):
        assert ytscribe.format_duration(0) == "Unknown"

    def test_negative(self):
        assert ytscribe.format_duration(-5) == "Unknown"

    def test_seconds_only(self):
        assert ytscribe.format_duration(45) == "45s"

    def test_minutes_and_seconds(self):
        assert ytscribe.format_duration(65) == "1m 5s"

    def test_hours_minutes_seconds(self):
        assert ytscribe.format_duration(3661) == "1h 1m 1s"

    def test_exact_hour(self):
        assert ytscribe.format_duration(3600) == "1h 0m 0s"

    def test_exact_minute(self):
        assert ytscribe.format_duration(60) == "1m 0s"

    def test_large_duration(self):
        # 10 hours
        assert ytscribe.format_duration(36000) == "10h 0m 0s"


class TestFormatCount:
    """Tests for _format_count."""

    def test_none(self):
        assert ytscribe._format_count(None) == "N/A"

    def test_zero(self):
        assert ytscribe._format_count(0) == "0"

    def test_small_number(self):
        assert ytscribe._format_count(42) == "42"

    def test_thousands(self):
        assert ytscribe._format_count(1500) == "1,500"

    def test_millions(self):
        assert ytscribe._format_count(1500000) == "1,500,000"

    def test_float_truncated(self):
        """Floats from API responses should be cast to int."""
        assert ytscribe._format_count(1234.56) == "1,234"


class TestSanitizeFilename:
    """Tests for sanitize_filename."""

    def test_simple_title(self):
        assert ytscribe.sanitize_filename("Hello World") == "Hello_World"

    def test_special_characters_removed(self):
        result = ytscribe.sanitize_filename('Test <Video> "Title" | Part 1')
        assert "<" not in result
        assert ">" not in result
        assert '"' not in result
        assert "|" not in result

    def test_whitespace_to_underscores(self):
        result = ytscribe.sanitize_filename("Multiple   Spaces   Here")
        assert "  " not in result
        assert result == "Multiple_Spaces_Here"

    def test_long_title_truncated(self):
        long_title = "A " * 100  # 200 chars
        result = ytscribe.sanitize_filename(long_title, max_length=80)
        assert len(result) <= 80

    def test_truncation_at_word_boundary(self):
        title = "Short_Word " * 20
        result = ytscribe.sanitize_filename(title, max_length=50)
        # Should not end mid-word
        assert not result.endswith("_Sho")

    def test_all_special_chars(self):
        """Title made entirely of special chars should return 'untitled'."""
        assert ytscribe.sanitize_filename('!@#$%^&*()') == "untitled"

    def test_empty_string(self):
        assert ytscribe.sanitize_filename("") == "untitled"

    def test_leading_dots_stripped(self):
        result = ytscribe.sanitize_filename("...Hidden File")
        assert not result.startswith(".")

    def test_unicode_preserved(self):
        """Non-ASCII characters that aren't in the strip list should survive."""
        result = ytscribe.sanitize_filename("日本語テスト")
        assert result == "日本語テスト"

    def test_em_dash_preserved(self):
        """Em dashes are common in YouTube titles and should survive."""
        result = ytscribe.sanitize_filename("Part 1 — The Beginning")
        assert "—" in result


class TestFormatOutput:
    """Tests for format_output."""

    def test_md_format_has_heading(self, sample_metadata):
        result = ytscribe.format_output("test123", sample_metadata, "Hello world.", "md")
        assert result.startswith("# Test Video Title")

    def test_md_format_has_metadata(self, sample_metadata):
        result = ytscribe.format_output("test123", sample_metadata, "Hello world.", "md")
        assert "**ID:** test123" in result
        assert "**Channel:** Test Channel" in result
        assert "**Duration:** 12m 34s" in result
        assert "**Views:** 1,500,000" in result
        assert "**Likes:** 42,000" in result
        assert "**Tags:** python, testing, tutorial" in result

    def test_md_format_has_separator(self, sample_metadata):
        result = ytscribe.format_output("test123", sample_metadata, "Hello world.", "md")
        assert "\n---\n" in result

    def test_txt_format_has_title(self, sample_metadata):
        result = ytscribe.format_output("test123", sample_metadata, "Hello world.", "txt")
        assert result.startswith("Test Video Title")

    def test_txt_format_has_separator(self, sample_metadata):
        result = ytscribe.format_output("test123", sample_metadata, "Hello world.", "txt")
        assert "=" * 60 in result

    def test_txt_format_no_markdown(self, sample_metadata):
        result = ytscribe.format_output("test123", sample_metadata, "Hello world.", "txt")
        assert "**" not in result
        assert "# " not in result

    def test_md_chapter_markers_converted(self, sample_metadata):
        """__CHAPTER__ markers should become ## headings in md."""
        transcript = "__CHAPTER__:Introduction\n\nHello world."
        result = ytscribe.format_output("test123", sample_metadata, transcript, "md")
        assert "## Introduction" in result
        assert "__CHAPTER__" not in result

    def test_txt_chapter_markers_converted(self, sample_metadata):
        """__CHAPTER__ markers should become underlined titles in txt."""
        transcript = "__CHAPTER__:Introduction\n\nHello world."
        result = ytscribe.format_output("test123", sample_metadata, transcript, "txt")
        assert "Introduction" in result
        assert "-----------" in result
        assert "__CHAPTER__" not in result

    def test_missing_optional_fields(self):
        """Should handle missing optional metadata gracefully."""
        minimal_meta = {
            "title": "Minimal Video",
            "channel": "Unknown",
            "duration": 60,
            "date": "2026-01-01",
            "view_count": None,
            "like_count": None,
            "thumbnail": "",
            "tags": [],
        }
        result = ytscribe.format_output("vid1", minimal_meta, "Content here.", "md")
        assert "**Views:** N/A" in result
        assert "**Likes:** N/A" in result
        # No thumbnail or tags lines when empty
        assert "Thumbnail" not in result
        assert "Tags" not in result

    def test_description_truncated(self, sample_metadata):
        """Long descriptions should be truncated to 300 chars with ellipsis."""
        sample_metadata["description"] = "A" * 500
        result = ytscribe.format_output("test123", sample_metadata, "Content.", "md")
        assert "..." in result
