# COMP3011Web
# COMP3011Web

**A Python search engine for [quotes.toscrape.com](https://quotes.toscrape.com/).**
Built as Coursework 2 for COMP3011 *Web Services and Web Data* (University of
Leeds).

The tool crawls the site, builds an inverted index of every word occurrence,
saves the index to disk, and answers two query commands: `print` (raw entry
for a term) and `find` (Boolean AND query across multiple terms, ranked).

---

## Table of contents

- [Quick start](#quick-start)
- [Project layout](#project-layout)
- [Architecture](#architecture)
- [Usage](#usage)
- [Index file format](#index-file-format)
- [Testing](#testing)
- [Design decisions](#design-decisions)
- [Extension: TF-IDF ranking](#extension-tf-idf-ranking)

---

## Quick start

```bash
# 1. Clone and enter
git clone https://github.com/<you>/COMP3011Web.git
cd COMP3011Web

# 2. Create a virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Launch the interactive shell
python -m src.main
```

You will see:

```
COMP3011 Search Engine — quotes.toscrape.com
Type 'help' for commands, 'exit' or Ctrl-D to quit.
> build
Crawling https://quotes.toscrape.com/ (this will take a moment)...
    [INFO] Crawl finished: 213 URL(s) fetched, 150 unique document(s) indexed.
Built index: 150 docs, 4563 unique terms. Saved to data/index.json (~2.1 MB).
> find good friends
4 page(s) found:
  https://quotes.toscrape.com/tag/inspirational/page/1/#quote-4   (score=5)
  https://quotes.toscrape.com/tag/life/page/1/#quote-5   (score=4)
  ...
> exit
```

The first `build` takes about 21 minutes because the crawler waits 6 s
between requests (the politeness window required by the brief) and the
site has 213 pages. Subsequent sessions can use `load` to skip straight
to querying:

```
> load
Loaded index: 150 docs, 4563 unique terms, from data/index.json.
> find indifference
1 page(s) found:
  https://quotes.toscrape.com/tag/inspirational/page/1/#quote-5   (score=5)
```

**A note on "documents"**: each document in the index is one *unique
quote* (deduplicated across pages where the same quote appears) or one
*author detail page*. The site has 100 distinct quotes and 50 authors,
so the index contains 150 documents — not 213. See
[Design decisions](#design-decisions) for the rationale.

### Requirements

- Python 3.10 or newer (uses `Literal`, `TypedDict`, and structural pattern
  matching only insofar as they are part of those standard libraries — no
  3.10-specific syntax is used).
- The runtime and test dependencies are pinned in `requirements.txt`:

  | Package        | Purpose                                |
  |----------------|----------------------------------------|
  | `requests`     | HTTP client used by the crawler        |
  | `beautifulsoup4` + `lxml` | HTML parsing                |
  | `pytest`       | Test runner                            |
  | `pytest-cov`   | Coverage reports                       |
  | `requests-mock`| Mock HTTP responses in crawler tests   |

---

## Project layout

```
COMP3011Web/
├── src/                    # all production code
│   ├── __init__.py
│   ├── tokenizer.py        # text normalisation (case-fold, alphanumeric split)
│   ├── crawler.py          # BFS crawler with 6 s politeness window
│   ├── indexer.py          # builds the inverted index from crawled pages
│   ├── storage.py          # save/load index as JSON, atomic writes
│   ├── search.py           # print / find logic, TF and TF-IDF ranking
│   └── main.py             # interactive REPL (build / load / print / find)
├── tests/                  # 183 tests, 100 % line coverage on src/
│   ├── test_tokenizer.py
│   ├── test_crawler.py     # uses requests-mock, no real network in CI
│   ├── test_indexer.py
│   ├── test_storage.py
│   ├── test_search.py
│   └── test_main.py
├── scripts/                # development convenience scripts
│   ├── smoke_test.py       # end-to-end crawl → build → save → load → verify
│   └── demo_queries.py     # runs brief examples + edge cases
├── data/
│   └── index.json          # the compiled index (created by `build`)
├── requirements.txt
├── .gitignore
└── README.md               # this file
```

---

## Architecture

The pipeline is a one-way data flow with **strict module boundaries**:

```
┌──────────────────────────────────────────────────────────────────┐
│                         src/main.py                              │
│   Interactive REPL — build / load / print / find / help / exit   │
└──────────────────────────────────────────────────────────────────┘
              │                          │
       build  │                          │  print / find
              ▼                          ▼
┌──────────────────────┐         ┌──────────────────────┐
│   src/crawler.py     │         │   src/search.py      │
│   BFS + 6 s delay    │         │   AND intersection   │
└──────────┬───────────┘         │   tf / tfidf ranking │
           │                     └──────────┬───────────┘
           ▼                                │
┌──────────────────────┐                    │
│   src/indexer.py     │  ◄─────────────────┘
│   build inverted     │
│   index (tf, df,     │
│   positions, lengths)│
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│   src/storage.py     │
│   JSON, atomic write │
└──────────────────────┘

  All text passes through src/tokenizer.py — at crawl time AND at query time.
  Using one tokenizer everywhere is the only way to guarantee that the
  vocabulary in the index matches the vocabulary in user queries.
```

Each module has a single responsibility, has no circular dependencies, and is
unit-tested in isolation. The CLI is the only file that wires them together.

---

## Usage

The interactive shell implements exactly the four commands the brief
specifies, with a `help` command and three exit paths added for usability.

| Command                  | Effect                                                    |
|--------------------------|-----------------------------------------------------------|
| `build`                  | Crawl the site, build the index, save it to disk          |
| `load`                   | Load the saved index from `data/index.json`               |
| `print <word>`           | Show the inverted-index entry for `<word>`                |
| `find <terms…>`          | Find pages containing **all** of `<terms>` (AND query)    |
| `find --rank tfidf <terms…>` | Same as `find`, but rank by TF-IDF score             |
| `help`                   | Print the command list                                    |
| `exit` / `quit` / Ctrl-D | Leave the shell                                           |
| Ctrl-C                   | Same as `exit`, suppresses the default traceback          |

CLI overrides (useful for tests and tighter politeness windows):

```bash
python -m src.main --delay 2                       # 2 s politeness (still polite)
python -m src.main --index /tmp/my_index.json      # custom index location
python -m src.main --base-url https://example.com/ # crawl a different site
python -m src.main --help                          # full argparse help
```

### Example session

The session below reproduces the brief's three example commands:

```
> print nonsense
Term 'nonsense' (df=2)
  https://quotes.toscrape.com/page/2/#quote-5                       tf=1
  https://quotes.toscrape.com/tag/life/page/1/#quote-10             tf=1

> find indifference
1 page(s) found:
  https://quotes.toscrape.com/tag/inspirational/page/1/#quote-5   (score=5)

> find good friends
4 page(s) found:
  https://quotes.toscrape.com/tag/inspirational/page/1/#quote-4   (score=5)
  https://quotes.toscrape.com/tag/life/page/1/#quote-5            (score=4)
  https://quotes.toscrape.com/author/George-Eliot                 (score=2)
  https://quotes.toscrape.com/author/J-K-Rowling                  (score=2)
```

Each URL ends with `#quote-N` for quote documents (where N is the
quote's position on the original page) or with `/author/<name>` for
author detail pages. This makes every document independently
addressable in the index.

### Edge cases

The shell handles common bad inputs without crashing:

```
> find xyz123
No pages contain all of: 'xyz123'

> find good xyz
No pages contain all of: 'good', 'xyz'

> find
Usage: find [--rank tf|tfidf] <term> [<term> ...]

> print
Usage: print <word>

> print XYZ                # case is normalised the same as during indexing
Term 'xyz' not in index.

> wat                       # unknown command
Unknown command: 'wat'. Type 'help' for available commands.
```

The full set of edge cases is exercised by `scripts/demo_queries.py`.

---

## Index file format

The on-disk index is a single pretty-printed UTF-8 JSON file at
`data/index.json` (~2.1 MB). Top-level shape:

```json
{
  "index": {
    "good": {
      "df": 14,
      "postings": {
        "https://quotes.toscrape.com/page/4/#quote-3": {
          "tf": 2,
          "positions": [3, 8]
        },
        "https://quotes.toscrape.com/author/J-K-Rowling": {
          "tf": 1,
          "positions": [47]
        }
      }
    }
  },
  "doc_lengths": {
    "https://quotes.toscrape.com/page/4/#quote-3": 25,
    "https://quotes.toscrape.com/author/J-K-Rowling": 110
  },
  "num_docs": 150
}
```

| Field          | Meaning                                                    |
|----------------|------------------------------------------------------------|
| `index[t]`     | Inverted-index entry for term `t`                          |
| `…df`          | Number of documents containing `t`                         |
| `…postings`    | Map of URL → `{tf, positions}` for documents that have `t` |
| `…postings.tf` | Number of times `t` appears in that document               |
| `…positions`   | Zero-indexed offsets into the document's token stream      |
| `doc_lengths[u]` | Total number of tokens in document `u` (for TF-IDF/BM25) |
| `num_docs`     | Total documents in the corpus (100 quotes + 50 authors)    |

JSON was chosen over `pickle` because the brief asks for the index file to
be submitted; a human-readable artifact is easier to inspect and audit. See
[`src/storage.py`](src/storage.py) for the rationale and atomic-write logic.

---

## Testing

The project ships with **183 tests** covering every module. To run them:

```bash
# Run all tests
python -m pytest

# With coverage report
python -m pytest --cov=src --cov-report=term-missing

# A single file
python -m pytest tests/test_search.py -v
```

Current results:

```
================ tests coverage =================
src/__init__.py        0      0   100%
src/crawler.py       119      0   100%
src/indexer.py        33      0   100%
src/main.py          107      0   100%
src/search.py         73      0   100%
src/storage.py        26      0   100%
src/tokenizer.py       8      0   100%
-------------------------------------------------
TOTAL                366      0   100%
================ 183 passed in 1.4s ==============
```

### Testing strategy

* **No real network in tests.** `tests/test_crawler.py` uses
  `requests-mock` so the entire suite runs offline in 1–2 seconds. This
  also means the test run is *polite by construction* — even if a
  developer runs `pytest` in a tight loop, the live site sees nothing.
* **Dependency injection for slow operations.** Both the crawler's
  politeness delay and the `Crawler` itself (in `_cmd_build`) are
  injectable, so tests run instantly while production uses the brief's
  required 6 s window.
* **Pure-vs-impure separation.** Logic-heavy modules expose pure
  functions (`build_index`, `find`, `lookup`) that take inputs and
  return outputs; I/O wrappers (`save_index`, `format_print`,
  `SearchEngineShell.execute`) sit thinly on top. The pure functions
  are tested by direct equality assertions; the wrappers are tested
  with `capsys` for captured stdout.
* **Edge cases are explicit.** Empty queries, pure-punctuation
  queries, duplicate query terms, unknown terms, mid-stream network
  failure, atomic-write interruption — every one of these has a named
  test that documents the expected behaviour.

### Convenience scripts

```bash
# End-to-end smoke test: crawl → build → save → load → verify
python scripts/smoke_test.py --delay 2

# Replay brief examples + edge cases on the saved index
python scripts/demo_queries.py
```

Both scripts exit with a non-zero status on failure, so they can later be
plugged into a CI pipeline without code changes.

---

## Design decisions

This section summarises the choices made at each stage and the rationale.
Every decision is also documented in the corresponding module's docstring.

### Tokenizer (`src/tokenizer.py`)
* Case-folding via `text.lower()` — required by the brief.
* Single regex `[a-z0-9]+` extracts maximal alphanumeric runs. Punctuation,
  apostrophes, hyphens, and whitespace all act as separators.
  Apostrophes are deliberately split (`"don't"` → `["don", "t"]`) because
  it keeps the rule a one-liner and the brief's queries do not contain
  contractions.
* No stop-word removal and no stemming — the brief asks us to index *all*
  word occurrences.

### Crawler (`src/crawler.py`)
* **Full-site BFS traversal.** Starting from the home page we follow
  the `Next →` pagination link, all `/tag/...` listings (with their
  own pagination), and all `/author/...` detail pages — 213 unique
  URLs in total. `/login` and `/static/...` are skipped. URLs are
  normalised (URL fragments stripped) and de-duplicated via a
  `visited` set, so the dense graph of cross-links cannot cause
  infinite loops.
* **BFS with `collections.deque`**, the standard frontier-queue
  pattern; `popleft()` is O(1) where a Python `list.pop(0)` would
  be O(n).
* **Content-aware text extraction.** Each page type has its own
  content container:
  - quote-listing pages → every `<div class="quote">`
  - author detail pages → `<div class="author-details">`
  Everything else on the page — the site title (`<h1>Quotes to
  Scrape</h1>`), navigation, "Top Ten tags" sidebar, footer — is
  *deliberately discarded*. Otherwise searching `find quotes` would
  return every page just because the site title contains the word.
* **Quote-level deduplication.** The same quote appears on multiple
  HTML pages (home listing, tag listings, …). Each quote block is
  keyed by `(quote_text, author)` and the first occurrence wins,
  so the inverted index counts each quote exactly once. The result
  is 100 unique quote documents + 50 author documents = 150 indexed
  documents, drawn from 213 fetched URLs.
* **Politeness window is configurable, defaults to 6 s**, and is
  computed as `delay − elapsed_since_last_request` rather than a
  blind `sleep(6)` so HTML parsing time counts toward the wait.

### Indexer (`src/indexer.py`)
* **Per-term fields stored:** `tf`, `df`, `positions`.
* **Per-document length stored** so future BM25 / length-normalised TF can
  be added without re-crawling.
* **Two-pass build:** aggregate positions inside each document first, then
  merge into the global index. This makes `df` correctness obvious — it
  cannot accidentally count the same document twice.

### Storage (`src/storage.py`)
* **JSON, pretty-printed.** Human-readable, language-agnostic, and easy
  for the marker to inspect.
* **Atomic writes** via temp file + `os.replace`. A crash mid-write never
  leaves a half-written `index.json` behind. A test (`monkeypatch`-ing
  `os.replace` to raise) verifies the pre-existing file survives.
* **Custom `IndexNotFoundError`** subclasses `FileNotFoundError`, giving
  the CLI a specific exception to catch ("did you run `build` first?")
  without breaking generic `except FileNotFoundError` handlers.

### Search (`src/search.py`)
* **AND semantics via `set` intersection** of the URL key-sets of each
  term's posting list — the textbook Boolean-IR approach.
* **Default ranking: sum of term frequencies**, with URL ascending as the
  deterministic tiebreak. This is a meaningful "how relevant" signal
  beyond pure Boolean retrieval and provides the natural upgrade path
  to TF-IDF (see below).
* **Query terms are de-duplicated** with `dict.fromkeys` (insertion-order
  preserved), so `find good good` is equivalent to `find good`.

### CLI (`src/main.py`)
* **Interactive REPL** matching the `>` prompt in the brief.
* **Index resident in memory between commands** — `build` and `load` pay
  the I/O cost once, every subsequent `find` is microseconds.
* **Dispatch table** (`dict[str, Callable]`) for commands; adding a new
  command is a 4-line change.
* **Three exit paths**, including `KeyboardInterrupt` caught silently so
  Ctrl-C does not splash a Python traceback into a recorded demo.

---

## Extension: TF-IDF ranking

The brief's marking rubric lists "Advanced features beyond requirements
(e.g., TF-IDF ranking…)" among the 80+ band indicators. To stay
**strictly backward-compatible with the brief examples**, `find` accepts an
optional `--rank` flag:

```
> find good friends                       # default: sum-of-tf ranking
4 page(s) found:
  https://quotes.toscrape.com/tag/inspirational/page/1/#quote-4   (score=5)
  https://quotes.toscrape.com/tag/life/page/1/#quote-5            (score=4)
  https://quotes.toscrape.com/author/George-Eliot                 (score=2)
  https://quotes.toscrape.com/author/J-K-Rowling                  (score=2)

> find --rank tfidf good friends          # TF-IDF ranking
4 page(s) found:
  https://quotes.toscrape.com/tag/inspirational/page/1/#quote-4   (score=11.7385)
  https://quotes.toscrape.com/tag/life/page/1/#quote-5            (score=11.5838)
  https://quotes.toscrape.com/author/George-Eliot                 (score=6.8416)
  https://quotes.toscrape.com/author/J-K-Rowling                  (score=6.8416)
```

### Formula

For each query term `t` and document `d`:

```
tf_weight(t, d)  = 1 + ln(tf(t, d))
idf_weight(t)    = ln((N + 1) / (df(t) + 1)) + 1
contribution     = tf_weight(t, d) × idf_weight(t)
score(q, d)      = Σ contribution for every t in q
```

* `N` is the total number of documents.
* `df(t)` is the number of documents containing `t`.
* `tf(t, d)` is the frequency of `t` in `d` (always ≥ 1 because we only
  score documents that survive the AND intersection).
* Natural logarithm is used throughout; the choice of base only rescales
  all scores by a constant and therefore does not affect ranking.

### Why this formula?

* **Smoothed IDF** (`+1` in both numerator and denominator) is the same
  variant scikit-learn uses by default. It avoids the pathological case
  where a term appearing in every document (`df = N`) gets `log(1) = 0`
  and is silently dropped from scoring. With our content-aware
  crawler the corpus no longer has any literal df=N terms (because
  navigation and footer chrome are stripped), but the smoothing still
  matters for *near-ubiquitous* function words like "the" and "and"
  which have df > 100 / 150 — without it their IDF would round to a
  very small number and the score would be dominated by noise.
* **Logarithmic TF** is Salton's classic sub-linear transform: a term
  appearing 100 times is *not* 100× more important than appearing once,
  and the log compresses that effect. A test
  (`test_tfidf_log_tf_is_sublinear`) verifies that doubling raw tf gives
  a score increase strictly less than 2×.
* **Length normalisation is intentionally omitted.** BM25-style
  per-document length normalisation would be the natural next step;
  `doc_lengths` is already present in the index for that purpose.

The implementation is in `_tfidf_score()` in `src/search.py`, with five
dedicated tests in `TestTfidfRanking` and `TestTfidfFormatting`.

---

## Acknowledgements

* Target site: [quotes.toscrape.com](https://quotes.toscrape.com/) — a
  practice site maintained by the Scrapy project.
* TF-IDF smoothing variant: `sklearn.feature_extraction.text.TfidfTransformer`
  default (`smooth_idf=True`, `sublinear_tf=True`).
* I acknowledge the use of Claude (Anthropic, https://claude.ai/) in this project, including:
  1. Generate all relevant codes, .md documents, and video presentation scripts.
  2. Provide design suggestions and decisions.
  3. Offer an outline of the project workflow.
  4. Debug and verify the accuracy of the output.
  5. Analyze the scoring criteria to ensure the practice meets the relevant requirements.
  6. Explain the concepts.
  7. Generate the video slides.
* The GenAI conversation records have been saved in the GitHub repository.
