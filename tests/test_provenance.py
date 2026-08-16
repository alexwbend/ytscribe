"""Tests for caption provenance: manual vs auto-generated tracks."""
import os

import pytest

import ytscribe


class TestFindVtt:
    """Tests for _find_vtt."""

    def test_returns_none_when_empty(self, tmp_path):
        assert ytscribe._find_vtt(str(tmp_path), "abc123") is None

    def test_finds_exact_lang(self, tmp_path):
        (tmp_path / "abc123.en.vtt").write_text("WEBVTT\n")
        found = ytscribe._find_vtt(str(tmp_path), "abc123")
        assert found is not None and found.endswith("abc123.en.vtt")

    def test_finds_regional_lang_variant(self, tmp_path):
        """yt-dlp resolves --sub-lang en to en-US/en-GB; probing {id}.en.vtt misses those."""
        (tmp_path / "abc123.en-US.vtt").write_text("WEBVTT\n")
        found = ytscribe._find_vtt(str(tmp_path), "abc123")
        assert found is not None and found.endswith("abc123.en-US.vtt")

    def test_ignores_other_videos(self, tmp_path):
        (tmp_path / "other99.en.vtt").write_text("WEBVTT\n")
        assert ytscribe._find_vtt(str(tmp_path), "abc123") is None

    def test_ignores_non_vtt(self, tmp_path):
        (tmp_path / "abc123.en.srt").write_text("1\n")
        assert ytscribe._find_vtt(str(tmp_path), "abc123") is None


class TestDownloadTranscriptProvenance:
    """download_transcript must report which flag produced the file."""

    @staticmethod
    def _fake_ytdlp(tmp_path, write_on):
        """Build a run_ytdlp stub that writes a VTT only for the given flag."""
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake(args, capture_output=True):
            if write_on is not None and write_on in args:
                (tmp_path / "abc123.en.vtt").write_text("WEBVTT\n")
            return Result()

        return fake

    def test_manual_track_reported_as_manual(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ytscribe, "run_ytdlp", self._fake_ytdlp(tmp_path, "--write-sub"))
        path, source = ytscribe.download_transcript("abc123", str(tmp_path))
        assert source == ytscribe.SOURCE_MANUAL
        assert path.endswith("abc123.en.vtt")

    def test_auto_track_reported_as_auto(self, tmp_path, monkeypatch):
        """No manual track available, so --write-auto-sub is what lands."""
        monkeypatch.setattr(ytscribe, "run_ytdlp", self._fake_ytdlp(tmp_path, "--write-auto-sub"))
        path, source = ytscribe.download_transcript("abc123", str(tmp_path))
        assert source == ytscribe.SOURCE_AUTO

    def test_regional_manual_variant_not_mislabelled_as_auto(self, tmp_path, monkeypatch):
        """Regression: a manual en-US track used to fall through to the
        no-language fallback branch and get reported as auto-generated."""
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake(args, capture_output=True):
            if "--write-sub" in args:
                (tmp_path / "abc123.en-US.vtt").write_text("WEBVTT\n")
            return Result()

        monkeypatch.setattr(ytscribe, "run_ytdlp", fake)
        path, source = ytscribe.download_transcript("abc123", str(tmp_path))
        assert source == ytscribe.SOURCE_MANUAL
        assert path.endswith("abc123.en-US.vtt")

    def test_no_captions_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ytscribe, "run_ytdlp", self._fake_ytdlp(tmp_path, None))
        assert ytscribe.download_transcript("abc123", str(tmp_path)) is None
