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


# ---------------------------------------------------------------------------
# TF-IDF ranking (stage 7 extension)
# ---------------------------------------------------------------------------
import math


class TestTfidfRanking:
    @pytest.fixture
    def biased_idx(self):
        """A corpus designed so TF-IDF and TF rank DIFFERENTLY.

        Mapping (term, url) -> tf::

                  | u1 u2 u3 u4
            rare  |  1  0  0  0
            common|  3  1  1  1     (appears in every doc)
        """
        return {
            "index": {
                "rare": {
                    "df": 1,
                    "postings": {"u1": _posting(1)},
                },
                "common": {
                    "df": 4,
                    "postings": {
                        "u1": _posting(3),
                        "u2": _posting(1),
                        "u3": _posting(1),
                        "u4": _posting(1),
                    },
                },
            },
            "doc_lengths": {"u1": 10, "u2": 10, "u3": 10, "u4": 10},
            "num_docs": 4,
        }

    def test_unknown_rank_mode_raises(self, idx):
        with pytest.raises(ValueError, match="Unknown rank mode"):
            find("good", idx, rank="bm25")

    def test_default_rank_is_tf(self, idx):
        assert find("good", idx) == find("good", idx, rank="tf")

    def test_tfidf_returns_same_urls_as_tf(self, idx):
        # AND-intersection is independent of ranking — only ORDER may differ.
        tf_urls = {r.url for r in find("good friends", idx, rank="tf")}
        tfidf_urls = {r.url for r in find("good friends", idx, rank="tfidf")}
        assert tf_urls == tfidf_urls

    def test_tfidf_score_matches_hand_calculation(self, biased_idx):
        """Verify the exact formula on a single-term, single-doc case.

        For ``find rare`` on biased_idx:
            tf = 1, df = 1, N = 4
            tf_weight  = 1 + log(1)      = 1.0
            idf_weight = log(5/2) + 1    ≈ 1.9163
            score      = 1.0 * 1.9163    ≈ 1.9163
        """
        results = find("rare", biased_idx, rank="tfidf")
        assert len(results) == 1
        expected = (1 + math.log(1)) * (math.log(5 / 2) + 1)
        assert results[0].score == pytest.approx(expected)

    def test_tfidf_rare_term_has_higher_idf_weight(self, biased_idx):
        """A rarer term has a strictly larger IDF weight.

        With sklearn-smoothed IDF, ``df=4=N`` does NOT zero out the
        contribution (that's the whole point of the smoothing), but a
        rare term still gets a higher per-occurrence weight.

        At tf=1 for both terms, the scores are pure IDF weights:
            rare:   1 * (log(5/2) + 1) ≈ 1.9163
            common: 1 * (log(5/5) + 1) = 1.0
        """
        # Score on a hypothetical doc where each term has tf=1.
        # We isolate the IDF effect by comparing terms at equal tf.
        single_doc_idx = {
            "index": {
                "rare":   {"df": 1, "postings": {"u": _posting(1)}},
                "common": {"df": 4, "postings": {"u": _posting(1)}},
            },
            "doc_lengths": {"u": 10},
            "num_docs": 4,
        }
        rare_score = find("rare", single_doc_idx, rank="tfidf")[0].score
        common_score = find("common", single_doc_idx, rank="tfidf")[0].score
        assert rare_score > common_score

    def test_tfidf_log_tf_is_sublinear(self, biased_idx):
        """Doubling raw tf must not double the TF-IDF score."""
        # u1 has tf=3 for 'common'; we'll construct another doc with tf=6.
        idx = {
            "index": {
                "x": {
                    "df": 2,
                    "postings": {"a": _posting(3), "b": _posting(6)},
                }
            },
            "doc_lengths": {"a": 10, "b": 10},
            "num_docs": 2,
        }
        results = {r.url: r.score for r in find("x", idx, rank="tfidf")}
        # Linear scaling would give b/a = 2.0; log scaling gives < 2.0.
        ratio = results["b"] / results["a"]
        assert 1.0 < ratio < 2.0

    def test_tfidf_term_appearing_everywhere_still_contributes(self, biased_idx):
        """Smoothing avoids the naive-IDF zeroing-out when df == N."""
        # 'common' appears in all 4 docs — naive log(N/df) would be 0.
        results = find("common", biased_idx, rank="tfidf")
        for r in results:
            assert r.score > 0


class TestTfidfFormatting:
    def test_default_format_uses_integer_scores(self, idx):
        """Brief example output must remain byte-identical to baseline."""
        out = format_find("good friends", idx)
        # Integer scores have no decimal point.
        assert "score=3)" in out and "score=2)" in out
        assert ".0" not in out  # no float-looking values

    def test_tfidf_format_uses_four_decimals(self, idx):
        out = format_find("good friends", idx, rank="tfidf")
        # Every score line ends with a 4-decimal float.
        import re

        for line in out.splitlines():
            m = re.search(r"score=([0-9]+\.[0-9]+)\)", line)
            if m:
                # Confirm exactly 4 digits after the decimal point.
                assert len(m.group(1).split(".")[1]) == 4

    def test_tfidf_empty_query_message_unchanged(self, idx):
        assert format_find("", idx, rank="tfidf") == "No query given."

    def test_tfidf_no_match_message_unchanged(self, idx):
        out = format_find("xyz", idx, rank="tfidf")
        assert out == "No pages contain all of: 'xyz'"