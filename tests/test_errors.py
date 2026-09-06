"""Tests for yt-dlp failure classification.

Before these existed, every yt-dlp failure (a bot check, a rate limit, a
release YouTube had since broken) surfaced as "no subs", the one outcome a
caller is allowed to trust as final. These tests pin the distinction.
"""
import os
import sys
from datetime import datetime

import pytest

import ytscribe

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


class Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestClassifyYtdlpError:
    def test_clean_run_is_not_an_error(self):
        assert ytscribe.classify_ytdlp_error(Result()) is None

    def test_warnings_only_are_not_an_error(self):
        """yt-dlp reports 'no subtitles for the requested languages' as a warning with exit 0."""
        r = Result(stderr="WARNING: [youtube] abc: There are no subtitles for the requested languages")
        assert ytscribe.classify_ytdlp_error(r) is None

    def test_bot_check(self):
        r = Result(returncode=1, stderr=(
            "ERROR: [youtube] 4C4Ex5z5IHo: Sign in to confirm you’re not a bot. "
            "Use --cookies-from-browser or --cookies for the authentication."
        ))
        err = ytscribe.classify_ytdlp_error(r)
        assert err.kind == ytscribe.KIND_BOT_CHECK
        assert err.systemic
        assert err.reason.startswith("Sign in to confirm")
        assert "cookies" in err.hint

    def test_rate_limit(self):
        r = Result(returncode=1, stderr="ERROR: [youtube] abc: HTTP Error 429: Too Many Requests")
        err = ytscribe.classify_ytdlp_error(r)
        assert err.kind == ytscribe.KIND_RATE_LIMIT
        assert err.systemic

    def test_stale_extractor(self):
        """The exact error a 2025 yt-dlp produced against YouTube in September 2026."""
        r = Result(returncode=1, stderr=(
            "ERROR: [youtube] 1DsffcZa70M: The page needs to be reloaded.. The page needs to be reloaded."
        ))
        err = ytscribe.classify_ytdlp_error(r)
        assert err.kind == ytscribe.KIND_EXTRACTOR
        assert err.systemic
        assert "pip install -U yt-dlp" in err.hint

    def test_unable_to_extract_is_extractor(self):
        r = Result(returncode=1, stderr="ERROR: [youtube] abc: Unable to extract player version; please report this issue")
        assert ytscribe.classify_ytdlp_error(r).kind == ytscribe.KIND_EXTRACTOR

    def test_unavailable_is_not_systemic(self):
        r = Result(returncode=1, stderr="ERROR: [youtube] abc: Video unavailable. This video is private")
        err = ytscribe.classify_ytdlp_error(r)
        assert err.kind == ytscribe.KIND_UNAVAILABLE
        assert not err.systemic

    def test_unknown_error_line(self):
        r = Result(returncode=1, stderr="ERROR: something nobody has seen before")
        err = ytscribe.classify_ytdlp_error(r)
        assert err.kind == ytscribe.KIND_UNKNOWN
        assert err.reason == "something nobody has seen before"

    def test_nonzero_exit_without_error_line(self):
        err = ytscribe.classify_ytdlp_error(Result(returncode=3))
        assert err.kind == ytscribe.KIND_UNKNOWN
        assert "code 3" in err.reason

    def test_reason_strips_extractor_prefix(self):
        r = Result(returncode=1, stderr="ERROR: [youtube] dQw4w9WgXcQ: Video unavailable")
        assert ytscribe.classify_ytdlp_error(r).reason == "Video unavailable"

    def test_error_in_stdout_counts_too(self):
        r = Result(returncode=1, stdout="ERROR: [youtube] abc: Sign in to confirm you're not a bot")
        assert ytscribe.classify_ytdlp_error(r).kind == ytscribe.KIND_BOT_CHECK


class TestDownloadTranscriptRaises:
    def test_clean_no_file_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ytscribe, "run_ytdlp", lambda args, capture_output=True: Result())
        assert ytscribe.download_transcript("abc123", str(tmp_path)) is None

    def test_extractor_failure_raises_not_none(self, tmp_path, monkeypatch):
        stale = Result(returncode=1, stderr="ERROR: [youtube] abc123: The page needs to be reloaded.")
        monkeypatch.setattr(ytscribe, "run_ytdlp", lambda args, capture_output=True: stale)
        with pytest.raises(ytscribe.YtDlpError) as excinfo:
            ytscribe.download_transcript("abc123", str(tmp_path))
        assert excinfo.value.kind == ytscribe.KIND_EXTRACTOR

    def test_bot_check_raises(self, tmp_path, monkeypatch):
        blocked = Result(returncode=1, stderr="ERROR: [youtube] abc123: Sign in to confirm you're not a bot")
        monkeypatch.setattr(ytscribe, "run_ytdlp", lambda args, capture_output=True: blocked)
        with pytest.raises(ytscribe.YtDlpError) as excinfo:
            ytscribe.download_transcript("abc123", str(tmp_path))
        assert excinfo.value.kind == ytscribe.KIND_BOT_CHECK

    def test_rate_limit_retries_then_raises(self, tmp_path, monkeypatch):
        calls = []
        limited = Result(returncode=1, stderr="ERROR: HTTP Error 429: Too Many Requests")
        monkeypatch.setattr(ytscribe, "run_ytdlp", lambda args, capture_output=True: calls.append(args) or limited)
        monkeypatch.setattr(ytscribe.time, "sleep", lambda s: None)
        with pytest.raises(ytscribe.YtDlpError) as excinfo:
            ytscribe.download_transcript("abc123", str(tmp_path))
        assert excinfo.value.kind == ytscribe.KIND_RATE_LIMIT
        # Three yt-dlp calls per attempt (manual, auto, no-lang fallback) times MAX_RETRIES
        assert len(calls) == 3 * ytscribe.MAX_RETRIES

    def test_unavailable_raises(self, tmp_path, monkeypatch):
        gone = Result(returncode=1, stderr="ERROR: [youtube] abc123: Video unavailable")
        monkeypatch.setattr(ytscribe, "run_ytdlp", lambda args, capture_output=True: gone)
        with pytest.raises(ytscribe.YtDlpError) as excinfo:
            ytscribe.download_transcript("abc123", str(tmp_path))
        assert excinfo.value.kind == ytscribe.KIND_UNAVAILABLE


