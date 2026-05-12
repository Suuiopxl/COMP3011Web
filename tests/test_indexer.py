"""
Unit tests for ``src.indexer``.

Testing strategy
----------------
We feed ``build_index`` synthetic ``CrawledPage`` objects with carefully
designed text so we can predict every ``tf``, ``df``, and position
exactly. No real crawl is performed.
"""

from __future__ import annotations

import pytest

from src.crawler import CrawledPage
from src.indexer import build_index


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def page(url: str, text: str) -> CrawledPage:
    """Concise factory for one CrawledPage."""
    return CrawledPage(url=url, text=text)


# ---------------------------------------------------------------------------
# Shape / top-level contract
# ---------------------------------------------------------------------------
class TestIndexShape:
    def test_empty_input_returns_empty_structure(self):
        idx = build_index([])
        assert idx == {"index": {}, "doc_lengths": {}, "num_docs": 0}

    def test_returned_dict_has_three_top_level_keys(self):
        idx = build_index([page("u1", "hello")])
        assert set(idx.keys()) == {"index", "doc_lengths", "num_docs"}

    def test_num_docs_matches_input_size(self):
        pages = [page(f"u{i}", "word") for i in range(5)]
        assert build_index(pages)["num_docs"] == 5


# ---------------------------------------------------------------------------
# Term frequency (tf)
# ---------------------------------------------------------------------------
class TestTermFrequency:
    def test_single_occurrence_has_tf_one(self):
        idx = build_index([page("u1", "hello world")])
        assert idx["index"]["hello"]["postings"]["u1"]["tf"] == 1

    def test_repeated_word_tf_matches_count(self):
        idx = build_index([page("u1", "good good good evening")])
        assert idx["index"]["good"]["postings"]["u1"]["tf"] == 3

    def test_tf_is_per_document_not_global(self):
        idx = build_index([page("u1", "the the"), page("u2", "the")])
        assert idx["index"]["the"]["postings"]["u1"]["tf"] == 2
        assert idx["index"]["the"]["postings"]["u2"]["tf"] == 1


# ---------------------------------------------------------------------------
# Document frequency (df)
# ---------------------------------------------------------------------------
class TestDocumentFrequency:
    def test_word_in_one_doc_has_df_one(self):
        idx = build_index([page("u1", "unique"), page("u2", "other")])
        assert idx["index"]["unique"]["df"] == 1

    def test_word_in_all_docs_has_df_equal_num_docs(self):
        idx = build_index(
            [page("u1", "common"), page("u2", "common"), page("u3", "common")]
        )
        assert idx["index"]["common"]["df"] == 3

    def test_repeated_in_same_doc_does_not_inflate_df(self):
        """``df`` counts documents, not occurrences."""
        idx = build_index([page("u1", "word word word")])
        assert idx["index"]["word"]["df"] == 1

    def test_df_increases_only_with_new_documents(self):
        idx = build_index(
            [
                page("u1", "alpha beta"),
                page("u2", "alpha"),       # alpha in doc 2 -> df 2
                page("u3", "gamma delta"),  # alpha NOT here -> df stays 2
            ]
        )
        assert idx["index"]["alpha"]["df"] == 2
        assert idx["index"]["beta"]["df"] == 1


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------
class TestPositions:
    def test_positions_are_zero_indexed_in_token_stream(self):
        idx = build_index([page("u1", "a b c")])
        assert idx["index"]["a"]["postings"]["u1"]["positions"] == [0]
        assert idx["index"]["b"]["postings"]["u1"]["positions"] == [1]
        assert idx["index"]["c"]["postings"]["u1"]["positions"] == [2]

    def test_repeated_word_records_all_positions(self):
        idx = build_index([page("u1", "x y x y x")])
        assert idx["index"]["x"]["postings"]["u1"]["positions"] == [0, 2, 4]
        assert idx["index"]["y"]["postings"]["u1"]["positions"] == [1, 3]

    def test_positions_count_after_tokenisation_not_chars(self):
        """Punctuation is dropped by the tokenizer, so positions are
        purely token offsets, not character offsets."""
        idx = build_index([page("u1", "hello, world! foo")])
        assert idx["index"]["hello"]["postings"]["u1"]["positions"] == [0]
        assert idx["index"]["world"]["postings"]["u1"]["positions"] == [1]
        assert idx["index"]["foo"]["postings"]["u1"]["positions"] == [2]


