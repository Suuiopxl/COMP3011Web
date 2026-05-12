"""
Query demo script
=================

Runs the brief's example queries plus a handful of edge cases against
an existing on-disk index. Useful for:

* Verifying ``search.format_*`` still produces correct output after any
  change to the indexing pipeline.
* Rehearsing the video demonstration without typing commands by hand.

Requires that the index has been built at least once (e.g. via
``python scripts/smoke_test.py``). If the file is missing, the script
exits with a clear message pointing the user at the right command.

Usage
-----

From the project root::

    python scripts/demo_queries.py
    python scripts/demo_queries.py --index /custom/path/index.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.search import format_find, format_print  # noqa: E402
from src.storage import IndexNotFoundError, load_index  # noqa: E402


# Each tuple is (command_label, callable, arg) so the loop below stays flat.
BRIEF_EXAMPLES = [
    ("print nonsense",     format_print, "nonsense"),
    ("find indifference",  format_find,  "indifference"),
    ("find good friends",  format_find,  "good friends"),
]

EDGE_CASES = [
    ("find xyz123",        format_find,  "xyz123"),         # unknown single term
    ("find good xyz",      format_find,  "good xyz"),       # AND with unknown
    ("find (empty)",       format_find,  ""),               # empty query
    ("find !!!",           format_find,  "!!!"),            # pure punctuation
    ("find GOOD friends",  format_find,  "GOOD friends"),   # case insensitivity
    ("find good good",     format_find,  "good good"),      # duplicate terms
    ("print XYZ123",       format_print, "XYZ123"),         # unknown word
    ("print (empty)",      format_print, ""),               # empty word
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the brief's example queries against the saved index.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=PROJECT_ROOT / "data" / "index.json",
        help="Path to the saved index file.",
    )
    parser.add_argument(
        "--skip-edge-cases",
        action="store_true",
        help="Only run the brief's example queries.",
    )
    return parser.parse_args()


def _run_block(title: str, cases, idx) -> None:
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)
    for label, fn, arg in cases:
        print(f"\n> {label}")
        print(fn(arg, idx))


def main() -> int:
    args = parse_args()

    try:
        idx = load_index(args.index)
    except IndexNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print(
            "Hint: run 'python scripts/smoke_test.py' first to build the index.",
            file=sys.stderr,
        )
        return 1

    print(
        f"Loaded index: {idx['num_docs']} docs, "
        f"{len(idx['index'])} unique terms, "
        f"from {args.index}"
    )

    _run_block("Brief examples", BRIEF_EXAMPLES, idx)
    if not args.skip_edge_cases:
        _run_block("Edge cases", EDGE_CASES, idx)

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())