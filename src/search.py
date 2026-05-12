"""
Search module
=============

Implements the two query commands the brief specifies:

* :func:`format_print` — backs the ``print <word>`` CLI command
* :func:`format_find`  — backs the ``find <terms...>`` CLI command

The pure data-producing functions (:func:`lookup`, :func:`find`) are
exposed alongside the formatting wrappers so tests can verify the
search logic without parsing strings.

Design decisions (defend these in the video)
--------------------------------------------

1. **AND semantics with ``set`` intersection.** A page must contain
   *every* query term to be a hit. We take the intersection of the
   URL keys of each term's posting list. Time complexity:
   ``O(min(|p_i|) + k·|result|)`` where ``k`` is the number of query
   terms — the standard Boolean-IR approach.

2. **Sum-of-tf ranking with URL tiebreak.** ``score`` is the total
   number of times the query terms appear in the page. This gives
   the user a meaningful "how relevant" signal beyond the unordered
   set returned by a strict Boolean query. Equal scores are broken
   by URL ascending so the output is deterministic and trivial to
   assert in tests. This score is also the natural baseline that
   :ref:`stage 7's TF-IDF extension <stage7>` upgrades — same code
   path, weighted differently.

3. **Query terms are deduplicated.** ``find love love`` is treated
   exactly like ``find love``; otherwise a typo would inflate the
   score without any genuine signal. ``dict.fromkeys`` preserves
   first-occurrence order so the "No pages contain..." error message
   still reads as the user typed it.

4. **Query tokens go through the same tokenizer as the index.** This
   is what makes ``find Good`` find ``good`` and ``find don't`` find
   pages containing ``don`` *and* ``t``. The tokenizer is the single
   source of truth for normalisation — there is no separate
   "query parser".
"""

from __future__ import annotations

from typing import List, NamedTuple, Optional

from src.indexer import Index, TermEntry
from src.tokenizer import tokenize


class SearchResult(NamedTuple):
    """One hit returned by :func:`find`."""

    url: str
    score: int  # total tf across all query terms in this page


# ---------------------------------------------------------------------------
# Pure search logic (no I/O, no formatting)
# ---------------------------------------------------------------------------
def lookup(word: str, index: Index) -> Optional[TermEntry]:
    """Return the inverted-index entry for ``word`` or ``None``.

    ``word`` is run through the tokenizer first, so ``"Good"`` and
    ``"good"`` resolve to the same entry. If ``word`` tokenises to
    multiple tokens, only the first one is looked up (the CLI's
    ``print`` command is defined as single-word).
    """
    tokens = tokenize(word)
    if not tokens:
        return None
    return index["index"].get(tokens[0])


def find(query: str, index: Index) -> List[SearchResult]:
    """Return pages containing **all** terms in ``query``, ranked.

    Parameters
    ----------
    query:
        Free-form query string. Will be tokenised the same way as the
        index was built.
    index:
        An :class:`~src.indexer.Index` produced by
        :func:`~src.indexer.build_index`.

    Returns
    -------
    list[SearchResult]
        Ordered by ``score`` descending, then ``url`` ascending.
        Empty when the query has no tokens or no page satisfies the
        AND-conjunction of all query terms.
    """
    # Deduplicate while preserving order (Py3.7+ dict insertion order).
    tokens = list(dict.fromkeys(tokenize(query)))
    if not tokens:
        return []

    # Look up each token's postings; if any term is absent from the
    # vocabulary the AND-intersection is empty, so we exit early.
    postings_lists = []
    for token in tokens:
        entry = index["index"].get(token)
        if entry is None:
            return []
        postings_lists.append(entry["postings"])

    # Intersect the URL key-sets across all terms.
    candidate_urls = set(postings_lists[0].keys())
    for postings in postings_lists[1:]:
        candidate_urls &= postings.keys()

    # Score each surviving URL by summing tf across query terms.
    results = [
        SearchResult(
            url=url,
            score=sum(postings[url]["tf"] for postings in postings_lists),
        )
        for url in candidate_urls
    ]

    # Sort: score desc, URL asc (deterministic, test-friendly).
    results.sort(key=lambda r: (-r.score, r.url))
    return results


# ---------------------------------------------------------------------------
# Display formatters used by the CLI
# ---------------------------------------------------------------------------
def format_print(word: str, index: Index) -> str:
    """Render the inverted-index entry for ``word`` for terminal output."""
    tokens = tokenize(word)
    if not tokens:
        return "No word given."

    token = tokens[0]
    entry = index["index"].get(token)
    if entry is None:
        return f"Term '{token}' not in index."

    lines = [f"Term '{token}' (df={entry['df']})"]
    # Iterate URLs in alphabetical order so the output is reproducible.
    for url in sorted(entry["postings"]):
        tf = entry["postings"][url]["tf"]
        lines.append(f"  {url}   tf={tf}")
    return "\n".join(lines)


def format_find(query: str, index: Index) -> str:
    """Run :func:`find` and render its results for terminal output."""
    tokens = list(dict.fromkeys(tokenize(query)))
    if not tokens:
        return "No query given."

    results = find(query, index)
    if not results:
        terms = ", ".join(f"'{t}'" for t in tokens)
        return f"No pages contain all of: {terms}"

    lines = [f"{len(results)} page(s) found:"]
    for r in results:
        lines.append(f"  {r.url}   (score={r.score})")
    return "\n".join(lines)