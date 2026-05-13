"""
Crawler module
==============

BFS web crawler for ``quotes.toscrape.com``. Walks every linked page
in the site (pagination, tag listings, author detail pages) and emits
**one ``CrawledPage`` per unique piece of content**:

* one entry per unique *quote* (deduplicated by quote text + author),
* one entry per *author detail page* (biographical text).

The "indexable document" is therefore a single quote or a single
author biography — not an HTML page. This matters because the same
quote appears on multiple HTML pages (the home listing, several tag
listings, and so on); without deduplication its term frequencies
would be inflated and the search results would be useless.

"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Deque, List, NamedTuple, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class CrawledPage(NamedTuple):
    """One indexable document.

    ``url`` is unique across the returned list and identifies the
    document in the inverted index. ``text`` is the document's
    indexable content — already stripped of site-wide chrome.
    """

    url: str
    text: str


class Crawler:
    """BFS web crawler with quote-level deduplication."""

    DEFAULT_BASE_URL = "https://quotes.toscrape.com/"
    DEFAULT_USER_AGENT = (
        "COMP3011-SearchEngine/1.0 (Educational coursework crawler)"
    )

    # Paths we never follow even if linked.
    SKIPPED_PATH_PREFIXES = ("/login", "/logout", "/static/")

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
        """Crawl the site and return one document per unique quote
        plus one document per author detail page.

        Returns
        -------
        list[CrawledPage]
            BFS-visit order. Empty if the network is unreachable.
        """
        visited_urls: Set[str] = set()
        frontier: Deque[str] = deque([self._normalise(self.base_url)])
        seen_quote_keys: Set[Tuple[str, str]] = set()
        results: List[CrawledPage] = []

        while frontier:
            url = frontier.popleft()
            if url in visited_urls:  # pragma: no cover -- belt-and-braces; the
                # `not in visited_urls` check at enqueue time normally already
                # prevents duplicates from reaching the frontier.
                continue
            visited_urls.add(url)

            html = self._fetch(url)
            if html is None:
                continue  # Error already logged inside _fetch.

            results.extend(self._extract_documents(html, url, seen_quote_keys))

            for link in self._extract_links(html, current_url=url):
                if link not in visited_urls:
                    frontier.append(link)

        logger.info(
            "Crawl finished: %d URL(s) fetched, %d unique document(s) indexed.",
            len(visited_urls),
            len(results),
        )
        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _wait_politeness(self) -> None:
        """Sleep so at least ``self.delay`` s has elapsed since the
        previous request.
        """
        if self.delay == 0 or self._last_request_time is None:
            return
        elapsed = time.monotonic() - self._last_request_time
        remaining = self.delay - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _fetch(self, url: str) -> Optional[str]:
        """GET ``url`` with the politeness delay. Returns HTML on
        success, ``None`` on any network or HTTP error.
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
            self._last_request_time = time.monotonic()

    def _extract_documents(
        self,
        html: str,
        url: str,
        seen_quote_keys: Set[Tuple[str, str]],
    ) -> List[CrawledPage]:
        """Return zero or more documents extracted from this page.

        - Author detail pages (``/author/...``) yield one document.
        - Listing pages (home, ``/page/N/``, ``/tag/...``) yield one
          document per *previously-unseen* quote block on the page.
        - Anything else yields no documents.
        """
        path = urlparse(url).path
        soup = BeautifulSoup(html, "html.parser")

        if path.startswith("/author/"):
            details = soup.select_one("div.author-details")
            if details is None:
                return []
            text = details.get_text(separator=" ", strip=True)
            if not text:
                return []
            return [CrawledPage(url=url, text=text)]

        # Listing page — extract each quote block, dedup globally.
        docs: List[CrawledPage] = []
        quote_blocks = soup.select("div.quote")
        for i, block in enumerate(quote_blocks):
            text_node = block.select_one("span.text")
            author_node = block.select_one("small.author")
            if text_node is None or author_node is None:
                continue
            quote_text = text_node.get_text(strip=True)
            author = author_node.get_text(strip=True)
            key = (quote_text, author)
            if key in seen_quote_keys:
                continue  # Already indexed from a previous page.
            seen_quote_keys.add(key)
            # Build a stable, page-suffixed URL for this quote so two
            # quotes on the same page get distinct document ids.
            doc_url = f"{url}#quote-{i + 1}"
            doc_text = block.get_text(separator=" ", strip=True)
            docs.append(CrawledPage(url=doc_url, text=doc_text))
        return docs

    def _extract_links(self, html: str, current_url: str) -> List[str]:
        """Return every same-domain link we want to enqueue.

        We follow:
          * ``Next →`` pagination (``li.next a``)
          * tag pages and their pagination (``/tag/...``)
          * author detail pages (``/author/...``)

        We skip ``/login`` and any cross-domain link.
        """
        soup = BeautifulSoup(html, "html.parser")
        links: List[str] = []
        seen_in_page: Set[str] = set()

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            absolute = urljoin(current_url, href)
            parsed = urlparse(absolute)

            if parsed.netloc and parsed.netloc != self._base_netloc:
                continue

            normalised = self._normalise(absolute)
            path = urlparse(normalised).path
            if any(path.startswith(p) for p in self.SKIPPED_PATH_PREFIXES):
                continue
            if not path:
                continue

            if normalised in seen_in_page:
                continue
            seen_in_page.add(normalised)
            links.append(normalised)

        return links

    @staticmethod
    def _normalise(url: str) -> str:
        """Strip the fragment from a URL so anchor variants don't
        produce duplicate entries in the visited set.
        """
        parsed = urlparse(url)
        return urlunparse(parsed._replace(fragment=""))


# ----------------------------------------------------------------------
# Manual smoke-test: ``python -m src.crawler``
# ----------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    crawler = Crawler()
    docs = crawler.crawl()
    print(f"\nIndexed {len(docs)} document(s).")
    for doc in docs[:5]:
        print(f"  {doc.url}  ({len(doc.text)} chars)")
    if len(docs) > 5:
        print(f"  ... and {len(docs) - 5} more")