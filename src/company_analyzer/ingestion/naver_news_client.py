from __future__ import annotations

import re
from dataclasses import dataclass

import requests

NEWS_SEARCH_URL = "https://openapi.naver.com/v1/search/news.json"
MAX_RESULTS_PER_PAGE = 100
MAX_START = 1000  # Naver Search API's documented cap


class NaverApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class NewsArticle:
    title: str
    link: str
    description: str
    pub_date: str  # RFC 2822 as returned by the API


def _strip_html_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def search_news(
    client_id: str,
    client_secret: str,
    query: str,
    max_results: int = 100,
    session: requests.Session | None = None,
) -> list[NewsArticle]:
    session = session or requests
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    articles: list[NewsArticle] = []
    start = 1
    while len(articles) < max_results and start <= MAX_START:
        display = min(MAX_RESULTS_PER_PAGE, max_results - len(articles))
        resp = session.get(
            NEWS_SEARCH_URL,
            headers=headers,
            params={"query": query, "display": display, "start": start, "sort": "date"},
            timeout=30,
        )
        if resp.status_code != 200:
            raise NaverApiError(f"Naver News API returned {resp.status_code}: {resp.text[:200]}")
        payload = resp.json()
        items = payload.get("items", [])
        if not items:
            break
        for item in items:
            articles.append(
                NewsArticle(
                    title=_strip_html_tags(item["title"]),
                    link=item["link"],
                    description=_strip_html_tags(item.get("description", "")),
                    pub_date=item.get("pubDate", ""),
                )
            )
        start += display
    return articles
