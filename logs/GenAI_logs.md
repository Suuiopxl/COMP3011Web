# GenAI Interaction Log

**Tool used:** Claude (Anthropic, accessed via the official chat interface).
**Role:** Pair-programming partner under human-in-the-loop control.

This document is a strictly factual record of every interaction with the
AI tool during this coursework. It is intended as the offline evidence
artefact referenced by the 30-second GenAI evaluation segment of the
video demonstration.

**Conventions used in this log**

- "U:" — message sent by the student (the user).
- "A:" — response by Claude (the assistant).
- File contents are summarised by filename only; full implementations
  live in `src/` and `tests/` under version control.

---

## 1. Project orientation and environment choice

**U:** Provided the coursework brief PDF and asked the assistant to read
the project documentation, summarise what the assignment requires, and
recommend a development environment from two candidates: VS Code on WSL2
or GitHub Codespaces.

**A:** Summarised the assignment as building a Python search engine for
`quotes.toscrape.com` with four CLI commands (`build`, `load`, `print`,
`find`), a 6-second politeness window, and a 5-minute video
demonstration carrying 30% of the module mark. Recommended
**VS Code + WSL2** over Codespaces on five grounds: zero cost, more
stable HTTP behaviour from a residential IP, no idle-suspension during
the long polite crawl, simpler video-recording workflow, and offline
development support.

---

## 2. Workflow and architecture planning

**U:** Asked the assistant to plan the workflow and lay out the project
architecture.

**A:** Proposed a directory layout matching the brief's required
structure (`src/`, `tests/`, `data/`, plus `scripts/` and `docs/`),
described eight modules with their responsibilities and dependencies,
and broke the work into seven sequential stages: Tokenizer → Crawler
→ Indexer → Storage → Search → CLI → Bonus features. Proposed a
semantic-commit Git workflow and a 10-day calendar. Suggested storing
`tf`, `df`, and word positions in the inverted index from the start so
that later TF-IDF work would not require re-crawling.

**U:** Accepted the seven-stage plan and asked that design-decision
questions be posed at the start of every stage.

---

## 3. Stage 1 — Tokenizer

**U:** Said: "Start stage 1."

**A:** Asked three design-decision questions: punctuation handling,
numeric-token handling, and whether to add stop-word removal or
stemming. Recommended one option for each and explained the trade-offs.

**U:** Selected: split on all punctuation including apostrophes; keep
numeric tokens; no stop-word removal, no stemming.

**A:** Created `src/tokenizer.py` (8 statements: lowercase + regex
`[a-z0-9]+`) and `tests/test_tokenizer.py` (26 tests grouped into 7
classes). Reported 100% line coverage.

---

## 4. Test execution error — wrong pytest invocation

**U:** Reported: `python3 tests/test_tokenizer.py` failed with
`ModuleNotFoundError: No module named pytest`.

**A:** Identified two distinct problems: (a) test files must be invoked
via `python -m pytest`, not as scripts, and (b) the user had not yet
installed `pytest` in their virtual environment. Provided a single
consolidated dependencies list (`requests`, `beautifulsoup4`, `lxml`,
`pytest`, `pytest-cov`, `requests-mock`) and a complete `requirements.txt`
and `.gitignore`.

---

## 5. Virtual-environment creation error

**U:** Reported: `source .venv/bin/activate` failed with `No such file or
directory`.

**A:** Diagnosed that `python3 -m venv .venv` had silently failed because
Ubuntu does not ship `python3-venv` by default. Provided a three-step
fix (`sudo apt install python3-venv python3-pip`, recreate venv,
activate), plus a fallback for Python-version-specific venv packages.

---

## 6. Dependencies not installed inside venv

**U:** Reported, after activating venv, that
`python -m pytest tests/test_tokenizer.py` failed with
`No module named pytest`.

**A:** Pointed out that pytest was not yet installed inside the freshly
created venv, instructed `pip install -r requirements.txt`, and provided
the equivalent one-liner.

---

## 7. Asking how the tokenizer works

**U:** "What is the principle behind your `tokenizer.py`? Can it be run
directly?"

