"""
End-to-end smoke test
=====================

Exercises the full pipeline so you can verify everything still works
after any code change without typing a multi-line one-liner into the
terminal::

    crawl  →  build_index  →  save_index  →  load_index  →  diff check

Usage
-----

From the project root::

    python scripts/smoke_test.py                    # full run, default 6s delay
    python scripts/smoke_test.py --delay 2          # faster (still polite)
    python scripts/smoke_test.py --no-save          # in-memory only, no file
    python scripts/smoke_test.py --output /tmp/i.json  # custom output path

Exit codes: ``0`` success, ``1`` if any step failed (round-trip mismatch,
network error, etc.). The non-zero exit makes this safe to use in CI
later.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Make ``src`` importable when this script is launched directly (i.e.
# ``python scripts/smoke_test.py``) rather than as a module.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.crawler import Crawler  # noqa: E402 -- sys.path tweak above
from src.indexer import build_index  # noqa: E402
from src.storage import load_index, save_index  # noqa: E402


# Sample words drawn from the brief's own examples; we look them up
# after building the index as a sanity check.
SAMPLE_WORDS = ("nonsense", "indifference", "good", "friends")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="End-to-end smoke test: crawl, index, save, load, verify.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=6.0,
        help="Politeness window between requests in seconds.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "index.json",
        help="Where to write the compiled index.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Skip save/load round-trip (in-memory pipeline only).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Surface the crawler's own INFO logs so the user sees the final
    # "Crawl finished" message in addition to the headings below.
    logging.basicConfig(level=logging.INFO, format="    [%(levelname)s] %(message)s")

    print("=" * 60)
    print(" COMP3011 search engine — end-to-end smoke test")
    print("=" * 60)

    # ---- 1. Crawl ---------------------------------------------------------
    print(f"\n[1/4] Crawling quotes.toscrape.com (delay={args.delay}s)...")
    t0 = time.monotonic()
    pages = Crawler(delay=args.delay).crawl()
    t1 = time.monotonic()
    if not pages:
        print(f"  ✗ FAILED — no pages crawled (network issue?)")
        return 1
    print(f"  ✓ Crawled {len(pages)} pages in {t1 - t0:.1f}s")

    # ---- 2. Build index ---------------------------------------------------
    print("\n[2/4] Building inverted index...")
    t2 = time.monotonic()
    idx = build_index(pages)
    t3 = time.monotonic()
    print(
        f"  ✓ Built index in {(t3 - t2) * 1000:.1f} ms — "
        f"{idx['num_docs']} docs, "
        f"{len(idx['index'])} unique terms, "
        f"{sum(idx['doc_lengths'].values())} total tokens"
    )

    # ---- 3. Save + round-trip --------------------------------------------
    if not args.no_save:
        print(f"\n[3/4] Saving + loading round-trip ({args.output})...")
        save_index(idx, args.output)
        size_kb = args.output.stat().st_size / 1024
        loaded = load_index(args.output)
        if loaded != idx:
            print("  ✗ FAILED — loaded index differs from built index")
            return 1
        print(f"  ✓ Round-trip OK ({size_kb:.1f} KB on disk)")
    else:
        print("\n[3/4] Skipped (--no-save).")

    # ---- 4. Sanity check on brief example words --------------------------
    print("\n[4/4] Sanity-checking the brief's example words...")
    for word in SAMPLE_WORDS:
        entry = idx["index"].get(word)
        if entry is None:
            print(f"  · {word!r:>14}: not in index")
        else:
            print(
                f"  · {word!r:>14}: df={entry['df']:>2}, "
                f"appears in {len(entry['postings']):>2} page(s)"
            )

    print("\nAll steps passed ✓\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())