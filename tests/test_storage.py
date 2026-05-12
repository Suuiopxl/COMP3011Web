"""
Unit tests for ``src.storage``.

Every test that touches disk uses pytest's ``tmp_path`` fixture so the
real ``data/`` directory is never written to during the test run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.storage import (
    DEFAULT_INDEX_PATH,
    IndexNotFoundError,
    load_index,
    save_index,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_index():
    """A minimal but well-formed index."""
    return {
        "index": {
            "good": {
                "df": 2,
                "postings": {
                    "https://example.com/1": {"tf": 2, "positions": [3, 17]},
                    "https://example.com/2": {"tf": 1, "positions": [5]},
                },
            },
            "world": {
                "df": 1,
                "postings": {
                    "https://example.com/1": {"tf": 1, "positions": [0]},
                },
            },
        },
        "doc_lengths": {
            "https://example.com/1": 25,
            "https://example.com/2": 10,
        },
        "num_docs": 2,
    }


# ---------------------------------------------------------------------------
# Round-trip integrity
# ---------------------------------------------------------------------------
class TestRoundTrip:
    def test_save_then_load_returns_equal_index(self, tmp_path, sample_index):
        path = tmp_path / "idx.json"
        save_index(sample_index, path)
        loaded = load_index(path)
        assert loaded == sample_index

    def test_round_trip_preserves_nested_structure(self, tmp_path, sample_index):
        path = tmp_path / "idx.json"
        save_index(sample_index, path)
        loaded = load_index(path)
        # Drill into a deeply-nested value to confirm structure is intact.
        assert loaded["index"]["good"]["postings"][
            "https://example.com/1"
        ]["positions"] == [3, 17]

    def test_round_trip_with_empty_index(self, tmp_path):
        empty = {"index": {}, "doc_lengths": {}, "num_docs": 0}
        path = tmp_path / "empty.json"
        save_index(empty, path)
        assert load_index(path) == empty

    def test_round_trip_preserves_unicode_text(self, tmp_path):
        # quotes.toscrape uses curly quotes (U+201C/D); make sure they survive.
        idx = {
            "index": {
                "caf\u00e9": {  # café
                    "df": 1,
                    "postings": {"https://x/": {"tf": 1, "positions": [0]}},
                }
            },
            "doc_lengths": {"https://x/": 1},
            "num_docs": 1,
        }
        path = tmp_path / "unicode.json"
        save_index(idx, path)
        assert load_index(path) == idx


# ---------------------------------------------------------------------------
# Saving — file system behaviour
# ---------------------------------------------------------------------------
class TestSaving:
    def test_creates_parent_directories(self, tmp_path, sample_index):
        path = tmp_path / "deep" / "nested" / "idx.json"
        assert not path.parent.exists()
        save_index(sample_index, path)
        assert path.exists()

    def test_overwrites_existing_file(self, tmp_path, sample_index):
        path = tmp_path / "idx.json"
        path.write_text("garbage")
        save_index(sample_index, path)
        assert load_index(path) == sample_index

    def test_writes_pretty_printed_json(self, tmp_path, sample_index):
        path = tmp_path / "idx.json"
        save_index(sample_index, path)
        # Pretty-printed JSON has many newlines; minified has none.
        content = path.read_text(encoding="utf-8")
        assert content.count("\n") > 5

    def test_no_tmp_file_left_after_successful_save(self, tmp_path, sample_index):
        path = tmp_path / "idx.json"
        save_index(sample_index, path)
        # After atomic rename, the .tmp sidecar must not linger.
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == []


# ---------------------------------------------------------------------------
# Loading — error handling
# ---------------------------------------------------------------------------
class TestLoadingErrors:
    def test_missing_file_raises_index_not_found(self, tmp_path):
        with pytest.raises(IndexNotFoundError):
            load_index(tmp_path / "nope.json")

    def test_index_not_found_is_a_filenotfounderror(self, tmp_path):
        """Generic ``except FileNotFoundError`` still works."""
        with pytest.raises(FileNotFoundError):
            load_index(tmp_path / "nope.json")

    def test_error_message_suggests_running_build(self, tmp_path):
        with pytest.raises(IndexNotFoundError, match="build"):
            load_index(tmp_path / "nope.json")

    def test_non_object_json_rejected(self, tmp_path):
        path = tmp_path / "wrong.json"
        path.write_text("[1, 2, 3]")  # JSON array, not an object
        with pytest.raises(ValueError, match="object"):
            load_index(path)

    def test_missing_top_level_keys_rejected(self, tmp_path):
        path = tmp_path / "wrong.json"
        path.write_text('{"index": {}}')  # missing doc_lengths & num_docs
        with pytest.raises(ValueError, match="missing keys"):
            load_index(path)

    def test_invalid_json_raises_decode_error(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not valid json")
        with pytest.raises(json.JSONDecodeError):
            load_index(path)


# ---------------------------------------------------------------------------
# Path handling
# ---------------------------------------------------------------------------
class TestPaths:
    def test_default_path_is_data_index_json(self):
        assert DEFAULT_INDEX_PATH == Path("data/index.json")

    def test_accepts_string_path(self, tmp_path, sample_index):
        path_str = str(tmp_path / "idx.json")
        save_index(sample_index, path_str)
        assert load_index(path_str) == sample_index

    def test_accepts_pathlib_path(self, tmp_path, sample_index):
        path_obj = tmp_path / "idx.json"
        save_index(sample_index, path_obj)
        assert load_index(path_obj) == sample_index


# ---------------------------------------------------------------------------
# Atomicity sanity check
# ---------------------------------------------------------------------------
class TestAtomicity:
    def test_existing_file_preserved_if_save_interrupted(
        self, tmp_path, sample_index, monkeypatch
    ):
        """If ``os.replace`` fails, the original index must survive
        and no half-written file is left at the destination."""
        path = tmp_path / "idx.json"
        # Pre-populate with a known-good index.
        original = {
            "index": {"old": {"df": 1, "postings": {"u": {"tf": 1, "positions": [0]}}}},
            "doc_lengths": {"u": 1},
            "num_docs": 1,
        }
        save_index(original, path)

        # Now simulate a crash during the atomic rename.
        def boom(*args, **kwargs):
            raise OSError("simulated disk failure")

        monkeypatch.setattr("src.storage.os.replace", boom)

        with pytest.raises(OSError, match="simulated"):
            save_index(sample_index, path)

        # The original file is intact — the would-be overwrite never landed.
        assert load_index(path) == original