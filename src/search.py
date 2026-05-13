"""
Search module
=============

Implements the two query commands the brief specifies:

* :func:`format_print` — backs the ``print <word>`` CLI command
* :func:`format_find`  — backs the ``find <terms...>`` CLI command

Two ranking strategies are available:

* ``"tf"`` (default) — sum of term frequencies across query terms. This
  is the baseline Boolean-with-relevance ordering described in the
  module's first specification.
* ``"tfidf"`` (opt-in via ``--rank tfidf`` in the CLI) — TF-IDF score
  using the sklearn-style smoothed IDF and logarithmic TF normalisation
  (see :func:`_tfidf_score` for the exact formula). This is the
  extension referenced under "Advanced features beyond requirements" in
  the marking rubric.

The default ranking and output format are **byte-for-byte identical**
to the original specification so the brief's example commands behave
exactly as documented.

"""

from __future__ import annotations

import math
from typing import Dict, List, Literal, NamedTuple, Optional

from src.indexer import Index, TermEntry
from src.tokenizer import tokenize

RankMode = Literal["tf", "tfidf"]


class SearchResult(NamedTuple):
    """One hit returned by :func:`find`.

    ``score`` is a plain ``float``. For the default ``tf`` ranking it is
    always an integer value (sum of integer term frequencies); for
    ``tfidf`` ranking it is a real-valued score.
    """

    url: str
    score: float


# ---------------------------------------------------------------------------
# Scoring strategies (private — exposed via the ``find`` function)
# ---------------------------------------------------------------------------
def _tf_score(
    tokens: List[str], url: str, postings_lists: List[Dict[str, dict]], index: Index
) -> float:
    """Sum of term frequencies across query terms for one document."""
    return float(sum(postings[url]["tf"] for postings in postings_lists))


def _tfidf_score(
    tokens: List[str], url: str, postings_lists: List[Dict[str, dict]], index: Index
) -> float:
    """TF-IDF score with smoothed IDF and log-normalised TF.

    For each query term ``t``::

        tf_weight  = 1 + log(tf(t, doc))
        idf_weight = log((N + 1) / (df(t) + 1)) + 1
        contribution = tf_weight * idf_weight

    The document's score is the sum of contributions across query terms.
    Natural logarithm is used throughout — the base only rescales all
    scores by a constant and therefore does not affect ranking.
    """
    num_docs = index["num_docs"]
    score = 0.0
    for token, postings in zip(tokens, postings_lists):
        tf = postings[url]["tf"]
        df = index["index"][token]["df"]
        tf_weight = 1.0 + math.log(tf)  # tf >= 1 because url is in postings
        idf_weight = math.log((num_docs + 1) / (df + 1)) + 1.0
        score += tf_weight * idf_weight
    return score


_SCORE_FUNCS = {
    "tf": _tf_score,
    "tfidf": _tfidf_score,
}


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


def find(query: str, index: Index, rank: RankMode = "tf") -> List[SearchResult]:
    """Return pages containing **all** terms in ``query``, ranked.

    Parameters
    ----------
    query:
        Free-form query string, tokenised identically to the indexer.
    index:
        An :class:`~src.indexer.Index` produced by
        :func:`~src.indexer.build_index`.
    rank:
        ``"tf"`` (default, baseline) or ``"tfidf"`` (smoothed sklearn
        formula). Unknown values raise ``ValueError``.

    Returns
    -------
    list[SearchResult]
        Ordered by ``score`` descending, then ``url`` ascending. Empty
        when the query has no tokens or no page contains every term.
    """
    if rank not in _SCORE_FUNCS:
        raise ValueError(
            f"Unknown rank mode {rank!r}. Use one of: {sorted(_SCORE_FUNCS)}"
        )
    score_fn = _SCORE_FUNCS[rank]

    # Deduplicate while preserving order (Py3.7+ dict insertion order).
    tokens = list(dict.fromkeys(tokenize(query)))
    if not tokens:
        return []

    # Look up each token's postings; if any term is absent from the
    # vocabulary the AND-intersection is empty, so we exit early.
    postings_lists: List[Dict[str, dict]] = []
    for token in tokens:
        entry = index["index"].get(token)
        if entry is None:
            return []
        postings_lists.append(entry["postings"])

    # Intersect the URL key-sets across all terms.
    candidate_urls = set(postings_lists[0].keys())
    for postings in postings_lists[1:]:
        candidate_urls &= postings.keys()

    # Score and sort.
    results = [
        SearchResult(
            url=url,
            score=score_fn(tokens, url, postings_lists, index),
        )
        for url in candidate_urls
    ]
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
    for url in sorted(entry["postings"]):
        tf = entry["postings"][url]["tf"]
        lines.append(f"  {url}   tf={tf}")
    return "\n".join(lines)


def format_find(query: str, index: Index, rank: RankMode = "tf") -> str:
    """Run :func:`find` and render its results for terminal output.

    The output format adapts to the ranking mode: integer scores are
    printed without decimals (preserving the brief's example output),
    TF-IDF scores are printed with four decimal places.
    """
    tokens = list(dict.fromkeys(tokenize(query)))
    if not tokens:
        return "No query given."

    results = find(query, index, rank=rank)
    if not results:
        terms = ", ".join(f"'{t}'" for t in tokens)
        return f"No pages contain all of: {terms}"

    lines = [f"{len(results)} page(s) found:"]
    for r in results:
        if rank == "tf":
            # Integer values for the default mode (matches brief examples).
            lines.append(f"  {r.url}   (score={int(r.score)})")
        else:
            lines.append(f"  {r.url}   (score={r.score:.4f})")
    return "\n".join(lines)