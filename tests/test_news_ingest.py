from __future__ import annotations

import responses

from company_analyzer.config import Settings
from company_analyzer.db import repository as repo
from company_analyzer.db.connection import DBConnection
from company_analyzer.ingestion.news_ingest import NoCanonicalEventsError, ingest_news


def _make_canonical_event(conn: DBConnection, company_id: int, entity: str) -> None:
    repo.create_canonical_event(
        conn, company_id=company_id, event_type="product_launch", subject="NAVER",
        action="launch", canonical_date="2025-06-01", date_precision="day",
        lifecycle_status="completed", domain="search", entity=entity,
        title=f"{entity}: launch", summary=None, review_status="auto_applied",
    )


@responses.activate
def test_ingest_news_queries_per_entity_and_stores_as_non_official(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")
    _make_canonical_event(conn, company.id, "HyperCLOVA X")

    responses.add(
        responses.GET, "https://openapi.naver.com/v1/search/news.json",
        json={
            "items": [
                {
                    "title": "<b>NAVER</b> launches new AI search",
                    "link": "https://news.example.com/1",
                    "description": "NAVER rolled out a new AI-powered search experience.",
                    "pubDate": "Mon, 01 Jun 2025 09:00:00 +0900",
                },
            ]
        },
        status=200,
    )

    settings = Settings(naver_client_id="id", naver_client_secret="secret")
    summary = ingest_news(conn, settings, "NAVER")

    assert summary["queries"] == ["NAVER HyperCLOVA X"]
    assert summary["ingested"] == 1
    assert summary["failed"] == []

    docs = repo.list_documents(conn, company.id, source_type="news")
    assert len(docs) == 1
    assert docs[0].is_official is False
    assert docs[0].title == "NAVER launches new AI search"
    assert docs[0].published_date == "2025-06-01"


@responses.activate
def test_ingest_news_dedupes_across_entity_queries(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")
    _make_canonical_event(conn, company.id, "HyperCLOVA X")
    _make_canonical_event(conn, company.id, "AI Search")

    article = {
        "title": "NAVER news",
        "link": "https://news.example.com/dup",
        "description": "Some description text about NAVER long enough to pass filters.",
        "pubDate": "Mon, 01 Jun 2025 09:00:00 +0900",
    }
    responses.add(
        responses.GET, "https://openapi.naver.com/v1/search/news.json",
        json={"items": [article]}, status=200,
    )
    responses.add(
        responses.GET, "https://openapi.naver.com/v1/search/news.json",
        json={"items": [article]}, status=200,
    )

    settings = Settings(naver_client_id="id", naver_client_secret="secret")
    summary = ingest_news(conn, settings, "NAVER")

    assert summary["queries"] == ["NAVER AI Search", "NAVER HyperCLOVA X"]
    assert summary["ingested"] == 1
    docs = repo.list_documents(conn, company.id, source_type="news")
    assert len(docs) == 1


def test_ingest_news_requires_canonical_events_first(conn: DBConnection):
    repo.get_or_create_company(conn, "NAVER")
    settings = Settings(naver_client_id="id", naver_client_secret="secret")
    try:
        ingest_news(conn, settings, "NAVER")
        assert False, "expected NoCanonicalEventsError"
    except NoCanonicalEventsError as exc:
        assert "cluster-events" in str(exc)


def test_ingest_news_requires_client_credentials(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")
    _make_canonical_event(conn, company.id, "HyperCLOVA X")
    settings = Settings(naver_client_id=None, naver_client_secret=None)
    try:
        ingest_news(conn, settings, "NAVER")
        assert False, "expected ConfigError"
    except Exception as exc:
        assert "NAVER_CLIENT_ID" in str(exc)
