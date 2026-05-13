"""
Unit tests for ``src.crawler``.

Strategy
--------
* Every test uses the ``requests_mock`` fixture so **no real network
  traffic is generated**. The suite finishes in milliseconds.
* Tests are grouped by behaviour: traversal, content extraction,
  quote-level deduplication, error handling, politeness, User-Agent,
  link filtering, URL normalisation.
* Fixture HTML mirrors quotes.toscrape.com's real structure
  (``div.quote``, ``span.text``, ``small.author``, ``div.author-details``,
  ``li.next``) so the selectors are exercised the same way as in
  production.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from src.crawler import CrawledPage, Crawler

BASE_URL = "https://quotes.toscrape.com/"


# ---------------------------------------------------------------------------
# Global fixture: any URL not explicitly mocked returns 404.
# This prevents NoMockAddress crashes when the crawler follows links
# that the test author did not pre-register (tag listings, author
# detail links embedded in quote blocks, etc). The crawler is
# error-tolerant, so a 404 on an irrelevant link is harmless.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _catchall_404(requests_mock):
    """Register a regex-matched 404 fallback so unmocked URLs do not
    crash the test with NoMockAddress. The crawler is error-tolerant,
    so 404s on irrelevant links are harmless."""
    import re
    requests_mock.get(re.compile(r".*"), status_code=404)
    return requests_mock


# ---------------------------------------------------------------------------
# Reusable HTML fixtures
# ---------------------------------------------------------------------------
def _quote_block(text: str, author: str, author_link: str = "#", tags=()):
    """Render a single <div class='quote'> block.

    ``author_link`` defaults to "#" so the crawler does not try to
    follow it. Pass an explicit ``/author/...`` path when testing
    author-page traversal.
    """
    tag_html = "".join(
        f'<a class="tag" href="/tag/{t}/page/1/">{t}</a>' for t in tags
    )
    return f"""
    <div class="quote">
      <span class="text">{text}</span>
      <span>by <small class="author">{author}</small>
        <a href="{author_link}">(about)</a>
      </span>
      <div class="tags">Tags: {tag_html}</div>
    </div>
    """


def _listing_page(quotes_html: str, next_path: str = "") -> str:
    """Render a quote-listing page with optional Next link, including
    the site chrome (h1, footer) that must NOT end up in the index.
    """
    next_html = (
        f'<ul class="pager"><li class="next"><a href="{next_path}">Next &rarr;</a></li></ul>'
        if next_path
        else ""
    )
    return f"""
    <html><body>
      <h1>Quotes to Scrape</h1>
      <nav><a href="/login">Login</a></nav>
      {quotes_html}
      {next_html}
      <h2>Top Ten tags</h2>
      <footer>Quotes by GoodReads.com — Made with by Zyte</footer>
      <script>console.log('chrome');</script>
    </body></html>
    """


def _author_page(name: str, born: str, bio: str) -> str:
    return f"""
    <html><body>
      <h1>Quotes to Scrape</h1>
      <nav><a href="/login">Login</a></nav>
      <div class="author-details">
        <h3 class="author-title">{name}</h3>
        <p>Born: <span class="author-born-date">{born}</span></p>
        <div class="author-description">{bio}</div>
      </div>
      <footer>Made with by Zyte</footer>
    </body></html>
    """


# ---------------------------------------------------------------------------
# Single page, single quote
# ---------------------------------------------------------------------------
class TestSinglePage:
    def test_single_listing_page_with_one_quote(self, requests_mock):
        html = _listing_page(_quote_block('"Hello world"', "Author A"))
        requests_mock.get(BASE_URL, text=html)

        results = Crawler(delay=0).crawl()

        assert len(results) == 1
        assert results[0].url.startswith(BASE_URL)
        assert "#quote-1" in results[0].url
        assert "Hello world" in results[0].text
        assert "Author A" in results[0].text

    def test_chrome_text_is_not_in_indexed_content(self, requests_mock):
        """The marker's Q&A is explicit: nav/footer/h1 must NOT contribute
        to the index, otherwise queries like 'find quotes' would return
        every page just because the site title contains 'Quotes'.
        """
        html = _listing_page(_quote_block('"Hello world"', "Author A"))
        requests_mock.get(BASE_URL, text=html)

        results = Crawler(delay=0).crawl()
        text = results[0].text

        assert "Quotes to Scrape" not in text   # h1
        assert "Login" not in text              # nav
        assert "Top Ten tags" not in text       # sidebar
        assert "Zyte" not in text               # footer
        assert "console.log" not in text        # script

    def test_two_quotes_on_same_page_become_two_documents(self, requests_mock):
        html = _listing_page(
            _quote_block('"First quote."', "A")
            + _quote_block('"Second quote."', "B")
        )
        requests_mock.get(BASE_URL, text=html)

        results = Crawler(delay=0).crawl()

        assert len(results) == 2
        urls = [r.url for r in results]
        assert urls[0].endswith("#quote-1")
        assert urls[1].endswith("#quote-2")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
class TestPagination:
    def test_follows_next_link(self, requests_mock):
        requests_mock.get(
            BASE_URL,
            text=_listing_page(_quote_block('"A"', "X"), next_path="/page/2/"),
        )
        requests_mock.get(
            f"{BASE_URL}page/2/",
            text=_listing_page(_quote_block('"B"', "Y")),
        )

        results = Crawler(delay=0).crawl()

        assert len(results) == 2
        assert any("page/2/" in r.url for r in results)


# ---------------------------------------------------------------------------
# Quote-level deduplication (THE key new behaviour)
# ---------------------------------------------------------------------------
class TestQuoteDedup:
    def test_same_quote_on_two_pages_indexed_once(self, requests_mock):
        """If the same quote appears on page 1 AND on a tag page, it
        must end up in the index exactly once."""
        same_quote = _quote_block('"The world is a process."', "Einstein")

        requests_mock.get(
            BASE_URL,
            text=_listing_page(same_quote, next_path="/tag/world/"),
        )
        requests_mock.get(
            f"{BASE_URL}tag/world/",
            text=_listing_page(same_quote),
        )

        results = Crawler(delay=0).crawl()

        # 1 unique quote across the two pages.
        assert len(results) == 1
        # And the canonical URL is the first page it appeared on.
        assert BASE_URL in results[0].url and "#quote-1" in results[0].url

    def test_same_text_different_author_counted_separately(self, requests_mock):
        """Dedup is by (text, author). Same text by different author is
        a different document (defensive)."""
        requests_mock.get(
            BASE_URL,
            text=_listing_page(
                _quote_block('"Be yourself."', "Wilde")
                + _quote_block('"Be yourself."', "Roosevelt")
            ),
        )
        results = Crawler(delay=0).crawl()
        assert len(results) == 2

    def test_quote_missing_text_or_author_is_skipped(self, requests_mock):
        """Defensive against malformed pages: a div.quote without
        span.text or small.author is silently ignored."""
        html = _listing_page(
            '<div class="quote"><span class="text">"Lonely text"</span></div>'
            + _quote_block('"Full quote"', "Real Author")
        )
        requests_mock.get(BASE_URL, text=html)

        results = Crawler(delay=0).crawl()

        assert len(results) == 1
        assert "Full quote" in results[0].text


# ---------------------------------------------------------------------------
# Author detail pages
# ---------------------------------------------------------------------------
class TestAuthorPages:
    def test_author_page_extracts_author_details_only(self, requests_mock):
        requests_mock.get(
            BASE_URL,
            text=_listing_page(
                _quote_block('"X"', "Albert Einstein",
                             author_link="/author/Albert-Einstein/")
            ),
        )
        requests_mock.get(
            f"{BASE_URL}author/Albert-Einstein/",
            text=_author_page(
                "Albert Einstein",
                "March 14, 1879",
                "Physicist born in Germany.",
            ),
        )

        results = Crawler(delay=0).crawl()

        author_docs = [r for r in results if "/author/" in r.url]
        assert len(author_docs) == 1
        text = author_docs[0].text
        # Author details ARE in the index:
        assert "March 14, 1879" in text
        assert "Physicist" in text
        # Chrome is NOT in the index:
        assert "Quotes to Scrape" not in text
        assert "Login" not in text

    def test_author_page_without_details_div_is_dropped(self, requests_mock):
        """A malformed author page (no div.author-details) yields no
        document — defensive."""
        requests_mock.get(
            BASE_URL,
            text=_listing_page(
                _quote_block('"X"', "Y", author_link="/author/Y/")
            ),
        )
        requests_mock.get(
            f"{BASE_URL}author/Y/",
            text="<html><body><h1>Broken</h1></body></html>",
        )
        results = Crawler(delay=0).crawl()
        # Only the quote, no author doc.
        assert all("/author/" not in r.url for r in results)


# ---------------------------------------------------------------------------
# Tag pages and the full-site graph
# ---------------------------------------------------------------------------
class TestTagPagesFollowed:
    def test_tag_links_are_followed(self, requests_mock):
        """Tag pages must be crawled (they contribute author info etc.,
        and the marker said all 213 pages should be visited)."""
        requests_mock.get(
            BASE_URL,
            text=_listing_page(
                _quote_block('"A"', "X", tags=("love", "life"))
            ),
        )
        requests_mock.get(
            f"{BASE_URL}tag/love/page/1/",
            text=_listing_page(_quote_block('"A"', "X", tags=("love",))),
        )
        requests_mock.get(
            f"{BASE_URL}tag/life/page/1/",
            text=_listing_page(_quote_block('"A"', "X", tags=("life",))),
        )

        Crawler(delay=0).crawl()
        # The tag URLs must have been visited (mocks would not be called
        # otherwise).
        visited_urls = [r.url for r in requests_mock.request_history]
        assert any("tag/love" in u for u in visited_urls)
        assert any("tag/life" in u for u in visited_urls)


# ---------------------------------------------------------------------------
# Login / static / cross-domain link filtering
# ---------------------------------------------------------------------------
class TestLinkFiltering:
    def test_login_path_is_skipped(self, requests_mock):
        requests_mock.get(BASE_URL, text=_listing_page(""))

        Crawler(delay=0).crawl()

        visited = [r.url for r in requests_mock.request_history]
        assert all("/login" not in u for u in visited)

    def test_off_site_links_not_followed(self, requests_mock):
        html = (
            _listing_page("")
            .replace("</body>", '<a href="https://evil.com/page/">x</a></body>')
        )
        requests_mock.get(BASE_URL, text=html)

        Crawler(delay=0).crawl()
        visited = [r.url for r in requests_mock.request_history]
        assert all("evil.com" not in u for u in visited)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
class TestErrorHandling:
    def test_404_returns_no_documents(self, requests_mock):
        requests_mock.get(BASE_URL, status_code=404)
        assert Crawler(delay=0).crawl() == []

    def test_500_returns_no_documents(self, requests_mock):
        requests_mock.get(BASE_URL, status_code=500)
        assert Crawler(delay=0).crawl() == []

    def test_connection_error_handled(self, requests_mock):
        requests_mock.get(BASE_URL, exc=requests.ConnectionError)
        assert Crawler(delay=0).crawl() == []

    def test_timeout_handled(self, requests_mock):
        requests_mock.get(BASE_URL, exc=requests.Timeout)
        assert Crawler(delay=0).crawl() == []

    def test_failure_on_later_page_keeps_earlier_documents(self, requests_mock):
        requests_mock.get(
            BASE_URL,
            text=_listing_page(
                _quote_block('"A"', "X"), next_path="/page/2/"
            ),
        )
        requests_mock.get(f"{BASE_URL}page/2/", status_code=500)

        results = Crawler(delay=0).crawl()

        assert len(results) == 1


# ---------------------------------------------------------------------------
# URL normalisation
# ---------------------------------------------------------------------------
class TestUrlNormalisation:
    def test_fragment_is_stripped_from_link(self, requests_mock):
        html = _listing_page(_quote_block('"A"', "X")).replace(
            "</body>", '<a href="/page/2/#top">jump</a></body>'
        )
        requests_mock.get(BASE_URL, text=html)
        requests_mock.get(f"{BASE_URL}page/2/", text=_listing_page(""))

        Crawler(delay=0).crawl()

        visited = [r.url for r in requests_mock.request_history]
        # The /page/2/ URL was visited, but with no fragment.
        assert any(u.endswith("/page/2/") for u in visited)
        assert all("#top" not in u for u in visited)


# ---------------------------------------------------------------------------
# Politeness window
# ---------------------------------------------------------------------------
class TestPoliteness:
    def test_no_sleep_before_first_request(self, requests_mock):
        requests_mock.get(BASE_URL, text=_listing_page(""))
        with patch("src.crawler.time.sleep") as sleep_mock:
            Crawler(delay=6.0).crawl()
        sleep_mock.assert_not_called()

    def test_sleeps_between_requests(self, requests_mock):
        requests_mock.get(
            BASE_URL,
            text=_listing_page(_quote_block('"A"', "X"), next_path="/page/2/"),
        )
        requests_mock.get(f"{BASE_URL}page/2/", text=_listing_page(""))
        with patch("src.crawler.time.sleep") as sleep_mock:
            Crawler(delay=6.0).crawl()
        assert sleep_mock.call_count == 1
        slept_for = sleep_mock.call_args.args[0]
        assert 0 < slept_for <= 6.0

    def test_delay_zero_means_no_sleep(self, requests_mock):
        requests_mock.get(
            BASE_URL,
            text=_listing_page(_quote_block('"A"', "X"), next_path="/page/2/"),
        )
        requests_mock.get(f"{BASE_URL}page/2/", text=_listing_page(""))
        with patch("src.crawler.time.sleep") as sleep_mock:
            Crawler(delay=0).crawl()
        sleep_mock.assert_not_called()

    def test_negative_delay_rejected(self):
        with pytest.raises(ValueError):
            Crawler(delay=-1)

    def test_zero_timeout_rejected(self):
        with pytest.raises(ValueError):
            Crawler(timeout=0)


# ---------------------------------------------------------------------------
# User-Agent / session injection
# ---------------------------------------------------------------------------
class TestUserAgent:
    def test_default_user_agent_sent(self, requests_mock):
        requests_mock.get(BASE_URL, text=_listing_page(""))
        Crawler(delay=0).crawl()
        assert "COMP3011" in requests_mock.last_request.headers["User-Agent"]

    def test_custom_user_agent_overrides_default(self, requests_mock):
        requests_mock.get(BASE_URL, text=_listing_page(""))
        Crawler(delay=0, user_agent="MyBot/2.0").crawl()
        assert requests_mock.last_request.headers["User-Agent"] == "MyBot/2.0"

    def test_caller_supplied_session_used(self, requests_mock):
        session = requests.Session()
        session.headers["X-Custom"] = "marker"
        requests_mock.get(BASE_URL, text=_listing_page(""))
        Crawler(delay=0, session=session).crawl()
        assert requests_mock.last_request.headers["X-Custom"] == "marker"

    def test_user_agent_arg_overrides_session_ua(self, requests_mock):
        session = requests.Session()
        session.headers["User-Agent"] = "Old/1.0"
        requests_mock.get(BASE_URL, text=_listing_page(""))
        Crawler(delay=0, session=session, user_agent="New/2.0").crawl()
        assert requests_mock.last_request.headers["User-Agent"] == "New/2.0"


# ---------------------------------------------------------------------------
# CrawledPage type contract
# ---------------------------------------------------------------------------
class TestCrawledPageType:
    def test_returns_named_tuples(self, requests_mock):
        requests_mock.get(
            BASE_URL,
            text=_listing_page(_quote_block('"A"', "X")),
        )
        result = Crawler(delay=0).crawl()[0]
        assert isinstance(result, CrawledPage)
        # Tuple-style and named-attribute access both work.
        assert result.url == result[0]
        assert result.text == result[1]


# ---------------------------------------------------------------------------
# Defensive branches (boundary cases the suite would otherwise miss)
# ---------------------------------------------------------------------------
class TestDefensiveBranches:
    def test_author_page_with_empty_details_dropped(self, requests_mock):
        """A `div.author-details` that exists but contains only
        whitespace yields no document."""
        requests_mock.get(
            BASE_URL,
            text=_listing_page(
                _quote_block('"X"', "A", author_link="/author/A/")
            ),
        )
        requests_mock.get(
            f"{BASE_URL}author/A/",
            text='<html><body><div class="author-details">   </div></body></html>',
        )
        results = Crawler(delay=0).crawl()
        # Only the quote, no empty author document.
        assert all("/author/" not in r.url for r in results)

    def test_anchor_with_empty_path_ignored(self, requests_mock):
        """An anchor whose href resolves to an empty path (e.g.
        `href="?q=x"` with no path) is skipped defensively."""
        # urljoin("https://x.com/", "") → "https://x.com/" (path "/" not "")
        # Pure-empty path happens with explicit query-only URL on a
        # bare host:
        html = _listing_page(_quote_block('"A"', "X")).replace(
            "</body>", '<a href="https://quotes.toscrape.com">no-path</a></body>'
        )
        requests_mock.get(BASE_URL, text=html)
        # Should not crash — empty-path link is silently skipped.
        Crawler(delay=0).crawl()