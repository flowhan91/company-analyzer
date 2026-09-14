from __future__ import annotations

from company_analyzer.db.connection import DBConnection

from company_analyzer.clustering.build_canonical_events import cluster_new_events
from company_analyzer.db import repository as repo
from company_analyzer.llm.mock_provider import MockLLMProvider
from company_analyzer.models import EventCandidate


def _make_event(
    conn: DBConnection, company, *, source_type: str, is_official: bool,
    text: str, entity: str, domain: str, event_type: str, event_date: str, external_id: str,
) -> repo.Event:
    doc, _ = repo.upsert_document(
        conn, company_id=company.id, source_type=source_type, is_official=is_official,
        title="t", url=None, published_date=event_date, external_id=external_id, raw_text=text,
    )
    chunks = repo.replace_chunks(conn, doc.id, [{"heading": None, "text": text, "start_offset": 0, "end_offset": len(text)}])
    candidate = EventCandidate(
        event_type=event_type, subject="NAVER", action=event_type, event_date=event_date,
        date_precision="day", lifecycle_status="completed", domain=domain, entity=entity, raw_quote=text,
    )
    event = repo.insert_event(conn, chunk_id=chunks[0].id, candidate=candidate, extraction_model="mock", prompt_version="v1")
    repo.upsert_evidence_span(
        conn, event_id=event.id, chunk_id=chunks[0].id, raw_quote=text, matched_text=text,
        start_offset=0, end_offset=len(text), match_score=1.0, match_method="exact",
        is_valid=True, review_status="auto_valid",
    )
    return event


def test_duplicate_events_from_different_official_documents_merge(conn: DBConnection):
    provider = MockLLMProvider()
    company = repo.get_or_create_company(conn, "NAVER")
    _make_event(
        conn, company, source_type="press_release", is_official=True,
        text="NAVER launched Product X today.", entity="Product X", domain="search",
        event_type="product_launch", event_date="2025-06-01", external_id="a",
    )
    _make_event(
        conn, company, source_type="tech_blog", is_official=True,
        text="NAVER also launched Product X this week.", entity="Product X", domain="search",
        event_type="product_launch", event_date="2025-06-02", external_id="b",
    )

    counts = cluster_new_events(conn, company.id, provider)
    assert counts["merged"] == 1
    assert counts["new_canonical"] == 1

    timeline_events = repo.list_canonical_events(conn, company.id)
    assert len(timeline_events) == 1


def test_unrelated_events_do_not_merge(conn: DBConnection):
    provider = MockLLMProvider()
    company = repo.get_or_create_company(conn, "NAVER")
    _make_event(
        conn, company, source_type="press_release", is_official=True,
        text="NAVER launched Product X today.", entity="Product X", domain="search",
        event_type="product_launch", event_date="2025-06-01", external_id="a",
    )
    _make_event(
        conn, company, source_type="press_release", is_official=True,
        text="NAVER opened a new logistics center.", entity="Logistics Center", domain="commerce",
        event_type="expansion", event_date="2025-09-01", external_id="b",
    )

    counts = cluster_new_events(conn, company.id, provider)
    assert counts["merged"] == 0
    assert counts["new_canonical"] == 2


def test_news_event_never_seeds_a_new_canonical_event(conn: DBConnection):
    provider = MockLLMProvider()
    company = repo.get_or_create_company(conn, "NAVER")
    _make_event(
        conn, company, source_type="news", is_official=False,
        text="NAVER reportedly launched Product X.", entity="Product X", domain="search",
        event_type="product_launch", event_date="2025-06-01", external_id="news-a",
    )

    counts = cluster_new_events(conn, company.id, provider)
    assert counts["new_canonical"] == 0
    assert counts["deferred_news_event"] == 1
    assert repo.list_canonical_events(conn, company.id) == []


def test_news_event_can_join_an_existing_official_canonical_event(conn: DBConnection):
    provider = MockLLMProvider()
    company = repo.get_or_create_company(conn, "NAVER")
    _make_event(
        conn, company, source_type="press_release", is_official=True,
        text="NAVER launched Product X today.", entity="Product X", domain="search",
        event_type="product_launch", event_date="2025-06-01", external_id="official-a",
    )
    cluster_new_events(conn, company.id, provider)
    assert len(repo.list_canonical_events(conn, company.id)) == 1

    _make_event(
        conn, company, source_type="news", is_official=False,
        text="NAVER reportedly launched Product X.", entity="Product X", domain="search",
        event_type="product_launch", event_date="2025-06-02", external_id="news-b",
    )
    counts = cluster_new_events(conn, company.id, provider)
    assert counts["merged"] == 1
    assert len(repo.list_canonical_events(conn, company.id)) == 1