**A:** Walked the user through the two steps of the implementation
(`.lower()` followed by `re.findall(r"[a-z0-9]+", ...)`), traced the
behaviour on a concrete example, and explained why each design decision
(pre-compiled regex, `findall` over `split`, type guard) was made.
Explained that the module is library-only and showed three ways to
exercise it (pytest, Python REPL, doctest). Offered an optional
`if __name__ == "__main__"` demo entry point and recommended against
adding it because the real entry point would be `src/main.py` in
stage 6.

---

## 8. Stage 2 — Crawler

**U:** "Stage 2."

**A:** Asked four design-decision questions: which pages to crawl,
traversal strategy, content-extraction granularity, and how to handle
the politeness window during testing.

**U:** Selected: pagination only (10 pages); BFS with `collections.deque`;
extract all visible text; configurable politeness delay defaulting to 6
seconds (zero in tests).

**A:** Created `src/crawler.py` (81 statements: `CrawledPage` named
tuple, `Crawler` class with injectable delay/session, BFS frontier, link
filter on same domain) and `tests/test_crawler.py` (25 tests using
`requests-mock` for offline determinism).

---

## 9. Crawler test failures — caught by the assistant before user execution

**U:** Reviewed the assistant's claim that the tests passed.

**A:** First run produced 4 failing tests, which the assistant reported
honestly rather than hiding. Two distinct root causes were diagnosed:

- `requests.Session.headers.setdefault` for User-Agent is a no-op because
  `Session` ships with its own default UA. Fixed by setting the header
  unconditionally on internally-created sessions.
- Two tests for text extraction used a fixture page that contained a
  "Next" link, but did not register a mock for the next URL, so the
  crawler hit `NoMockAddress`. Fixed by registering the second URL.

After the fixes, 22 of 22 tests passed but coverage was 95%. The
assistant added three more tests targeting the uncovered branches
(custom session injection, custom UA override on injected session,
duplicate-Next-link defensive deduplication), reaching 100%.

---

## 10. Real-network smoke test of the crawler

**A:** Ran the crawler against the live site with a 2-second delay in
the sandbox and reported the output (10 pages, each between 1481 and
3462 visible characters), demonstrating that the crawler behaved
correctly outside of the mocked test environment.

**U:** Ran the same command locally and confirmed an exact match of
page count and character counts.

---

## 11. Stage 3 — Indexer

**U:** "Stage 3."

**A:** Asked three design-decision questions: index granularity,
multi-word query semantics, and tokenizer integration.

**U:** Selected: store `tf` + `positions` + per-document length; strict
AND for multi-word queries; reuse `tokenizer.tokenize` directly.

**A:** Created `src/indexer.py` (33 statements: two-pass algorithm —
per-document positional aggregation, then global merge — with
`TypedDict` annotations) and `tests/test_indexer.py` (27 tests).
Reported 100% line coverage.

---

## 12. Stage 4 — Storage

**U:** "Stage 4."

**A:** Asked three design-decision questions: serialisation format,
path configurability, and missing-file error handling.

**U:** Selected: JSON, pretty-printed; default path with override
parameter; custom `IndexNotFoundError`.

**A:** Created `src/storage.py` (26 statements: atomic write via
temp-file + `os.replace`, `IndexNotFoundError` as a `FileNotFoundError`
subclass, top-level shape validation) and `tests/test_storage.py` (18
tests including a monkeypatched `os.replace` to simulate disk failure
and prove the existing index survives). 100% line coverage.

---

## 13. End-to-end smoke-test script

**U:** "Turn the end-to-end smoke test into a separate script so it
doesn't need to be typed in the terminal every time."

**A:** Created `scripts/smoke_test.py` with `argparse` (configurable
delay, output path, optional `--no-save`), four numbered progress
sections, non-zero exit on failure, and `sys.path` self-configuration so
the script can be launched from any working directory.

---

## 14. Stage 5 — Search

**U:** "Stage 5."

**A:** Asked four design-decision questions: result ordering for `find`,
output format of `find`, output format of `print`, and behaviour on
zero-result queries.

**U:** Selected: sort by total tf descending with URL ascending as
tiebreak; URL + score in `find` output; multi-line `Term 'X' (df=Y)`
header followed by per-URL lines for `print`; an explicit
"No pages contain all of: '...', '...'" message on no-results.

