"""Shared fixtures for ytscribe tests."""
import os
import sys

import pytest

# Add the scripts directory to the Python path so we can import ytscribe
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, SCRIPTS_DIR)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def sample_vtt_path():
    """Path to the sample VTT fixture file."""
    return os.path.join(FIXTURES_DIR, "sample.vtt")


@pytest.fixture
def sample_chapters_text():
    """Contents of the sample chapters fixture file."""
    path = os.path.join(FIXTURES_DIR, "sample_chapters.txt")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def sample_metadata():
    """A realistic metadata dict for testing format_output."""
    return {
        "title": "Test Video Title",
        "channel": "Test Channel",
        "duration": 754,
        "date": "2026-04-09",
        "view_count": 1500000,
        "like_count": 42000,
        "thumbnail": "https://i.ytimg.com/vi/test123/maxresdefault.jpg",
        "tags": ["python", "testing", "tutorial"],
        "description": "This is a test video description that explains the content.",
    }


@pytest.fixture
def tmp_config(tmp_path):
    """Helper to create a temporary config file and return its path."""
    def _write(data: dict) -> str:
        path = tmp_path / "ytscribe.config.json"
        import json
        with open(path, "w") as f:
            json.dump(data, f)
        return str(path)
    return _write
