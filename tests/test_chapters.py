"""Tests for parse_chapters_from_description."""
import ytscribe


class TestParseChapters:
    """Tests for chapter timestamp parsing from YouTube descriptions."""

    def test_valid_chapters(self, sample_chapters_text):
        """Standard description with 4 chapters starting at 0:00."""
        chapters = ytscribe.parse_chapters_from_description(sample_chapters_text)
        assert len(chapters) == 4
        assert chapters[0]["time_seconds"] == 0
        assert chapters[0]["time_label"] == "0:00"
        assert chapters[0]["title"] == "Introduction"
        assert chapters[1]["time_seconds"] == 65
        assert chapters[1]["title"] == "Testing Strategies"
        assert chapters[2]["time_seconds"] == 754
        assert chapters[2]["title"] == "Conclusion and Wrap-up"
        assert chapters[3]["time_seconds"] == 1500
        assert chapters[3]["title"] == "Outro"

    def test_sorted_by_time(self):
        """Chapters are returned sorted even if description is out of order."""
        desc = "12:00 Middle\n0:00 Start\n25:00 End"
        chapters = ytscribe.parse_chapters_from_description(desc)
        assert len(chapters) == 3
        assert chapters[0]["time_seconds"] == 0
        assert chapters[1]["time_seconds"] == 720
        assert chapters[2]["time_seconds"] == 1500

    def test_fewer_than_three_timestamps(self):
        """YouTube requires at least 3 chapters — fewer should return empty."""
        desc = "0:00 Intro\n5:00 Outro"
        chapters = ytscribe.parse_chapters_from_description(desc)
        assert chapters == []

    def test_does_not_start_at_zero(self):
        """Chapters that don't start at or near 0:00 should return empty."""
        desc = "2:00 First topic\n5:00 Second topic\n10:00 Third topic"
        chapters = ytscribe.parse_chapters_from_description(desc)
        assert chapters == []

    def test_starts_near_zero(self):
        """Chapters starting within 5 seconds of 0:00 should be accepted."""
        desc = "0:03 Intro\n5:00 Middle\n10:00 End"
        chapters = ytscribe.parse_chapters_from_description(desc)
        assert len(chapters) == 3
        assert chapters[0]["time_seconds"] == 3

    def test_empty_description(self):
        """Empty string should return empty list."""
        assert ytscribe.parse_chapters_from_description("") == []

    def test_none_like_empty(self):
        """None-ish input should return empty list."""
        assert ytscribe.parse_chapters_from_description("") == []

    def test_no_timestamps_in_text(self):
        """Plain text with no timestamps should return empty list."""
        desc = "This is just a normal video description.\nNo chapters here."
        assert ytscribe.parse_chapters_from_description(desc) == []

    def test_hhmmss_format(self):
        """Chapters with HH:MM:SS timestamps should be parsed correctly."""
        desc = "0:00:00 Intro\n0:15:30 Main content\n1:02:45 Wrap-up"
        chapters = ytscribe.parse_chapters_from_description(desc)
        assert len(chapters) == 3
        assert chapters[0]["time_seconds"] == 0
        assert chapters[0]["time_label"] == "0:00:00"
        assert chapters[1]["time_seconds"] == 930
        assert chapters[2]["time_seconds"] == 3765

    def test_bullet_prefixed_timestamps(self):
        """Timestamps preceded by bullet characters should still be parsed."""
        desc = "• 0:00 Intro\n• 5:00 Middle\n• 10:00 End"
        chapters = ytscribe.parse_chapters_from_description(desc)
        assert len(chapters) == 3

    def test_dash_prefixed_timestamps(self):
        """Timestamps preceded by dashes should still be parsed."""
        desc = "- 0:00 Intro\n- 5:00 Middle\n- 10:00 End"
        chapters = ytscribe.parse_chapters_from_description(desc)
        assert len(chapters) == 3

    def test_separator_variants(self):
        """Various separators between timestamp and title should work."""
        desc = "0:00 - Intro\n5:00 — Middle\n10:00: End"
        chapters = ytscribe.parse_chapters_from_description(desc)
        assert len(chapters) == 3
        assert chapters[0]["title"] == "Intro"
        assert chapters[1]["title"] == "Middle"
        assert chapters[2]["title"] == "End"

    def test_timestamps_mixed_with_other_text(self):
        """Only lines starting with timestamps should be detected."""
        desc = """Check out my website at example.com

0:00 Introduction
Some random text in between
5:00 Main Topic
More random text
10:00 Conclusion

Like and subscribe!"""
        chapters = ytscribe.parse_chapters_from_description(desc)
        assert len(chapters) == 3
        assert chapters[0]["title"] == "Introduction"
