"""
Indexer module
==============

Builds the inverted index that powers the search engine.

Index format (defend this in the video)
---------------------------------------

A single in-memory ``dict`` with three top-level keys::

    {
        "index": {
            "good": {
                "df": 3,
                "postings": {
                    "https://quotes.toscrape.com/page/1/": {
                        "tf": 2,
                        "positions": [5, 42]
                    },
                    "https://quotes.toscrape.com/page/4/": {
                        "tf": 1,
                        "positions": [17]
                    }
                }
            }
        },
        "doc_lengths": {
            "https://quotes.toscrape.com/page/1/": 245
        },
        "num_docs": 10
    }

"""

from __future__ import annotations

from typing import Dict, Iterable, List, TypedDict

from src.crawler import CrawledPage
from src.tokenizer import tokenize


# ---------------------------------------------------------------------------
# Typed structure (purely documentation – no runtime cost)
# ---------------------------------------------------------------------------
class Posting(TypedDict):
    """One document's record for a single term."""

    tf: int
    positions: List[int]


class TermEntry(TypedDict):
    """All postings for a single term, plus its document frequency."""

    df: int
    postings: Dict[str, Posting]


class Index(TypedDict):
    """The complete inverted index returned by :func:`build_index`."""

    index: Dict[str, TermEntry]
    doc_lengths: Dict[str, int]
    num_docs: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def build_index(pages: Iterable[CrawledPage]) -> Index:
    """Build an inverted index from an iterable of crawled pages.

    Parameters
    ----------
    pages:
        Anything yielding :class:`CrawledPage` (URL + visible text).
        The caller is responsible for deduplicating URLs; the
        :class:`~src.crawler.Crawler` already does this.

    Returns
    -------
    Index
        See module docstring for the exact shape. The dict is plain
        Python — ready to JSON-dump without further conversion.

    Notes
    -----
    Complexity: O(T) time and O(V + T) memory, where T is the total
    token count across all pages and V is the vocabulary size.
    """
    index: Dict[str, TermEntry] = {}
    doc_lengths: Dict[str, int] = {}
    num_docs = 0

    for page in pages:
        tokens = tokenize(page.text)
        doc_lengths[page.url] = len(tokens)
        num_docs += 1

        # First aggregate positions per term within this document
        # so we touch each (term, doc) pair only once in the global index.
        per_term_positions: Dict[str, List[int]] = {}
        for pos, token in enumerate(tokens):
            per_term_positions.setdefault(token, []).append(pos)

        # Merge this document's contributions into the global index.
        for token, positions in per_term_positions.items():
            entry = index.get(token)
            if entry is None:
                entry = {"df": 0, "postings": {}}
                index[token] = entry
            entry["postings"][page.url] = {
                "tf": len(positions),
                "positions": positions,
            }
            entry["df"] += 1

    return {"index": index, "doc_lengths": doc_lengths, "num_docs": num_docs}


# ---------------------------------------------------------------------------
# Manual smoke-test: ``python -m src.indexer``
# ---------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import logging

    from src.crawler import Crawler

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    pages = Crawler().crawl()
    idx = build_index(pages)
    print(
        f"\nIndexed {idx['num_docs']} docs, "
        f"{len(idx['index'])} unique terms, "
        f"{sum(idx['doc_lengths'].values())} total tokens."
    )
    # Print a few example entries
    for sample in ["good", "friends", "einstein", "indifference"]:
        entry = idx["index"].get(sample)
        if entry is None:
            print(f"\n{sample!r}: not in index")
        else:
            print(f"\n{sample!r}: df={entry['df']}")
            for url, posting in entry["postings"].items():
                print(
                    f"  {url}  tf={posting['tf']}  "
                    f"positions={posting['positions'][:5]}..."
                )