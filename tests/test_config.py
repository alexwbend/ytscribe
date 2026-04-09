"""Tests for load_config and find_config_file."""
import json
import os

import pytest

import ytscribe


class TestFindConfigFile:
    """Tests for find_config_file."""

    def test_config_in_current_dir(self, tmp_path):
        """Should find config in the given directory."""
        config_path = tmp_path / "ytscribe.config.json"
        config_path.write_text('{"format": "txt"}')
        result = ytscribe.find_config_file(str(tmp_path))
        assert result == str(config_path)

    def test_config_in_parent_dir(self, tmp_path):
        """Should walk up and find config in a parent directory."""
        config_path = tmp_path / "ytscribe.config.json"
        config_path.write_text('{"format": "txt"}')
        child = tmp_path / "subdir" / "deep"
        child.mkdir(parents=True)
        result = ytscribe.find_config_file(str(child))
        assert result == str(config_path)

    def test_no_config_found(self, tmp_path):
        """Should return None when no config exists anywhere up the tree."""
        child = tmp_path / "empty" / "deep"
        child.mkdir(parents=True)
        result = ytscribe.find_config_file(str(child))
        assert result is None


class TestLoadConfig:
    """Tests for load_config."""

    def test_valid_full_config(self, tmp_config):
        """All valid keys should be returned."""
        path = tmp_config({
            "format": "json",
            "merge": True,
            "timestamps": True,
            "lang": "fr",
            "chapters": False,
            "output_dir": "/tmp/output"
        })
        config = ytscribe.load_config(path)
        assert config == {
            "format": "json",
            "merge": True,
            "timestamps": True,
            "lang": "fr",
            "chapters": False,
            "output_dir": "/tmp/output"
        }

    def test_partial_config(self, tmp_config):
        """Only provided keys should appear; missing keys should not be present."""
        path = tmp_config({"format": "csv"})
        config = ytscribe.load_config(path)
        assert config == {"format": "csv"}
        assert "merge" not in config
        assert "timestamps" not in config

    def test_empty_object(self, tmp_config):
        """Empty JSON object should return empty dict."""
        path = tmp_config({})
        config = ytscribe.load_config(path)
        assert config == {}

    def test_invalid_json(self, tmp_path):
        """Malformed JSON should return empty dict and not crash."""
        bad_file = tmp_path / "ytscribe.config.json"
        bad_file.write_text("not json at all {{{")
        config = ytscribe.load_config(str(bad_file))
        assert config == {}

    def test_non_dict_json(self, tmp_path):
        """JSON that is an array or scalar should return empty dict."""
        bad_file = tmp_path / "ytscribe.config.json"
        bad_file.write_text('[1, 2, 3]')
        config = ytscribe.load_config(str(bad_file))
        assert config == {}

    def test_wrong_type_for_key(self, tmp_config):
        """Keys with wrong types should be skipped."""
        path = tmp_config({
            "format": 123,          # should be str
            "merge": "yes",         # should be bool
            "timestamps": True      # correct
        })
        config = ytscribe.load_config(path)
        # Only timestamps should survive
        assert config == {"timestamps": True}

    def test_invalid_format_value(self, tmp_config):
        """Format value not in VALID_FORMATS should be skipped."""
        path = tmp_config({"format": "docx"})
        config = ytscribe.load_config(path)
        assert config == {}

    def test_valid_format_values(self, tmp_config):
        """All four valid format values should be accepted."""
        for fmt in ["txt", "md", "json", "csv"]:
            path = tmp_config({"format": fmt})
            config = ytscribe.load_config(path)
            assert config == {"format": fmt}

    def test_unknown_keys_ignored(self, tmp_config):
        """Unknown keys should not appear in the result."""
        path = tmp_config({
            "format": "md",
            "unknown_key": "value",
            "another_bad": 42
        })
        config = ytscribe.load_config(path)
        assert config == {"format": "md"}
        assert "unknown_key" not in config

    def test_nonexistent_path(self):
        """Passing a path that doesn't exist should return empty dict."""
        config = ytscribe.load_config("/nonexistent/path/config.json")
        assert config == {}

    def test_none_path_no_config(self, tmp_path, monkeypatch):
        """With no config file present and None path, should return empty dict."""
        monkeypatch.chdir(tmp_path)
        config = ytscribe.load_config(None)
        assert config == {}
