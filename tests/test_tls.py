"""Tests for how run_ytdlp builds the yt-dlp command.

Everything ytscribe ingests (probe JSON, caption text, the bot-check and
rate-limit verdicts) arrives over yt-dlp's connection, so TLS certificates are
verified by default. YTSCRIBE_INSECURE_TLS is the one explicit way to turn that
off. subprocess.run is stubbed: no yt-dlp is spawned and nothing touches the
network.
"""
import subprocess

import pytest

import ytscribe


@pytest.fixture
def commands(monkeypatch):
    """Record every command run_ytdlp would have run, with a clean TLS environment."""
    recorded = []

    def fake_run(cmd, **kwargs):
        recorded.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(ytscribe.subprocess, "run", fake_run)
    monkeypatch.setattr(ytscribe, "_insecure_tls_warned", False)
    monkeypatch.delenv(ytscribe.INSECURE_TLS_ENV, raising=False)
    return recorded


class TestRunYtdlpTls:
    def test_verifies_tls_by_default(self, commands, capsys):
        ytscribe.run_ytdlp(["--dump-json", "https://example.test/v"])
        cmd = commands[0]
        assert "--no-check-certificates" not in cmd
        assert "--no-warnings" in cmd
        assert cmd[-2:] == ["--dump-json", "https://example.test/v"]
        assert capsys.readouterr().err == ""

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "Yes", "on", " 1 "])
    def test_opt_in_values_turn_verification_off(self, commands, monkeypatch, value):
        monkeypatch.setenv(ytscribe.INSECURE_TLS_ENV, value)
        ytscribe.run_ytdlp(["https://example.test/v"])
        cmd = commands[0]
        assert cmd.index("--no-check-certificates") < cmd.index("--no-warnings")
        assert cmd[-1] == "https://example.test/v"

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "enabled", "2"])
    def test_anything_else_keeps_verification_on(self, commands, monkeypatch, value):
        monkeypatch.setenv(ytscribe.INSECURE_TLS_ENV, value)
        ytscribe.run_ytdlp(["https://example.test/v"])
        assert "--no-check-certificates" not in commands[0]

    def test_opt_in_warns_once_per_process(self, commands, monkeypatch, capsys):
        monkeypatch.setenv(ytscribe.INSECURE_TLS_ENV, "1")
        for _ in range(3):
            ytscribe.run_ytdlp(["https://example.test/v"])
        err = capsys.readouterr().err
        assert err.count("verification is OFF") == 1
        assert ytscribe.INSECURE_TLS_ENV in err

    def test_environment_is_read_on_every_call(self, commands, monkeypatch):
        ytscribe.run_ytdlp(["a"])
        monkeypatch.setenv(ytscribe.INSECURE_TLS_ENV, "1")
        ytscribe.run_ytdlp(["b"])
        monkeypatch.delenv(ytscribe.INSECURE_TLS_ENV)
        ytscribe.run_ytdlp(["c"])
        assert ["--no-check-certificates" in cmd for cmd in commands] == [False, True, False]
