"""
Tokenizer module
================

Converts raw text (page content or user queries) into a normalised list of
tokens that can be used as keys in the inverted index.

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