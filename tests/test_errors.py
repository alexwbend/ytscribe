"""Tests for yt-dlp failure classification.

Before these existed, every yt-dlp failure (a bot check, a rate limit, a
release YouTube had since broken) surfaced as "no subs", the one outcome a
caller is allowed to trust as final. These tests pin the distinction.
"""
import json
import os
import sys
from datetime import datetime

import pytest

import ytscribe

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

# An 11-character video id that happens to contain "429", as ids occasionally do.
ID_WITH_429 = "Xa4291bQ_-z"


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


class TestClassifiesFromFirstErrorLineOnly:
    """The kind comes from the first ERROR line, never from the rest of the output.

    Everything else yt-dlp prints carries the video id, the URL, temp paths and
    (with --dump-json) titles and descriptions. Matching on any of it misfiled
    videos: an id containing "429" read as a rate limit, which is systemic and
    stops the whole batch.
    """

    def test_video_id_containing_429_is_not_a_rate_limit(self):
        r = Result(returncode=1, stderr=f"ERROR: [youtube] {ID_WITH_429}: Video unavailable")
        err = ytscribe.classify_ytdlp_error(r)
        assert err.kind == ytscribe.KIND_UNAVAILABLE
        assert not err.systemic

    def test_429_in_progress_lines_is_ignored(self):
        """The id is in the [youtube] progress lines of every run for that video."""
        r = Result(
            returncode=1,
            stdout=(
                f"[youtube] Extracting URL: https://www.youtube.com/watch?v={ID_WITH_429}\n"
                f"[youtube] {ID_WITH_429}: Downloading webpage\n"
            ),
            stderr=f"ERROR: [youtube] {ID_WITH_429}: Private video. Sign in if you've been granted access to this video",
        )
        assert ytscribe.classify_ytdlp_error(r).kind == ytscribe.KIND_UNAVAILABLE

    def test_temp_path_containing_429_is_not_a_rate_limit(self):
        r = Result(returncode=1, stderr=(
            "ERROR: unable to open for writing: [Errno 13] Permission denied: "
            f"'/var/folders/42/T/tmp4291ab/{ID_WITH_429}.en.vtt'"
        ))
        err = ytscribe.classify_ytdlp_error(r)
        assert err.kind == ytscribe.KIND_UNKNOWN
        assert not err.systemic

    def test_bare_429_in_the_error_line_is_not_a_rate_limit(self):
        r = Result(returncode=1, stderr="ERROR: Unsupported URL: https://example.com/page/429")
        assert ytscribe.classify_ytdlp_error(r).kind == ytscribe.KIND_EXTRACTOR

    def test_marker_text_in_a_title_does_not_decide_the_kind(self):
        """--dump-json stdout carries titles and descriptions; they must not classify."""
        r = Result(
            returncode=1,
            stdout='{"title": "HTTP Error 429: Too Many Requests, explained"}',
            stderr="ERROR: [youtube] abc: Video unavailable",
        )
        assert ytscribe.classify_ytdlp_error(r).kind == ytscribe.KIND_UNAVAILABLE

    def test_first_error_line_wins_over_later_ones(self):
        r = Result(returncode=1, stderr=(
            "ERROR: [youtube] abc: Video unavailable\n"
            "ERROR: [youtube] abc: HTTP Error 429: Too Many Requests"
        ))
        assert ytscribe.classify_ytdlp_error(r).kind == ytscribe.KIND_UNAVAILABLE

    def test_no_error_line_falls_back_to_the_whole_text(self):
        """A crash prints no ERROR line; the traceback is then all there is to go on."""
        r = Result(returncode=1, stderr=(
            "Traceback (most recent call last):\n"
            "yt_dlp.networking.exceptions.HTTPError: HTTP Error 429: Too Many Requests"
        ))
        err = ytscribe.classify_ytdlp_error(r)
        assert err.kind == ytscribe.KIND_RATE_LIMIT
        assert "code 1" in err.reason


class TestRateLimitStillRecognised:
    @pytest.mark.parametrize("line", [
        "ERROR: [youtube] abc: HTTP Error 429: Too Many Requests",
        "ERROR: [youtube] abc: Too Many Requests",
        "ERROR: unable to download video data: HTTPError 429: ",
        f"ERROR: [youtube] {ID_WITH_429}: HTTP Error 429: Too Many Requests",
        # Wrapped in the extractor's generic failure text, which on its own reads as "update yt-dlp".
        "ERROR: [youtube] abc: Unable to download webpage: HTTP Error 429: Too Many Requests "
        "(caused by <HTTPError 429: Too Many Requests>); please report this issue on "
        "https://github.com/yt-dlp/yt-dlp/issues?q=",
    ])
    def test_real_429_text(self, line):
        err = ytscribe.classify_ytdlp_error(Result(returncode=1, stderr=line))
        assert err.kind == ytscribe.KIND_RATE_LIMIT
        assert err.systemic


