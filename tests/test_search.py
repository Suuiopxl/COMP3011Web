"""
Unit tests for ``src.search``.

We construct hand-crafted indexes inline so every expected ``score``
can be predicted by simple arithmetic.
"""

from __future__ import annotations

import pytest

from src.search import (
    SearchResult,
    find,
    format_find,
    format_print,
    lookup,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _posting(tf: int) -> dict:
    """A minimal posting (positions list omitted/empty — search doesn't use it)."""
    return {"tf": tf, "positions": list(range(tf))}


@pytest.fixture
def idx():
    """A small but expressive index used across most tests.

    Mapping (term, url) -> tf::

                | u1  u2  u3
        good    |  5   1   2
        friends |  0   1   1
        unique  |  1   0   0
    """
    return {
        "index": {
            "good": {
                "df": 3,
                "postings": {
                    "u1": _posting(5),
                    "u2": _posting(1),
                    "u3": _posting(2),
                },
            },
            "friends": {
                "df": 2,
                "postings": {
                    "u2": _posting(1),
                    "u3": _posting(1),
                },
            },
            "unique": {
                "df": 1,
                "postings": {"u1": _posting(1)},
            },
        },
        "doc_lengths": {"u1": 10, "u2": 10, "u3": 10},
        "num_docs": 3,
    }


# ---------------------------------------------------------------------------
# Single-word find (basic AND with one term)
# ---------------------------------------------------------------------------
class TestSingleWordFind:
    def test_returns_all_pages_for_present_term(self, idx):
        results = find("good", idx)
        assert {r.url for r in results} == {"u1", "u2", "u3"}

    def test_score_equals_tf_for_single_term(self, idx):
        results = find("good", idx)
        scores = {r.url: r.score for r in results}
        assert scores == {"u1": 5, "u2": 1, "u3": 2}

    def test_results_sorted_by_score_descending(self, idx):
        scores = [r.score for r in find("good", idx)]
        assert scores == sorted(scores, reverse=True)
        assert scores == [5, 2, 1]

    def test_returns_empty_for_unknown_term(self, idx):
        assert find("xyz123", idx) == []


# ---------------------------------------------------------------------------
# Multi-word AND
# ---------------------------------------------------------------------------
class TestMultiWordAnd:
    def test_returns_intersection_only(self, idx):
        # `good` ∩ `friends` = {u2, u3}; u1 has no `friends`.
        urls = {r.url for r in find("good friends", idx)}
        assert urls == {"u2", "u3"}

    def test_score_sums_tf_across_terms(self, idx):
        results = find("good friends", idx)
        scores = {r.url: r.score for r in results}
        # u2: good=1 + friends=1 = 2
        # u3: good=2 + friends=1 = 3
        assert scores == {"u2": 2, "u3": 3}

    def test_results_sorted_by_combined_score(self, idx):
        results = find("good friends", idx)
        assert [r.url for r in results] == ["u3", "u2"]

    def test_empty_intersection_returns_no_results(self, idx):
        # `unique` only on u1; `friends` only on u2,u3. Intersection empty.
        assert find("unique friends", idx) == []

    def test_one_unknown_term_kills_whole_query(self, idx):
        assert find("good xyz", idx) == []


# ---------------------------------------------------------------------------
# Tiebreaking & determinism
# ---------------------------------------------------------------------------
class TestSorting:
    def test_equal_scores_broken_by_url_ascending(self):
        index = {
            "index": {
                "x": {
                    "df": 3,
                    "postings": {
                        "https://example.com/c": _posting(1),
                        "https://example.com/a": _posting(1),
                        "https://example.com/b": _posting(1),
                    },
                }
            },
            "doc_lengths": {},
            "num_docs": 3,
        }
        urls = [r.url for r in find("x", index)]
        assert urls == [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ]


# ---------------------------------------------------------------------------
# Tokenizer integration
# ---------------------------------------------------------------------------
class TestQueryNormalisation:
    def test_query_is_case_insensitive(self, idx):
        lower = find("good", idx)
        upper = find("GOOD", idx)
        mixed = find("GooD", idx)
        assert lower == upper == mixed

    def test_punctuation_in_query_split_by_tokenizer(self, idx):
        # "good," tokenises to ["good"], same as "good".
        assert find("good,", idx) == find("good", idx)

    def test_duplicate_query_terms_collapsed(self, idx):
        # `find good good` must NOT double the score of `find good`.
        single = find("good", idx)
        double = find("good good", idx)
        assert single == double

    def test_empty_query_returns_empty(self, idx):
        assert find("", idx) == []

    def test_whitespace_only_query_returns_empty(self, idx):
        assert find("   \t\n  ", idx) == []

    def test_pure_punctuation_query_returns_empty(self, idx):
        # Tokenizer drops "!!!"" → empty token list → empty results.
        assert find("!!! ???", idx) == []


# ---------------------------------------------------------------------------
# lookup() — backs the print command
# ---------------------------------------------------------------------------
class TestLookup:
    def test_returns_entry_for_known_word(self, idx):
        entry = lookup("good", idx)
        assert entry is not None
        assert entry["df"] == 3

    def test_returns_none_for_unknown_word(self, idx):
        assert lookup("xyz", idx) is None

    def test_returns_none_for_empty_word(self, idx):
        assert lookup("", idx) is None

    def test_lookup_is_case_insensitive(self, idx):
        assert lookup("GOOD", idx) == lookup("good", idx)


# ---------------------------------------------------------------------------
# Output formatting: print
# ---------------------------------------------------------------------------
class TestFormatPrint:
    def test_known_word_output_includes_df_and_postings(self, idx):
        out = format_print("good", idx)
        assert "good" in out
        assert "df=3" in out
        assert "tf=5" in out  # u1
        assert "tf=1" in out  # u2
        assert "tf=2" in out  # u3
        assert "u1" in out and "u2" in out and "u3" in out

    def test_known_word_pages_sorted_alphabetically(self, idx):
        out = format_print("good", idx)
        # u1 should appear before u2, which should appear before u3.
        assert out.index("u1") < out.index("u2") < out.index("u3")

    def test_unknown_word_message(self, idx):
        out = format_print("xyz123", idx)
        assert out == "Term 'xyz123' not in index."

    def test_empty_word_message(self, idx):
        assert format_print("", idx) == "No word given."

    def test_case_insensitive_input(self, idx):
        # "Good" should produce the same lines as "good".
        assert format_print("Good", idx) == format_print("good", idx)


# ---------------------------------------------------------------------------
# Output formatting: find
# ---------------------------------------------------------------------------
class TestFormatFind:
    def test_with_results_includes_count_and_urls(self, idx):
        out = format_find("good friends", idx)
        assert "2 page(s) found:" in out
        assert "u3" in out and "u2" in out
        assert "score=3" in out and "score=2" in out

    def test_results_ordered_in_output(self, idx):
        out = format_find("good friends", idx)
        # u3 (score=3) appears before u2 (score=2) in the rendered output.
        assert out.index("u3") < out.index("u2")

    def test_no_results_message_with_single_term(self, idx):
        out = format_find("xyz", idx)
        assert out == "No pages contain all of: 'xyz'"

    def test_no_results_message_lists_all_terms(self, idx):
        out = format_find("good xyz abc", idx)
        # Lists every tokenised term, in input order.
        assert "'good'" in out and "'xyz'" in out and "'abc'" in out
        assert out.index("'good'") < out.index("'xyz'") < out.index("'abc'")

    def test_no_results_when_intersection_empty(self, idx):
        out = format_find("unique friends", idx)
        assert "No pages contain all of:" in out
        assert "'unique'" in out and "'friends'" in out

    def test_empty_query_message(self, idx):
        assert format_find("", idx) == "No query given."

    def test_whitespace_only_query_message(self, idx):
        assert format_find("   ", idx) == "No query given."


# ---------------------------------------------------------------------------
# Result type contract
# ---------------------------------------------------------------------------
class TestSearchResultType:
    def test_returns_named_tuples(self, idx):
        r = find("good", idx)[0]
        assert isinstance(r, SearchResult)
        # Tuple-style and named-attribute access both work.
        assert r.url == r[0]
        assert r.score == r[1]