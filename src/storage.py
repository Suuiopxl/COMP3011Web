"""
Storage module
==============

Persists the inverted index to disk and loads it back.

"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

from src.indexer import Index

DEFAULT_INDEX_PATH = Path("data/index.json")

# Keys that any valid serialised index must contain at the top level.
_REQUIRED_KEYS = frozenset({"index", "doc_lengths", "num_docs"})


class IndexNotFoundError(FileNotFoundError):
    """Raised by :func:`load_index` when the index file does not exist.

    Subclasses :class:`FileNotFoundError` so legacy ``except
    FileNotFoundError`` blocks still catch it, while letting code that
    cares about the semantic distinction (e.g. the CLI's ``load``
    command) catch it specifically and suggest running ``build`` first.
    """


def save_index(index: Index, path: Path = DEFAULT_INDEX_PATH) -> None:
    """Serialise ``index`` to ``path`` as JSON.

    Parent directories are created on demand. The write is atomic:
    we write to ``<path>.tmp`` and then rename, so a crash never
    leaves a partially-written file at ``path``.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    # ``ensure_ascii=False`` lets non-ASCII characters (curly quotes
    # in the corpus, etc.) survive without ``\u`` escaping, making
    # the on-disk file easier to inspect.
    tmp_path.write_text(
        json.dumps(index, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp_path, path)  # atomic on POSIX and Windows


def load_index(path: Path = DEFAULT_INDEX_PATH) -> Index:
    """Load and validate an index previously written by :func:`save_index`.

    Raises
    ------
    IndexNotFoundError
        If ``path`` does not exist. Hint to the CLI that the user
        should run ``build`` first.
    ValueError
        If the file exists but does not look like a valid index
        (wrong top-level shape).
    json.JSONDecodeError
        If the file is not valid JSON (e.g. truncated by a crash
        before atomic writes were in place).
    """
    path = Path(path)
    if not path.exists():
        raise IndexNotFoundError(
            f"No index file at {path!s}. Run the 'build' command first."
        )
    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise ValueError(
            f"Expected a JSON object at {path!s}, got {type(data).__name__}."
        )
    missing = _REQUIRED_KEYS - data.keys()
    if missing:
        raise ValueError(
            f"File at {path!s} is not a valid index — missing keys: "
            f"{sorted(missing)}"
        )
    return cast(Index, data)