class TestAgeGate:
    """An age-gated video opens with the same "Sign in to confirm" as a bot check.

    It is permanent without a signed-in session, so it must be unavailable
    (non-systemic, parked by the caller), not a bot check (systemic, retried
    on the next run, forever).
    """

    # The shape yt-dlp builds from YouTube's reason + subreason + its cookie hint.
    AGE_GATE = (
        "ERROR: [youtube] {vid}: Sign in to confirm your age. This video may be inappropriate "
        "for some users. Use --cookies-from-browser or --cookies for the authentication. "
        "See  https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp  "
        "for how to manually pass cookies"
    )

    def test_age_gate_is_unavailable_not_a_bot_check(self):
        err = ytscribe.classify_ytdlp_error(Result(returncode=1, stderr=self.AGE_GATE.format(vid="abcdefghijk")))
        assert err.kind == ytscribe.KIND_UNAVAILABLE
        assert not err.systemic
        assert err.reason.startswith("Sign in to confirm your age")
        assert "age-restricted" in err.hint

    @pytest.mark.parametrize("line", [
        "ERROR: [youtube] abcdefghijk: Sign in to confirm your age",
        "ERROR: [youtube] abcdefghijk: This video is age-restricted; some formats may be missing",
        "ERROR: [youtube] abcdefghijk: This video is age-restricted and YouTube is requiring account age-verification",
        "ERROR: [youtube] abcdefghijk: This video may be inappropriate for some users.",
    ])
    def test_age_gate_wordings(self, line):
        err = ytscribe.classify_ytdlp_error(Result(returncode=1, stderr=line))
        assert err.kind == ytscribe.KIND_UNAVAILABLE
        assert not err.systemic

    def test_age_gate_still_beats_the_429_check_when_the_id_has_429(self):
        err = ytscribe.classify_ytdlp_error(Result(returncode=1, stderr=self.AGE_GATE.format(vid=ID_WITH_429)))
        assert err.kind == ytscribe.KIND_UNAVAILABLE

    def test_real_bot_check_is_not_mistaken_for_an_age_gate(self):
        r = Result(returncode=1, stderr=(
            f"ERROR: [youtube] {ID_WITH_429}: Sign in to confirm you’re not a bot. "
            "Use --cookies-from-browser or --cookies for the authentication. "
            "See  https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp  "
            "for how to manually pass cookies. Also see  "
            "https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies  "
            "for tips on effectively exporting YouTube cookies"
        ))
        err = ytscribe.classify_ytdlp_error(r)
        assert err.kind == ytscribe.KIND_BOT_CHECK
        assert err.systemic


class TestTlsFailure:
    """Once certificates are verified, a failed check is its own kind.

    Its message also carries "Unable to download webpage" and "please report
    this issue", which on their own read as an out-of-date yt-dlp and would send
    people (and the agent that follows SKILL.md) to pip install -U yt-dlp.
    """

    # Verbatim from yt-dlp 2026.08.19 against a local server with a self-signed cert.
    SELF_SIGNED = (
        "ERROR: [generic] localhost:53476: Unable to download webpage: [SSL: CERTIFICATE_VERIFY_FAILED] "
        "certificate verify failed: self-signed certificate (_ssl.c:1016) (caused by "
        "CertificateVerifyError('[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
        "self-signed certificate (_ssl.c:1016)')); please report this issue on  "
        "https://github.com/yt-dlp/yt-dlp/issues?q= , filling out the appropriate issue template. "
        "Confirm you are on the latest version using  yt-dlp -U"
    )

    def test_certificate_failure_is_tls_not_extractor(self):
        err = ytscribe.classify_ytdlp_error(Result(returncode=1, stderr=self.SELF_SIGNED))
        assert err.kind == ytscribe.KIND_TLS
        assert err.systemic
        assert ytscribe.INSECURE_TLS_ENV in err.hint
        assert "pip install -U yt-dlp" not in err.hint

    def test_missing_issuer_is_tls(self):
        r = Result(returncode=1, stderr=(
            "ERROR: [youtube] abcdefghijk: Unable to download webpage: [SSL: CERTIFICATE_VERIFY_FAILED] "
            "certificate verify failed: unable to get local issuer certificate (_ssl.c:1006)"
        ))
        assert ytscribe.classify_ytdlp_error(r).kind == ytscribe.KIND_TLS


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


