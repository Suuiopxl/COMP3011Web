"""
Unit tests for ``src.tokenizer``.

Testing strategy
----------------
We aim for high branch coverage of the (very small) tokenizer module
because every other component of the search engine depends on it. The
tests are grouped by *intent* so that the test report itself doubles as
a specification of the tokenizer's behaviour.
"""

from __future__ import annotations

import pytest

from src.tokenizer import tokenize


class TestBasicBehaviour:
    """Happy-path cases: ordinary English sentences."""

    def test_simple_sentence(self):
        assert tokenize("Hello world") == ["hello", "world"]

    def test_preserves_token_order(self):
        # Order matters because the indexer records word positions.
        assert tokenize("alpha beta gamma") == ["alpha", "beta", "gamma"]

    def test_collapses_runs_of_whitespace(self):
        assert tokenize("hello   world\t\nfoo") == ["hello", "world", "foo"]


class TestCaseInsensitivity:
    """The brief mandates a case-insensitive search."""

    def test_uppercase_lowercased(self):
        assert tokenize("GOOD") == ["good"]

    def test_mixed_case_lowercased(self):
        assert tokenize("Good GOOD good gOOd") == ["good", "good", "good", "good"]

    def test_good_and_Good_produce_same_token(self):
        assert tokenize("Good") == tokenize("good") == tokenize("GOOD")


class TestPunctuation:
    """Punctuation should act as a separator and never appear in the output."""

    def test_trailing_punctuation_stripped(self):
        assert tokenize("Hello, world!") == ["hello", "world"]

    def test_apostrophes_split_contractions(self):
        # Documented design decision: "don't" splits into "don" + "t".
        assert tokenize("don't") == ["don", "t"]

    def test_hyphenated_words_split(self):
        assert tokenize("well-known author") == ["well", "known", "author"]

    def test_only_punctuation_returns_empty(self):
        assert tokenize("!!!???...") == []

    def test_curly_quotes_split(self):
        # quotes.toscrape.com uses Unicode curly apostrophes (U+2019).
        assert tokenize("don\u2019t") == ["don", "t"]


class TestNumbers:
    """Numeric tokens are preserved (documented design decision)."""

    def test_pure_number_kept(self):
        assert tokenize("1999") == ["1999"]

    def test_number_inside_sentence(self):
        assert tokenize("Born in 1854 and died in 1900.") == [
            "born",
            "in",
            "1854",
            "and",
            "died",
            "in",
            "1900",
        ]

    def test_alphanumeric_kept_together(self):
        # An alphanumeric run with no separator stays one token.
        assert tokenize("room101") == ["room101"]


class TestEdgeCases:
    """Boundary conditions the marking rubric cares about."""

    def test_empty_string(self):
        assert tokenize("") == []

    def test_whitespace_only(self):
        assert tokenize("   \t\n  ") == []

    def test_single_character(self):
        assert tokenize("a") == ["a"]

    def test_unicode_letters_dropped(self):
        # We deliberately only keep ASCII letters/digits — anything else
        # acts as a separator. Document this in the video.
        assert tokenize("café résumé") == ["caf", "r", "sum"]


class TestQueryIndexConsistency:
    """The indexer and the search command MUST tokenize identically."""

    @pytest.mark.parametrize(
        "indexed_text, query",
        [
            ("Good friends are important.", "good friends"),
            ("Don't be afraid.", "don't"),
            ("She was born in 1854.", "1854"),
            ("Well-known author", "well known"),
        ],
    )
    def test_query_tokens_subset_of_indexed_tokens(self, indexed_text, query):
        indexed_tokens = set(tokenize(indexed_text))
        query_tokens = set(tokenize(query))
        assert query_tokens.issubset(indexed_tokens), (
            f"Query tokens {query_tokens} not found in indexed tokens "
            f"{indexed_tokens} — index/query tokenizers are inconsistent."
        )


class TestTypeSafety:
    """Defensive programming: reject non-string input early."""

    @pytest.mark.parametrize("bad_input", [None, 123, ["a", "b"], 3.14])
    def test_non_string_raises_type_error(self, bad_input):
        with pytest.raises(TypeError):
            tokenize(bad_input)  # type: ignore[arg-type]