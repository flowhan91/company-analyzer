from __future__ import annotations

import pytest

from company_analyzer.db import repository as repo
from company_analyzer.db.connection import DBConnection
from company_analyzer.jd_matching.embed_evidence import backfill_evidence_embeddings
from company_analyzer.jd_matching.matcher import EmptyJDError, NoEmbeddedEvidenceError, match_jd
from company_analyzer.jd_matching.parser import parse_and_store_jd
from company_analyzer.llm.mock_provider import MockLLMProvider
from company_analyzer.models import EventCandidate


def _make_canonical_event_with_evidence(conn, company, *, entity, domain, quote, external_id):
    doc, _ = repo.upsert_document(
        conn, company_id=company.id, source_type="press_release", is_official=True,
        title="t", url=None, published_date="2025-06-01", external_id=external_id,
        raw_text=quote,
    )
    chunks = repo.replace_chunks(
        conn, doc.id, [{"heading": None, "text": quote, "start_offset": 0, "end_offset": len(quote)}]
    )
    candidate = EventCandidate(
        event_type="product_launch", subject="NAVER", action="launched", event_date="2025-06-01",
        date_precision="day", lifecycle_status="completed", domain=domain, entity=entity, raw_quote=quote,
    )
    event = repo.insert_event(
        conn, chunk_id=chunks[0].id, candidate=candidate, extraction_model="mock", prompt_version="v1"
    )
    span = repo.upsert_evidence_span(
        conn, event_id=event.id, chunk_id=chunks[0].id, raw_quote=quote, matched_text=quote,
        start_offset=0, end_offset=len(quote), match_score=1.0, match_method="exact",
        is_valid=True, review_status="auto_valid",
    )
    canonical = repo.create_canonical_event(
        conn, company_id=company.id, event_type="product_launch", subject="NAVER", action="launched",
        canonical_date="2025-06-01", date_precision="day", lifecycle_status="completed",
        domain=domain, entity=entity, title=f"{entity}: launched", summary=None, review_status="auto_applied",
    )
    repo.add_cluster_member(conn, canonical_event_id=canonical.id, event_id=event.id, is_seed=True)
    return canonical, span


def test_parse_and_store_jd_dedups_entities_and_skills_and_drops_blank_tasks(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")

    class StubProvider(MockLLMProvider):
        def parse_job_description(self, raw_text: str) -> dict:
            return {
                "role": "Backend Engineer", "role_subtype": "Search", "domain": "search",
                "tasks": ["Build search ranking", "   ", "Operate distributed index"],
                "entities": ["Kubernetes", "kubernetes"],
                "skills": ["Kubernetes", "Python"],
            }

    jd = parse_and_store_jd(conn, company.id, "raw jd text", StubProvider())
    assert jd.role == "Backend Engineer"
    assert jd.domain == "search"
    assert jd.tasks == ["Build search ranking", "Operate distributed index"]
    assert jd.entities == ["Kubernetes", "Python"]


def test_backfill_evidence_embeddings_is_idempotent(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")
    _make_canonical_event_with_evidence(
        conn, company, entity="HyperCLOVA X", domain="AI",
        quote="NAVER launched HyperCLOVA X search today.", external_id="ext-1",
    )
    provider = MockLLMProvider()
    first = backfill_evidence_embeddings(conn, company.id, provider)
    second = backfill_evidence_embeddings(conn, company.id, provider)
    assert first == 1
    assert second == 0

    span = repo.get_evidence_for_event(
        conn, repo.list_events_for_company(conn, company.id)[0].id
    )
    assert span.embedding is not None
    assert len(span.embedding) == 32


def test_match_jd_raises_when_jd_has_no_tasks(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")

    class NoTaskProvider(MockLLMProvider):
        def parse_job_description(self, raw_text: str) -> dict:
            return {"role": None, "role_subtype": None, "domain": None, "tasks": [], "entities": [], "skills": []}

    provider = NoTaskProvider()
    jd = parse_and_store_jd(conn, company.id, "raw jd", provider)
    with pytest.raises(EmptyJDError):
        match_jd(conn, company.id, jd, provider)


def test_match_jd_raises_when_no_embeddings_exist(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")
    _make_canonical_event_with_evidence(
        conn, company, entity="HyperCLOVA X", domain="AI",
        quote="NAVER launched HyperCLOVA X search today.", external_id="ext-1",
    )
    provider = MockLLMProvider()
    jd = parse_and_store_jd(conn, company.id, "We build search ranking systems.", provider)
    with pytest.raises(NoEmbeddedEvidenceError):
        match_jd(conn, company.id, jd, provider)


def test_match_jd_ranks_topically_relevant_event_higher(conn: DBConnection):
    """The core product bar from the spec: the same company data, scored
    against different JDs, should surface different top results depending
    on what the JD actually asks for."""
    company = repo.get_or_create_company(conn, "NAVER")
    search_quote = "NAVER operates a distributed search ranking and indexing platform for web search."
    commerce_quote = "NAVER Pay expanded checkout and payment settlement services for online sellers."
    search_event, _ = _make_canonical_event_with_evidence(
        conn, company, entity="Search Ranking", domain="search", quote=search_quote, external_id="ext-search",
    )
    commerce_event, _ = _make_canonical_event_with_evidence(
        conn, company, entity="Commerce Payments", domain="commerce", quote=commerce_quote,
        external_id="ext-commerce",
    )
    provider = MockLLMProvider()
    embedded = backfill_evidence_embeddings(conn, company.id, provider)
    assert embedded == 2

    class SearchJDProvider(MockLLMProvider):
        def parse_job_description(self, raw_text: str) -> dict:
            return {
                "role": "Search Engineer", "role_subtype": None, "domain": "search",
                "tasks": [search_quote], "entities": [], "skills": [],
            }

    jd_provider = SearchJDProvider()
    jd = parse_and_store_jd(conn, company.id, "raw jd", jd_provider)

    candidates = match_jd(conn, company.id, jd, jd_provider, top_n=2)
    by_id = {c.id: c for c in candidates}
    assert candidates[0].kind == "event"
    assert candidates[0].id == search_event.id
    assert by_id[search_event.id].score > by_id[commerce_event.id].score
