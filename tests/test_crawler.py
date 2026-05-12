"""
Unit tests for ``src.crawler``.

Testing strategy
----------------
* Every test uses the ``requests_mock`` fixture so **no real network
  traffic is ever sent** during the test suite. This keeps tests fast,
  deterministic, and polite to the live site.
* Tests are grouped by behaviour: traversal, text extraction, error
  handling, deduplication, politeness, User-Agent, and link filtering.
* ``time.sleep`` is patched out wherever we assert on politeness so the
  suite finishes in milliseconds even for ``delay=6``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from src.crawler import CrawledPage, Crawler

BASE_URL = "https://quotes.toscrape.com/"

PAGE_1_HTML = """
<html><body>
  <h1>Quotes to Scrape</h1>
  <div class="quote">
    <span class="text">"The world as we have created it is a process of our thinking."</span>
    <span>by <small class="author">Albert Einstein</small></span>
  </div>
  <ul class="pager">
    <li class="next"><a href="/page/2/">Next &rarr;</a></li>
  </ul>
  <script>console.log('should be stripped');</script>
</body></html>
"""

PAGE_2_HTML = """
<html><body>
  <div class="quote">
    <span class="text">"Try not to become a man of success."</span>
    <span>by <small class="author">Albert Einstein</small></span>
  </div>
  <!-- no "Next" link: this is the last page -->