class TestProcessVideosFailureHandling:
    @staticmethod
    def _stub_metadata(monkeypatch):
        monkeypatch.setattr(ytscribe, "get_video_metadata", lambda vid, include_description=False: {
            "title": f"Title {vid}", "channel": "Chan", "duration": 60, "date": "2026-01-01",
            "view_count": 1, "like_count": 1, "thumbnail": "", "tags": [],
        })
        monkeypatch.setattr(ytscribe.time, "sleep", lambda s: None)

    def test_systemic_failure_stops_batch_and_lists_unattempted(self, tmp_path, monkeypatch):
        self._stub_metadata(monkeypatch)
        attempted = []

        def fake_download(vid, work_dir, lang="en"):
            attempted.append(vid)
            raise ytscribe.YtDlpError(ytscribe.KIND_EXTRACTOR, "The page needs to be reloaded.")

        monkeypatch.setattr(ytscribe, "download_transcript", fake_download)
        results = ytscribe.process_videos(["v1", "v2", "v3"], str(tmp_path), fmt="txt")

        assert attempted == ["v1"]
        assert results["success"] == []
        assert results["no_subs"] == []
        assert [f["id"] for f in results["failed"]] == ["v1", "v2", "v3"]
        assert results["failed"][0]["kind"] == ytscribe.KIND_EXTRACTOR
        assert "pip install -U yt-dlp" in results["failed"][0]["hint"]
        assert results["failed"][1]["error"].startswith("not attempted")
        assert results["aborted"]["kind"] == ytscribe.KIND_EXTRACTOR
        assert results["aborted"]["after"] == "v1"

    def test_non_systemic_failure_continues(self, tmp_path, monkeypatch, sample_vtt_path):
        self._stub_metadata(monkeypatch)

        def fake_download(vid, work_dir, lang="en"):
            if vid == "gone":
                raise ytscribe.YtDlpError(ytscribe.KIND_UNAVAILABLE, "Video unavailable")
            return sample_vtt_path, ytscribe.SOURCE_AUTO

        monkeypatch.setattr(ytscribe, "download_transcript", fake_download)
        results = ytscribe.process_videos(["gone", "ok"], str(tmp_path), fmt="txt")

        assert [f["id"] for f in results["failed"]] == ["gone"]
        assert results["failed"][0]["kind"] == ytscribe.KIND_UNAVAILABLE
        assert [s["id"] for s in results["success"]] == ["ok"]
        assert "aborted" not in results

    def test_genuine_no_subs_still_reported_as_no_subs(self, tmp_path, monkeypatch):
        self._stub_metadata(monkeypatch)
        monkeypatch.setattr(ytscribe, "download_transcript", lambda vid, work_dir, lang="en": None)
        results = ytscribe.process_videos(["silent"], str(tmp_path), fmt="txt")
        assert [n["id"] for n in results["no_subs"]] == ["silent"]
        assert results["failed"] == []

    def test_summary_prints_hint(self, tmp_path, monkeypatch, capsys):
        self._stub_metadata(monkeypatch)

        def fake_download(vid, work_dir, lang="en"):
            raise ytscribe.YtDlpError(ytscribe.KIND_BOT_CHECK, "Sign in to confirm you're not a bot")

        monkeypatch.setattr(ytscribe, "download_transcript", fake_download)
        ytscribe.process_videos(["v1"], str(tmp_path), fmt="txt")
        out = capsys.readouterr().out
        assert "Failed:     1/1" in out
        assert "bot-checking" in out
        assert "Batch stopped early" in out


class TestYtdlpVersionCheck:
    def test_stale_version_warns(self, monkeypatch, capsys):
        monkeypatch.setattr(ytscribe.subprocess, "run",
                            lambda *a, **k: Result(returncode=0, stdout="2025.10.14\n"))
        version = ytscribe.check_ytdlp_version(now=datetime(2026, 9, 6))
        assert version == "2025.10.14"
        err = capsys.readouterr().err
        assert "days old" in err and "pip install -U yt-dlp" in err

    def test_fresh_version_is_quiet(self, monkeypatch, capsys):
        monkeypatch.setattr(ytscribe.subprocess, "run",
                            lambda *a, **k: Result(returncode=0, stdout="2026.08.19\n"))
        assert ytscribe.check_ytdlp_version(now=datetime(2026, 9, 6)) == "2026.08.19"
        assert capsys.readouterr().err == ""

    def test_missing_ytdlp_returns_none(self, monkeypatch, capsys):
        def boom(*a, **k):
            raise OSError("not found")
        monkeypatch.setattr(ytscribe.subprocess, "run", boom)
        assert ytscribe.check_ytdlp_version() is None
        assert "not found" in capsys.readouterr().err

    def test_command_prefers_interpreter_module(self):
        cmd = ytscribe.ytdlp_command()
        assert cmd == [sys.executable, "-m", "yt_dlp"] or cmd == ["yt-dlp"]