**A:** Created `src/search.py` (53 statements: `lookup`, `find`,
`format_print`, `format_find`; `SearchResult` named tuple; set
intersection for AND; `dict.fromkeys` for order-preserving query
de-duplication) and `tests/test_search.py` (33 tests). 100% line
coverage.

---

## 15. Demo queries script

**U:** Asked the assistant to package the brief examples and edge cases
into a single replayable script.

**A:** Created `scripts/demo_queries.py` containing the three brief
example commands plus eight edge cases (unknown term, mixed AND with
unknown term, empty query, pure punctuation, case-insensitive query,
duplicate query terms, unknown `print` argument, empty `print`). The
script exits with a non-zero status if the index file is missing.

---

## 16. Stage 6 — CLI shell

**U:** "Stage 6."

**A:** Asked four design-decision questions: CLI style (REPL vs.
one-shot), state management, entry-point location, and REPL exit
mechanisms.

**U:** Selected: interactive REPL with `>` prompt (matches the brief);
index held in memory between commands; `src/main.py` entry point invoked
as `python -m src.main`; multiple exit paths including silent
`KeyboardInterrupt` handling.

**A:** Created `src/main.py` (92 statements: `SearchEngineShell` class
with `execute()` and `run_repl()` separated for testability, dict-based
command-dispatch table, defensive guards, `argparse` for CLI overrides)
and `tests/test_main.py` (32 tests including scripted REPL sessions via
patched `builtins.input`). 100% line coverage.

---

## 17. Stage 7a — TF-IDF extension

**U:** "Continue to stage 7. Complete TF-IDF. Also add a README that
meets the requirements for the current implementation."

**A:** Asked four design-decision questions: which IDF formula, how to
normalise TF, how to surface TF-IDF in the CLI, and whether to give the
project a product name.

**U:** Selected: sklearn-style smoothed IDF `log((N+1)/(df+1)) + 1`;
log-normalised TF `1 + log(tf)`; `find --rank tfidf` opt-in flag
preserving default `tf` behaviour; keep the existing repository name.

**A:** Refactored `src/search.py` to a strategy-pattern scoring API
(`_SCORE_FUNCS` dispatching to `_tf_score` and `_tfidf_score`); updated
`src/main.py` with a `_parse_find_args` helper and an updated help
string; added 9 new TF-IDF tests and 6 new `--rank`-flag tests. **All
161 pre-existing tests passed with zero regressions** — the default
`find` output is byte-identical to before TF-IDF was introduced.

---

## 18. TF-IDF test logic error — assistant wrong, user code right

**A:** Reported that 1 of the 178 tests failed:
`test_tfidf_rare_term_outranks_common_term`. Investigated by hand-
calculating both scores. The expected outcome — "a rare term should
outscore a common term" — turned out to be a **mistaken assumption
encoded in the test by the assistant itself**: with the user-chosen
sklearn-smoothed IDF formula, a term with `df = N` (appears in every
document) has IDF `= 1.0` rather than `0`, which is precisely the
behaviour the `+1` smoothing is designed to produce. The test was
therefore over-claiming. Replaced the test with
`test_tfidf_rare_term_has_higher_idf_weight`, which holds `tf` equal
across the two terms and verifies the **IDF weight component** is
larger for the rarer term — a more precise assertion that actually
follows from the formula. Documented this episode openly in this log
as an example of an AI-generated test that needed correction.

---

## 19. README

**A:** Created `README.md` (~370 lines) with table of contents, quick
start, project layout, ASCII architecture diagram, command reference,
on-disk index format documentation, testing instructions with the
current coverage report, a per-module design-decisions section, and a
dedicated TF-IDF extension section including the formula and the
rationale for choosing each part of it. Cited the scikit-learn default
`TfidfTransformer` parameters and Salton 1988 as references.

---

## 20. GenAI log scoping

**U:** Asked whether the chat transcript should be displayed in the
video.

**A:** Recommended against showing the transcript on camera (only 30
seconds of the 5-minute budget are allocated to GenAI evaluation, and
the brief asks for *critical reflection* rather than transcript
evidence). Recommended a slide-plus-narration approach for the video
and keeping this written log as the offline evidence artefact.

**U:** Requested a complete factual log of all interactions, translated
to English, with file contents summarised by filename only.

**A:** Produced this document.

---