"""
Tokenizer module
================

Converts raw text (page content or user queries) into a normalised list of
tokens that can be used as keys in the inverted index.

Design decisions (justify these in the video):

1. **Case-insensitive**: All text is lower-cased before tokenisation so that
   "Good" and "good" map to the same token, as required by the brief.

2. **Split on any non-alphanumeric character**: We use the regex ``[a-z0-9]+``
   to extract maximal runs of letters and digits. This means:

   * Punctuation (``.``, ``,``, ``;`` …) acts as a separator.
   * Apostrophes are treated as separators too, so ``"don't"`` becomes
     ``["don", "t"]``. The same rule is applied at query time, so a search
     for ``"don't"`` will still match documents that contain the contraction.
   * Hyphens split words: ``"well-known"`` → ``["well", "known"]``.
   * Numbers are kept as tokens: ``"1999"`` is a valid search term.

3. **No stop-word removal and no stemming**: The brief asks us to index
   *all* word occurrences, so we deliberately keep words such as "the",
   "a", "is" and we do not collapse "running" to "run". Keeping the
   pipeline simple also avoids introducing extra dependencies (e.g. NLTK).
"""

from __future__ import annotations

import re
from typing import List

# Pre-compiled once at import time for efficiency: matches one-or-more
# ASCII letters or digits. Applied to already-lower-cased text, so we only
# need the lower-case range.
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> List[str]:
    """Split ``text`` into a list of normalised tokens.

    The function is intentionally simple and deterministic so that the
    exact same rules apply both when building the inverted index and when
    parsing a user query at search time.

    Parameters
    ----------
    text:
        Arbitrary input string. ``None`` is *not* accepted — callers
        should pass an empty string instead.

    Returns
    -------
    list[str]
        Lower-cased tokens in the order they appear in ``text``. The
        positional order is preserved so that the indexer can record
        word positions.

    Examples
    --------
    >>> tokenize("Hello, World!")
    ['hello', 'world']
    >>> tokenize("Don't be silly")
    ['don', 't', 'be', 'silly']
    >>> tokenize("Born in 1999")
    ['born', 'in', '1999']
    >>> tokenize("")
    []
    """
    if not isinstance(text, str):
        raise TypeError(f"tokenize() expected str, got {type(text).__name__}")
    return _TOKEN_RE.findall(text.lower())