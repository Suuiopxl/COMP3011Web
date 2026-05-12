"""
Unit tests for ``src.main`` (the interactive shell).

Strategy
--------
The shell is split into two layers we can test independently:

* ``SearchEngineShell.execute`` — a *pure* dispatcher we feed strings
  to and assert against stdout. No mocking of ``input()`` required.
* ``SearchEngineShell.run_repl`` — the input loop. Tests patch
  ``builtins.input`` to feed a script of commands and to simulate
  EOFError / KeyboardInterrupt.

Network-touching pieces (the ``Crawler``) are monkey-patched so no
HTTP traffic is generated during the test run.
"""

from __future__ import annotations

import builtins
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import pytest

from src.crawler import CrawledPage
from src.main import (
    BANNER,
    HELP_TEXT,
    SearchEngineShell,
    main,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def shell(tmp_path) -> SearchEngineShell:
    """A fresh shell with a temp index path (no real disk writes survive)."""
    return SearchEngineShell(index_path=tmp_path / "idx.json", delay=0.0)


@pytest.fixture
def loaded_shell(tmp_path) -> SearchEngineShell:
    """A shell whose index is pre-populated in memory."""
    sh = SearchEngineShell(index_path=tmp_path / "idx.json", delay=0.0)
    sh.index = {
        "index": {
            "good": {
                "df": 2,
                "postings": {
                    "u1": {"tf": 3, "positions": [0, 1, 2]},
                    "u2": {"tf": 1, "positions": [5]},
                },
            },
            "friends": {
                "df": 1,
                "postings": {"u2": {"tf": 2, "positions": [6, 7]}},
            },
        },
        "doc_lengths": {"u1": 10, "u2": 12},
        "num_docs": 2,
    }
    return sh


def _scripted_input(lines) -> "Iterator[str]":
    """Return a function suitable for monkey-patching ``builtins.input``."""
    it = iter(lines)
    def fake_input(prompt: str = "") -> str:
        try:
            return next(it)
        except StopIteration:
            raise EOFError  # End the REPL after the last scripted line
    return fake_input


# ---------------------------------------------------------------------------
# Dispatcher: empty / unknown / case
# ---------------------------------------------------------------------------
class TestExecuteDispatch:
    def test_empty_line_produces_no_output(self, shell, capsys):
        shell.execute("")
        shell.execute("   ")
        shell.execute("\t\n")
        assert capsys.readouterr().out == ""

    def test_unknown_command_reports_error(self, shell, capsys):
        shell.execute("frobnicate")
        out = capsys.readouterr().out
        assert "Unknown command" in out
        assert "frobnicate" in out
        assert "help" in out

    def test_command_is_case_insensitive(self, shell, capsys):
        shell.execute("HELP")
        out = capsys.readouterr().out
        assert "Available commands" in out

    def test_leading_trailing_whitespace_stripped(self, shell, capsys):
        shell.execute("   help   ")
        assert "Available commands" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# help
# ---------------------------------------------------------------------------
class TestHelp:
    def test_help_lists_all_brief_commands(self, shell, capsys):
        shell.execute("help")
        out = capsys.readouterr().out
        for cmd in ("build", "load", "print", "find"):
            assert cmd in out

    def test_help_text_constant_matches_output(self, shell, capsys):
        shell.execute("help")
        assert capsys.readouterr().out == HELP_TEXT


# ---------------------------------------------------------------------------
# build (with the Crawler mocked out)
# ---------------------------------------------------------------------------
class TestBuild:
    @pytest.fixture
    def patched_crawler(self, monkeypatch):
        """Replace Crawler.crawl with a stub that returns deterministic pages."""
        fake_pages = [
            CrawledPage(url="https://x/1", text="hello world hello"),
            CrawledPage(url="https://x/2", text="hello"),
        ]

        class StubCrawler:
            DEFAULT_BASE_URL = "https://x/"

            def __init__(self, *a, **kw):
                pass

            def crawl(self):
                return fake_pages

        monkeypatch.setattr("src.main.Crawler", StubCrawler)
        return fake_pages

    def test_build_populates_in_memory_index(self, shell, patched_crawler, capsys):
        shell.execute("build")
        assert shell.index is not None
        assert shell.index["num_docs"] == 2
        assert "hello" in shell.index["index"]

    def test_build_writes_index_file(self, shell, patched_crawler):
        shell.execute("build")
        assert shell.index_path.exists()

    def test_build_prints_summary(self, shell, patched_crawler, capsys):
        shell.execute("build")
        out = capsys.readouterr().out
        assert "2 docs" in out
        assert str(shell.index_path) in out

    def test_build_handles_empty_crawl(self, shell, monkeypatch, capsys):
        class EmptyCrawler:
            DEFAULT_BASE_URL = "https://x/"

            def __init__(self, *a, **kw):
                pass

            def crawl(self):
                return []

        monkeypatch.setattr("src.main.Crawler", EmptyCrawler)
        shell.execute("build")
        assert shell.index is None
        assert "Build failed" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------
class TestLoad:
    def test_load_missing_file_prints_hint(self, shell, capsys):
        shell.execute("load")
        out = capsys.readouterr().out
        assert "build" in out  # message says "run build first"
        assert shell.index is None  # state unchanged

    def test_load_existing_file_populates_index(self, shell, capsys, tmp_path):
        # Create a real on-disk index via build's pipeline.
        from src.storage import save_index

        sample = {
            "index": {"hi": {"df": 1, "postings": {"u": {"tf": 1, "positions": [0]}}}},
            "doc_lengths": {"u": 1},
            "num_docs": 1,
        }
        save_index(sample, shell.index_path)

        shell.execute("load")
        assert shell.index == sample
        assert "Loaded index" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# print
# ---------------------------------------------------------------------------
class TestPrint:
    def test_print_without_arg_shows_usage(self, shell, capsys):
        shell.execute("print")
        assert "Usage:" in capsys.readouterr().out

    def test_print_without_index_prompts_to_build(self, shell, capsys):
        shell.execute("print hello")
        assert "No index loaded" in capsys.readouterr().out

    def test_print_known_word(self, loaded_shell, capsys):
        loaded_shell.execute("print good")
        out = capsys.readouterr().out
        assert "df=2" in out
        assert "u1" in out and "u2" in out

    def test_print_unknown_word(self, loaded_shell, capsys):
        loaded_shell.execute("print xyz")
        assert "not in index" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# find
# ---------------------------------------------------------------------------
class TestFind:
    def test_find_without_arg_shows_usage(self, shell, capsys):
        shell.execute("find")
        assert "Usage:" in capsys.readouterr().out

    def test_find_without_index_prompts_to_build(self, shell, capsys):
        shell.execute("find anything")
        assert "No index loaded" in capsys.readouterr().out

    def test_find_single_word(self, loaded_shell, capsys):
        loaded_shell.execute("find good")
        out = capsys.readouterr().out
        assert "2 page(s) found" in out
        assert "u1" in out and "u2" in out

    def test_find_multiword_and_intersection(self, loaded_shell, capsys):
        loaded_shell.execute("find good friends")
        out = capsys.readouterr().out
        assert "1 page(s) found" in out
        assert "u2" in out and "u1" not in out

    def test_find_no_matches(self, loaded_shell, capsys):
        loaded_shell.execute("find xyz")
        assert "No pages contain all of" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# REPL loop — exit handling
# ---------------------------------------------------------------------------
class TestReplExitPaths:
    def test_exit_keyword_returns_zero(self, shell, capsys, monkeypatch):
        monkeypatch.setattr(builtins, "input", _scripted_input(["exit"]))
        assert shell.run_repl() == 0

    def test_quit_keyword_returns_zero(self, shell, capsys, monkeypatch):
        monkeypatch.setattr(builtins, "input", _scripted_input(["quit"]))
        assert shell.run_repl() == 0

    def test_eof_returns_zero(self, shell, capsys, monkeypatch):
        # _scripted_input raises EOFError when the script is exhausted.
        monkeypatch.setattr(builtins, "input", _scripted_input([]))
        assert shell.run_repl() == 0

    def test_keyboard_interrupt_returns_zero(self, shell, capsys, monkeypatch):
        def boom(prompt: str = "") -> str:
            raise KeyboardInterrupt
        monkeypatch.setattr(builtins, "input", boom)
        assert shell.run_repl() == 0

    def test_banner_printed_on_start(self, shell, capsys, monkeypatch):
        monkeypatch.setattr(builtins, "input", _scripted_input(["exit"]))
        shell.run_repl()
        assert BANNER in capsys.readouterr().out


# ---------------------------------------------------------------------------
# REPL loop — full scripted session
# ---------------------------------------------------------------------------
class TestReplScripted:
    def test_help_then_exit(self, shell, capsys, monkeypatch):
        monkeypatch.setattr(
            builtins, "input", _scripted_input(["help", "exit"])
        )
        shell.run_repl()
        out = capsys.readouterr().out
        assert "Available commands" in out

    def test_print_before_load_then_load_then_print(
        self, loaded_shell, capsys, monkeypatch
    ):
        # Simulate a realistic session: typo, valid query, exit.
        monkeypatch.setattr(
            builtins,
            "input",
            _scripted_input(["wat", "print good", "exit"]),
        )
        loaded_shell.run_repl()
        out = capsys.readouterr().out
        assert "Unknown command" in out
        assert "df=2" in out

    def test_blank_lines_do_not_break_loop(self, shell, capsys, monkeypatch):
        monkeypatch.setattr(
            builtins, "input", _scripted_input(["", "  ", "help", "exit"])
        )
        assert shell.run_repl() == 0
        assert "Available commands" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# main() entry point + argparse
# ---------------------------------------------------------------------------
class TestMainEntryPoint:
    def test_main_respects_index_arg(self, capsys, monkeypatch, tmp_path):
        custom_path = tmp_path / "custom.json"
        monkeypatch.setattr(builtins, "input", _scripted_input(["exit"]))
        rc = main(["--index", str(custom_path)])
        assert rc == 0

    def test_main_respects_delay_arg(self, capsys, monkeypatch, tmp_path):
        captured = {}

        class StubShell:
            def __init__(self, *, base_url, delay, index_path):
                captured["delay"] = delay
                captured["base_url"] = base_url

            def run_repl(self):
                return 0

        monkeypatch.setattr("src.main.SearchEngineShell", StubShell)
        main(["--delay", "0.25"])
        assert captured["delay"] == 0.25

    def test_help_flag_exits_cleanly(self, capsys):
        # argparse exits with code 0 on --help; SystemExit propagates.
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0