class TestVideoIdContaining429IsNotRetried:
    """An id that merely contains "429" must not be waited out as a rate limit."""

    @staticmethod
    def _gone():
        return Result(
            returncode=1,
            stdout=f"[youtube] Extracting URL: https://www.youtube.com/watch?v={ID_WITH_429}\n",
            stderr=f"ERROR: [youtube] {ID_WITH_429}: Video unavailable",
        )

    def test_download_transcript_makes_one_attempt(self, tmp_path, monkeypatch):
        calls, sleeps = [], []
        monkeypatch.setattr(ytscribe, "run_ytdlp", lambda args, capture_output=True: calls.append(args) or self._gone())
        monkeypatch.setattr(ytscribe.time, "sleep", sleeps.append)
        with pytest.raises(ytscribe.YtDlpError) as excinfo:
            ytscribe.download_transcript(ID_WITH_429, str(tmp_path))
        assert excinfo.value.kind == ytscribe.KIND_UNAVAILABLE
        # One attempt = manual, auto, and the no-language fallback; no retry, no sleep.
        assert len(calls) == 3
        assert sleeps == []

    def test_metadata_makes_one_attempt(self, monkeypatch, capsys):
        calls, sleeps = [], []
        monkeypatch.setattr(ytscribe, "run_ytdlp", lambda args, capture_output=True: calls.append(args) or self._gone())
        monkeypatch.setattr(ytscribe.time, "sleep", sleeps.append)
        meta = ytscribe.get_video_metadata(ID_WITH_429)
        assert len(calls) == 1
        assert sleeps == []
        assert meta["title"] == f"Video {ID_WITH_429}"
        assert "unavailable" in capsys.readouterr().out


class TestMetadataRateLimitRetry:
    LIMITED = Result(returncode=1, stderr="ERROR: [youtube] abc: HTTP Error 429: Too Many Requests")

    def test_real_rate_limit_is_waited_out_then_succeeds(self, monkeypatch):
        ok = Result(returncode=0, stdout=json.dumps(
            {"title": "T", "channel": "C", "duration": 60, "upload_date": "20260101"}
        ))
        responses = iter([self.LIMITED, ok])
        sleeps = []
        monkeypatch.setattr(ytscribe, "run_ytdlp", lambda args, capture_output=True: next(responses))
        monkeypatch.setattr(ytscribe.time, "sleep", sleeps.append)
        assert ytscribe.get_video_metadata("abc")["title"] == "T"
        assert sleeps == [ytscribe.RETRY_DELAY_SECONDS]

    def test_real_rate_limit_gives_up_after_max_retries(self, monkeypatch):
        calls, sleeps = [], []
        monkeypatch.setattr(ytscribe, "run_ytdlp", lambda args, capture_output=True: calls.append(args) or self.LIMITED)
        monkeypatch.setattr(ytscribe.time, "sleep", sleeps.append)
        meta = ytscribe.get_video_metadata("abc")
        assert len(calls) == ytscribe.MAX_RETRIES
        assert sleeps == [ytscribe.RETRY_DELAY_SECONDS * n for n in range(1, ytscribe.MAX_RETRIES)]
        assert meta["title"] == "Video abc"


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

    def test_age_gated_video_is_unavailable_and_does_not_stop_the_batch(self, tmp_path, monkeypatch, sample_vtt_path):
        self._stub_metadata(monkeypatch)
        gated = Result(returncode=1, stderr=(
            "ERROR: [youtube] gated000001: Sign in to confirm your age. "
            "This video may be inappropriate for some users."
        ))

        monkeypatch.setattr(ytscribe, "run_ytdlp", lambda args, capture_output=True: gated)
        real_download = ytscribe.download_transcript

        def download(vid, work_dir, lang="en"):
            if vid == "gated000001":
                return real_download(vid, work_dir, lang)  # the real classification path
            return sample_vtt_path, ytscribe.SOURCE_MANUAL

        monkeypatch.setattr(ytscribe, "download_transcript", download)
        results = ytscribe.process_videos(["gated000001", "ok"], str(tmp_path), fmt="txt")

        assert [(f["id"], f["kind"]) for f in results["failed"]] == [("gated000001", ytscribe.KIND_UNAVAILABLE)]
        assert [s["id"] for s in results["success"]] == ["ok"]
        assert "aborted" not in results

    def test_tls_failure_stops_batch_with_its_own_hint(self, tmp_path, monkeypatch):
        self._stub_metadata(monkeypatch)

        def fake_download(vid, work_dir, lang="en"):
            raise ytscribe.YtDlpError(
                ytscribe.KIND_TLS, "Unable to download webpage: [SSL: CERTIFICATE_VERIFY_FAILED]")

        monkeypatch.setattr(ytscribe, "download_transcript", fake_download)
        results = ytscribe.process_videos(["v1", "v2"], str(tmp_path), fmt="txt")

        assert results["aborted"]["kind"] == ytscribe.KIND_TLS
        assert [f["id"] for f in results["failed"]] == ["v1", "v2"]
        assert ytscribe.INSECURE_TLS_ENV in results["failed"][0]["hint"]
        assert "pip install -U yt-dlp" not in results["failed"][0]["hint"]

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
