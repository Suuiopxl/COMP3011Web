"""
Crawler module
==============

BFS web crawler for ``quotes.toscrape.com``.

Design decisions (defend these in the video)
--------------------------------------------

1. **Pagination only.**
   We follow the "Next →" link from ``/page/1/`` through ``/page/10/`` and
   nothing else. ``/tag/<x>/`` and ``/author/<x>/`` pages contain quotes
   that *also* appear in the paginated listing, so indexing them would
   inflate term frequencies without adding any new vocabulary. The
   simpler page set is also faster to crawl (10 requests × 6 s ≈ 1 min).

2. **BFS traversal with ``collections.deque``.**
   The standard frontier-queue pattern used by industrial crawlers
   (Scrapy, Heritrix, …). For a linearly-paginated site BFS and DFS are
   indistinguishable, but BFS scales naturally if the page set is
   later expanded and avoids Python's recursion-depth limits.

3. **Visible-text extraction with script/style stripping.**
   The brief asks us to index *all word occurrences in the pages*, so
   we keep navigation and footer text — but we strip ``<script>`` and
   ``<style>`` blocks because their contents are not user-visible and
   would otherwise pollute the index with JavaScript identifiers.

4. **Politeness window injected at construction time.**
   The default is 6.0 s (brief requirement). Tests inject ``delay=0``
   so the suite runs in milliseconds. Crucially, the wait is computed
   as ``delay − elapsed_since_last_request`` rather than a blind
   ``sleep(6)``: if HTML parsing took 1 s we only sleep 5 s, which is
   both polite *and* efficient. The first request is never delayed.

5. **Same-domain link filter.**
   ``urlparse(link).netloc`` is compared against the base host to
   defensively reject any cross-domain links (none exist on
   quotes.toscrape, but the check costs nothing and prevents future
   surprises).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Deque, List, NamedTuple, Optional, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class CrawledPage(NamedTuple):
    """One successfully-crawled page.

    A ``NamedTuple`` keeps the interface tuple-like (so callers can
    ``for url, text in pages: …``) while also allowing
    ``page.url`` / ``page.text`` access for readability.
    """

    url: str
    text: str


class Crawler:
    """BFS web crawler with a configurable politeness window."""

    DEFAULT_BASE_URL = "https://quotes.toscrape.com/"
    DEFAULT_USER_AGENT = (
        "COMP3011-SearchEngine/1.0 (Educational coursework crawler)"
    )

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        delay: float = 6.0,
        timeout: float = 10.0,
        session: Optional[requests.Session] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        if delay < 0:
            raise ValueError(f"delay must be non-negative, got {delay!r}")
        if timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout!r}")

        self.base_url = base_url
        self.delay = float(delay)
        self.timeout = float(timeout)
        # ``requests.Session()`` ships with its own default User-Agent
        # (``python-requests/X.Y.Z``), so ``setdefault`` would be a no-op.
        # We therefore *unconditionally* set our own UA when we create the
        # session, but only override a caller-supplied session if the
        # caller also supplied an explicit ``user_agent`` argument.
        if session is None:
            self.session = requests.Session()
            self.session.headers["User-Agent"] = (
                user_agent or self.DEFAULT_USER_AGENT
            )
        else:
            self.session = session
            if user_agent is not None:
                self.session.headers["User-Agent"] = user_agent
        self._base_netloc = urlparse(base_url).netloc
        self._last_request_time: Optional[float] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def crawl(self) -> List[CrawledPage]:
        """Crawl the site starting from ``base_url``.

        Returns
        -------
        list[CrawledPage]
            Successfully-fetched pages in BFS visit order. Pages that
            return HTTP errors or time out are logged and skipped, so
            the list can be shorter than the number of URLs visited.
        """
        visited: Set[str] = set()
        frontier: Deque[str] = deque([self.base_url])
        results: List[CrawledPage] = []

        while frontier:
            url = frontier.popleft()
            if url in visited:
                continue
            visited.add(url)

            html = self._fetch(url)
            if html is None:
                continue  # Error already logged inside _fetch.

            results.append(CrawledPage(url=url, text=self._extract_text(html)))

            for link in self._extract_links(html, current_url=url):
                if link not in visited:
                    frontier.append(link)

        logger.info("Crawl finished: %d page(s) fetched.", len(results))
        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _wait_politeness(self) -> None:
        """Sleep so that at least ``self.delay`` s has elapsed since the
        previous request. Does nothing before the first request or when
        ``delay == 0``.
        """
        if self.delay == 0 or self._last_request_time is None:
            return
        elapsed = time.monotonic() - self._last_request_time
        remaining = self.delay - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _fetch(self, url: str) -> Optional[str]:
        """GET ``url`` with the politeness delay. Returns HTML on success,
        ``None`` on any network or HTTP error (errors are logged).
        """
        self._wait_politeness()
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            logger.warning("Failed to fetch %s: %s", url, exc)
            return None
        finally:
            # Update timestamp even on failure — we still consumed an HTTP
            # round-trip, so the next request must still respect the delay.
            self._last_request_time = time.monotonic()

    def _extract_text(self, html: str) -> str:
        """Return all visible text from an HTML document."""
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)

    def _extract_links(self, html: str, current_url: str) -> List[str]:
        """Return the absolute URLs of pagination ``<li class="next">`` links."""
        soup = BeautifulSoup(html, "html.parser")
        links: List[str] = []
        for anchor in soup.select("li.next a[href]"):
            absolute = urljoin(current_url, anchor["href"])
            if urlparse(absolute).netloc != self._base_netloc:
                logger.debug("Skipping off-site link: %s", absolute)
                continue
            links.append(absolute)
        return links


# ----------------------------------------------------------------------
# Manual smoke-test entry point: ``python -m src.crawler``
# ----------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    crawler = Crawler()
    pages = crawler.crawl()
    print(f"\nCrawled {len(pages)} page(s):")
    for page in pages:
        print(f"  {page.url}  ({len(page.text)} chars)")