</body></html>
"""


# ---------------------------------------------------------------------------
# Traversal
# ---------------------------------------------------------------------------
class TestCrawlerBasics:
    def test_single_page_when_no_next_link(self, requests_mock):
        requests_mock.get(BASE_URL, text=PAGE_2_HTML)
        results = Crawler(delay=0).crawl()
        assert len(results) == 1
        assert results[0].url == BASE_URL

    def test_follows_next_link_to_second_page(self, requests_mock):
        requests_mock.get(BASE_URL, text=PAGE_1_HTML)
        requests_mock.get(f"{BASE_URL}page/2/", text=PAGE_2_HTML)
        results = Crawler(delay=0).crawl()
        assert [p.url for p in results] == [BASE_URL, f"{BASE_URL}page/2/"]

    def test_returns_named_tuples(self, requests_mock):
        requests_mock.get(BASE_URL, text=PAGE_2_HTML)
        result = Crawler(delay=0).crawl()[0]
        assert isinstance(result, CrawledPage)
        assert result.url == result[0]  # tuple-style access still works
        assert result.text == result[1]


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------
class TestTextExtraction:
    def test_strips_script_content(self, requests_mock):
        requests_mock.get(BASE_URL, text=PAGE_1_HTML)
        requests_mock.get(f"{BASE_URL}page/2/", text="<html></html>")
        text = Crawler(delay=0).crawl()[0].text
        assert "console.log" not in text
        assert "should be stripped" not in text

    def test_strips_style_content(self, requests_mock):
        html = "<html><body><style>body{color:red}</style><p>Hello</p></body></html>"
        requests_mock.get(BASE_URL, text=html)
        text = Crawler(delay=0).crawl()[0].text
        assert "color:red" not in text
        assert "Hello" in text

    def test_includes_visible_navigation_text(self, requests_mock):
        # Brief: index *all* word occurrences, including navigation.
        requests_mock.get(BASE_URL, text=PAGE_1_HTML)
        requests_mock.get(f"{BASE_URL}page/2/", text="<html></html>")
        text = Crawler(delay=0).crawl()[0].text
        assert "Quotes to Scrape" in text
        assert "Albert Einstein" in text

    def test_handles_empty_html(self, requests_mock):
        requests_mock.get(BASE_URL, text="<html></html>")
        results = Crawler(delay=0).crawl()
        assert len(results) == 1
        assert results[0].text == ""


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
class TestErrorHandling:
    def test_404_returns_no_pages(self, requests_mock):
        requests_mock.get(BASE_URL, status_code=404)
        assert Crawler(delay=0).crawl() == []

    def test_500_returns_no_pages(self, requests_mock):
        requests_mock.get(BASE_URL, status_code=500)
        assert Crawler(delay=0).crawl() == []

    def test_connection_error_handled_gracefully(self, requests_mock):
        requests_mock.get(BASE_URL, exc=requests.ConnectionError)
        assert Crawler(delay=0).crawl() == []

    def test_timeout_handled_gracefully(self, requests_mock):
        requests_mock.get(BASE_URL, exc=requests.Timeout)
        assert Crawler(delay=0).crawl() == []

    def test_failure_on_later_page_keeps_earlier_pages(self, requests_mock):
        requests_mock.get(BASE_URL, text=PAGE_1_HTML)
        requests_mock.get(f"{BASE_URL}page/2/", status_code=500)
        results = Crawler(delay=0).crawl()
        assert len(results) == 1
        assert results[0].url == BASE_URL


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------
class TestDeduplication:
    def test_does_not_recrawl_same_url(self, requests_mock):
        # Construct a synthetic page 2 that links back to the root.
        page_2_with_backlink = """
        <html><body><p>second page</p>
          <ul class="pager">
            <li class="next"><a href="/">Back to start</a></li>
          </ul>
        </body></html>
        """
        requests_mock.get(BASE_URL, text=PAGE_1_HTML)
        requests_mock.get(f"{BASE_URL}page/2/", text=page_2_with_backlink)
        results = Crawler(delay=0).crawl()
        # Without the visited-set, this would loop forever.
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Politeness window
# ---------------------------------------------------------------------------
class TestPoliteness:
    def test_no_sleep_before_first_request(self, requests_mock):
        requests_mock.get(BASE_URL, text=PAGE_2_HTML)
        with patch("src.crawler.time.sleep") as sleep_mock:
            Crawler(delay=6.0).crawl()
        sleep_mock.assert_not_called()

    def test_sleeps_between_requests(self, requests_mock):
        requests_mock.get(BASE_URL, text=PAGE_1_HTML)
        requests_mock.get(f"{BASE_URL}page/2/", text=PAGE_2_HTML)
        with patch("src.crawler.time.sleep") as sleep_mock:
            Crawler(delay=6.0).crawl()
        assert sleep_mock.call_count == 1
        slept_for = sleep_mock.call_args.args[0]
        # Must be positive (we did sleep) and at most the configured delay.
        assert 0 < slept_for <= 6.0

    def test_delay_zero_means_no_sleep(self, requests_mock):
        requests_mock.get(BASE_URL, text=PAGE_1_HTML)
        requests_mock.get(f"{BASE_URL}page/2/", text=PAGE_2_HTML)
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
# User-Agent
# ---------------------------------------------------------------------------
class TestUserAgent:
    def test_default_user_agent_sent(self, requests_mock):
        requests_mock.get(BASE_URL, text=PAGE_2_HTML)
        Crawler(delay=0).crawl()
        assert "COMP3011" in requests_mock.last_request.headers["User-Agent"]

    def test_custom_user_agent_overrides_default(self, requests_mock):
        requests_mock.get(BASE_URL, text=PAGE_2_HTML)
        Crawler(delay=0, user_agent="MyBot/2.0").crawl()
        assert requests_mock.last_request.headers["User-Agent"] == "MyBot/2.0"


# ---------------------------------------------------------------------------
# Same-domain link filter
# ---------------------------------------------------------------------------
class TestLinkFiltering:
    def test_ignores_links_to_other_domains(self, requests_mock):
        html_with_external = """
        <html><body><p>page</p>
          <ul class="pager">
            <li class="next"><a href="https://evil.com/page/2/">Next</a></li>
          </ul>
        </body></html>
        """
        requests_mock.get(BASE_URL, text=html_with_external)
        results = Crawler(delay=0).crawl()
        assert len(results) == 1  # External link was filtered out.

    def test_only_pagination_next_links_followed(self, requests_mock):
        # Page contains a tag link and an author link; neither should be followed.
        html = """
        <html><body>
          <a href="/tag/love/">love</a>
          <a href="/author/einstein/">Einstein</a>
          <p>no next link here</p>
        </body></html>
        """
        requests_mock.get(BASE_URL, text=html)
        results = Crawler(delay=0).crawl()
        assert len(results) == 1
        assert results[0].url == BASE_URL


# ---------------------------------------------------------------------------
# Session injection (dependency-injection friendliness)
# ---------------------------------------------------------------------------
class TestSessionInjection:
    def test_accepts_caller_supplied_session(self, requests_mock):
        """A caller can inject a pre-configured Session (e.g. with proxies
        or custom headers). Headers set on that session are preserved
        unless the caller also passes ``user_agent``."""
        session = requests.Session()
        session.headers["X-Custom"] = "marker"
        requests_mock.get(BASE_URL, text="<html></html>")
        Crawler(delay=0, session=session).crawl()
        assert requests_mock.last_request.headers["X-Custom"] == "marker"

    def test_user_agent_arg_overrides_session_ua(self, requests_mock):
        session = requests.Session()
        session.headers["User-Agent"] = "OldAgent/1.0"
        requests_mock.get(BASE_URL, text="<html></html>")
        Crawler(delay=0, session=session, user_agent="NewAgent/2.0").crawl()
        assert requests_mock.last_request.headers["User-Agent"] == "NewAgent/2.0"


# ---------------------------------------------------------------------------
# Defensive BFS: visited-check at pop time
# ---------------------------------------------------------------------------
class TestPopTimeDeduplication:
    def test_duplicate_next_links_still_crawled_once(self, requests_mock):
        """If a single page accidentally contains the same Next-link
        twice, BFS must still visit the target exactly once. This
        exercises the visited-check at the pop step (defensive)."""
        html_with_duplicate_next = """
        <html><body>
          <ul class="pager"><li class="next"><a href="/page/2/">first</a></li></ul>
          <ul class="pager"><li class="next"><a href="/page/2/">again</a></li></ul>
        </body></html>
        """
        requests_mock.get(BASE_URL, text=html_with_duplicate_next)
        requests_mock.get(f"{BASE_URL}page/2/", text="<html></html>")
        results = Crawler(delay=0).crawl()
        page2_visits = sum(1 for p in results if p.url == f"{BASE_URL}page/2/")
        assert page2_visits == 1