# ---------------------------------------------------------------------------
# Per-document length
# ---------------------------------------------------------------------------
class TestDocLengths:
    def test_doc_length_counts_total_tokens_not_unique(self):
        idx = build_index([page("u1", "a a a b b c")])
        assert idx["doc_lengths"]["u1"] == 6  # 3 a + 2 b + 1 c

    def test_empty_page_has_length_zero(self):
        idx = build_index([page("u1", "")])
        assert idx["doc_lengths"]["u1"] == 0

    def test_doc_length_excludes_punctuation(self):
        idx = build_index([page("u1", "hello, world!")])
        assert idx["doc_lengths"]["u1"] == 2

    def test_every_input_url_appears_in_doc_lengths(self):
        urls = [f"u{i}" for i in range(4)]
        idx = build_index([page(u, "x") for u in urls])
        assert set(idx["doc_lengths"]) == set(urls)


# ---------------------------------------------------------------------------
# Tokenizer integration (case folding & normalisation)
# ---------------------------------------------------------------------------
class TestTokenizerIntegration:
    def test_case_insensitive_merging(self):
        idx = build_index([page("u1", "Good GOOD good")])
        # All three uppercase variants merge into a single token "good".
        assert "Good" not in idx["index"]
        assert "GOOD" not in idx["index"]
        assert idx["index"]["good"]["postings"]["u1"]["tf"] == 3

    def test_punctuation_stripped(self):
        idx = build_index([page("u1", "Don't, won't!")])
        # Apostrophes split contractions per tokenizer rules.
        assert "don't" not in idx["index"]
        assert idx["index"]["don"]["postings"]["u1"]["tf"] == 1
        assert idx["index"]["t"]["postings"]["u1"]["tf"] == 2

    def test_numbers_indexed(self):
        idx = build_index([page("u1", "Born in 1854 died 1900")])
        assert "1854" in idx["index"]
        assert "1900" in idx["index"]


# ---------------------------------------------------------------------------
# Multi-document interactions
# ---------------------------------------------------------------------------
class TestMultipleDocuments:
    def test_term_appearing_in_two_docs_has_two_postings(self):
        idx = build_index(
            [page("u1", "shared unique1"), page("u2", "shared unique2")]
        )
        postings = idx["index"]["shared"]["postings"]
        assert set(postings.keys()) == {"u1", "u2"}
        assert all(p["tf"] == 1 for p in postings.values())

    def test_positions_independent_per_document(self):
        idx = build_index(
            [page("u1", "x foo x"), page("u2", "foo x bar x")]
        )
        assert idx["index"]["x"]["postings"]["u1"]["positions"] == [0, 2]
        assert idx["index"]["x"]["postings"]["u2"]["positions"] == [1, 3]

    def test_disjoint_vocab_produces_separate_entries(self):
        idx = build_index([page("u1", "alpha beta"), page("u2", "gamma delta")])
        assert idx["index"]["alpha"]["postings"].keys() == {"u1"}
        assert idx["index"]["gamma"]["postings"].keys() == {"u2"}


# ---------------------------------------------------------------------------
# Realistic mini end-to-end (no network — uses synthetic CrawledPages)
# ---------------------------------------------------------------------------
class TestRealisticScenario:
    @pytest.fixture
    def mini_corpus(self):
        return [
            page(
                "https://quotes.toscrape.com/page/1/",
                "The world as we have created it is a process of our thinking.",
            ),
            page(
                "https://quotes.toscrape.com/page/2/",
                "Try not to become a man of success but rather try to become a man of value.",
            ),
            page(
                "https://quotes.toscrape.com/page/3/",
                "There are only two ways to live your life. One is as though nothing is a miracle.",
            ),
        ]

    def test_common_stopword_appears_in_all_docs(self, mini_corpus):
        idx = build_index(mini_corpus)
        # "a" appears in all three sample sentences.
        assert idx["index"]["a"]["df"] == 3

    def test_unique_word_appears_in_one_doc_only(self, mini_corpus):
        idx = build_index(mini_corpus)
        assert idx["index"]["miracle"]["df"] == 1

    def test_total_token_count_matches_sum_of_doc_lengths(self, mini_corpus):
        idx = build_index(mini_corpus)
        total_from_tf = sum(
            posting["tf"]
            for entry in idx["index"].values()
            for posting in entry["postings"].values()
        )
        total_from_lengths = sum(idx["doc_lengths"].values())
        assert total_from_tf == total_from_lengths

    def test_no_capitalised_tokens_in_index(self, mini_corpus):
        idx = build_index(mini_corpus)
        for term in idx["index"]:
            assert term == term.lower(), f"Token {term!r} is not lower-cased"