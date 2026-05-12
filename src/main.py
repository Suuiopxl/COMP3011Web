"""
Interactive shell for the COMP3011 search engine.

Run with::

    python -m src.main

The four commands specified by the brief are implemented exactly as
written there: ``build``, ``load``, ``print <word>``, ``find <terms>``.
A small ``help`` command and graceful exit paths (``exit`` / ``quit`` /
Ctrl-D / Ctrl-C) round out the user experience.

Design decisions (defend these in the video)
--------------------------------------------

1. **REPL, not a one-shot argparse CLI.** The brief explicitly shows
   commands at a ``>`` prompt — i.e. an interactive shell. Re-loading
   the index for every query (a one-shot CLI's only option) would
   also feel sluggish during the live demo.

2. **Index resident in memory across commands.** The shell holds the
   index in an instance attribute, so ``build``/``load`` is paid once
   and every subsequent ``find``/``print`` is microseconds.

3. **Compute/format/loop separation.**

   * :class:`SearchEngineShell.execute` is a *pure* dispatcher that
     processes one command line — no ``input()`` calls. This makes
     command-level behaviour trivial to unit-test.
   * :class:`SearchEngineShell.run_repl` is a thin loop that reads
     stdin and feeds lines to ``execute``. It contains only the
     concerns specific to running an interactive session (prompt,
     EOF, Ctrl-C).

4. **Defensive guards before every search.** ``print`` and ``find``
   first check that an index is loaded; otherwise they nudge the user
   toward ``build`` or ``load`` instead of throwing an
   ``AttributeError`` on ``None``.

5. **Three exit paths, all silent.** ``exit``/``quit`` keywords,
   ``EOFError`` (Ctrl-D), and ``KeyboardInterrupt`` (Ctrl-C) all leave
   cleanly. The Ctrl-C handler in particular suppresses the
   ``Traceback (most recent call last):...`` Python would print by
   default — which looks unprofessional in a recorded demo.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Callable, Dict, Optional

from src.crawler import Crawler
from src.indexer import Index, build_index
from src.search import format_find, format_print
from src.storage import (
    DEFAULT_INDEX_PATH,
    IndexNotFoundError,
    load_index,
    save_index,
)


HELP_TEXT = """Available commands:
  build           Crawl the website, build the inverted index, and save it.
  load            Load the previously-saved index from disk.
  print <word>    Show the inverted index entry for <word>.
  find <terms>    Find pages containing ALL <terms> (AND query).
  help            Show this help message.
  exit / quit     Leave the shell.
"""

BANNER = (
    "COMP3011 Search Engine — quotes.toscrape.com\n"
    "Type 'help' for commands, 'exit' or Ctrl-D to quit."
)


class SearchEngineShell:
    """Interactive REPL holding one in-memory index between commands."""

    PROMPT = "> "

    def __init__(
        self,
        base_url: str = Crawler.DEFAULT_BASE_URL,
        delay: float = 6.0,
        index_path: Path = DEFAULT_INDEX_PATH,
    ) -> None:
        self.base_url = base_url
        self.delay = delay
        self.index_path = Path(index_path)
        self.index: Optional[Index] = None

        # Dispatch table — looked up by ``execute``. Built once per
        # instance so the dict keys document the public command set.
        self._commands: Dict[str, Callable[[str], None]] = {
            "build": self._cmd_build,
            "load": self._cmd_load,
            "print": self._cmd_print,
            "find": self._cmd_find,
            "help": self._cmd_help,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def execute(self, line: str) -> None:
        """Process a single command line and print any output.

        Empty lines are silently ignored. Unknown commands and missing
        arguments are reported to the user without raising.
        """
        line = line.strip()
        if not line:
            return
        cmd, _, arg = line.partition(" ")
        cmd = cmd.lower()
        handler = self._commands.get(cmd)
        if handler is None:
            print(f"Unknown command: {cmd!r}. Type 'help' for available commands.")
            return
        handler(arg.strip())

    def run_repl(self) -> int:
        """Read commands from stdin until EOF / exit / quit / Ctrl-C.

        Returns the shell exit code (always 0 for normal exits).
        """
        print(BANNER)
        while True:
            try:
                line = input(self.PROMPT)
            except EOFError:
                # Ctrl-D — newline so the next shell prompt looks clean.
                print()
                return 0
            except KeyboardInterrupt:
                # Ctrl-C — suppress the default traceback.
                print()
                return 0

            if line.strip().lower() in {"exit", "quit"}:
                return 0
            self.execute(line)

    # ------------------------------------------------------------------
    # Command handlers (private; tested via ``execute``)
    # ------------------------------------------------------------------
    def _cmd_build(self, arg: str) -> None:
        crawler = Crawler(base_url=self.base_url, delay=self.delay)
        print(f"Crawling {self.base_url} (this will take a moment)...")
        pages = crawler.crawl()
        if not pages:
            print("Build failed — no pages were fetched. Check your network.")
            return
        self.index = build_index(pages)
        save_index(self.index, self.index_path)
        size_kb = self.index_path.stat().st_size / 1024
        print(
            f"Built index: {self.index['num_docs']} docs, "
            f"{len(self.index['index'])} unique terms. "
            f"Saved to {self.index_path} ({size_kb:.1f} KB)."
        )

    def _cmd_load(self, arg: str) -> None:
        try:
            self.index = load_index(self.index_path)
        except IndexNotFoundError as exc:
            print(str(exc))
            return
        print(
            f"Loaded index: {self.index['num_docs']} docs, "
            f"{len(self.index['index'])} unique terms, from {self.index_path}."
        )

    def _cmd_print(self, arg: str) -> None:
        if not arg:
            print("Usage: print <word>")
            return
        if self.index is None:
            print("No index loaded. Run 'build' or 'load' first.")
            return
        print(format_print(arg, self.index))

    def _cmd_find(self, arg: str) -> None:
        if not arg:
            print("Usage: find <term> [<term> ...]")
            return
        if self.index is None:
            print("No index loaded. Run 'build' or 'load' first.")
            return
        print(format_find(arg, self.index))

    def _cmd_help(self, arg: str) -> None:
        print(HELP_TEXT, end="")


# ---------------------------------------------------------------------------
# Module entry point
# ---------------------------------------------------------------------------
def _parse_cli_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.main",
        description="COMP3011 search-engine interactive shell.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        default=Crawler.DEFAULT_BASE_URL,
        help="Root URL the crawler starts from.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=6.0,
        help="Politeness window between requests in seconds.",
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=DEFAULT_INDEX_PATH,
        help="Where the index file lives (read by 'load', written by 'build').",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_cli_args(argv)
    # Surface the crawler's INFO logs (e.g. "Crawl finished: 10 pages") so the
    # user gets visible feedback during the long ``build`` operation.
    logging.basicConfig(level=logging.INFO, format="    [%(levelname)s] %(message)s")
    shell = SearchEngineShell(
        base_url=args.base_url, delay=args.delay, index_path=args.index
    )
    return shell.run_repl()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())