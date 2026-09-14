from __future__ import annotations

from email.utils import parsedate_to_datetime

from company_analyzer.config import Settings
from company_analyzer.db import repository as repo
from company_analyzer.db.connection import DBConnection
from company_analyzer.ingestion.naver_news_client import NaverApiError, search_news


def _to_iso_date(rfc2822_date: str) -> str | None:
    if not rfc2822_date:
        return None
    try:
        return parsedate_to_datetime(rfc2822_date).date().isoformat()
    except (ValueError, TypeError):
        return None


class NoCanonicalEventsError(RuntimeError):
    pass


def ingest_news(conn: DBConnection, settings: Settings, company_name: str, max_results: int = 100) -> dict:
    """Fetch news for entities already established from official sources.

    Deliberately NOT a blind "company name" search: a generic query for a
    large company returns mostly unrelated noise and can still miss coverage
    of a specific initiative. Instead this queries "<company> <entity>" for
    every distinct entity seen in the company's canonical_events - so it
    only runs meaningfully *after* official-source ingestion + clustering
    have already established what those entities are.

    Stored as is_official=False - context enrichment only. Downstream,
    news-sourced events may join an existing cluster but can never seed one.
    """
    client_id, client_secret = settings.require_naver_keys()
    company = repo.get_or_create_company(conn, company_name)

    canonical_events = repo.list_canonical_events(conn, company.id)
    entities = sorted({ce.entity for ce in canonical_events if ce.entity})
    if not entities:
        raise NoCanonicalEventsError(
            f"No canonical events with an entity exist yet for '{company_name}'. "
            "Run official-source ingestion (ingest-manual / ingest-dart) and "
            "cluster-events first, then re-run ingest-news."
        )

    queries = [f"{company_name} {entity}" for entity in entities]

    ingested, unchanged, failed = 0, 0, []
    seen_links: set[str] = set()

    for query in queries:
        try:
            articles = search_news(client_id, client_secret, query, max_results=max_results)
        except NaverApiError as exc:
            failed.append((query, str(exc)))
            repo.log_ingestion(
                conn, source="news", company_id=company.id, status="failed",
                detail=query, error_message=str(exc),
            )
            continue

        for article in articles:
            if article.link in seen_links:
                continue
            seen_links.add(article.link)
            if not article.description:
                continue
            _document, changed = repo.upsert_document(
                conn, company_id=company.id, source_type="news", is_official=False,
                title=article.title, url=article.link,
                published_date=_to_iso_date(article.pub_date),
                external_id=article.link, raw_text=article.description,
                metadata={"query": query},
            )
            if changed:
                ingested += 1
            else:
                unchanged += 1
        repo.log_ingestion(conn, source="news", company_id=company.id, status="success", detail=query)

    return {"ingested": ingested, "unchanged": unchanged, "failed": failed, "queries": queries}
