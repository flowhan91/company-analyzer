from __future__ import annotations

from company_analyzer.db.connection import DBConnection
from pathlib import Path

from company_analyzer.chunking.dispatch import get_chunker
from company_analyzer.db import repository as repo
from company_analyzer.evidence.validator import validate_pending_events
from company_analyzer.extraction.extractor import extract_pending_chunks
from company_analyzer.ingestion.manual_loader import ingest_manual_documents
from company_analyzer.llm.mock_provider import MockLLMProvider
from company_analyzer.models import EventCandidate
from company_analyzer.review import actions, audit, queue

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "naver"


def _make_event(conn: DBConnection, company, text: str, entity: str, domain: str, event_date: str) -> repo.Event:
    doc, _ = repo.upsert_document(
        conn, company_id=company.id, source_type="press_release", is_official=True,
        title="t", url=None, published_date=event_date, external_id=f"ext-{text[:10]}-{entity}",
        raw_text=text,
    )
    chunks = repo.replace_chunks(conn, doc.id, [{"heading": None, "text": text, "start_offset": 0, "end_offset": len(text)}])
    candidate = EventCandidate(
        event_type="product_launch", subject="NAVER", action="launch", event_date=event_date,
        date_precision="day", lifecycle_status="completed", domain=domain, entity=entity, raw_quote=text,
    )
    event = repo.insert_event(conn, chunk_id=chunks[0].id, candidate=candidate, extraction_model="mock", prompt_version="v1")
    repo.upsert_evidence_span(
        conn, event_id=event.id, chunk_id=chunks[0].id, raw_quote=text, matched_text=text,
        start_offset=0, end_offset=len(text), match_score=1.0, match_method="exact",
        is_valid=True, review_status="auto_valid",
    )
    return event


def test_approve_event_relationship_merges_events_into_one_canonical_event(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")
    event_a = _make_event(conn, company, "NAVER launched Product X today.", "Product X", "search", "2025-06-01")
    event_b = _make_event(conn, company, "NAVER also launched Product X this week.", "Product X", "search", "2025-06-02")

    relationship = repo.upsert_event_relationship(
        conn, event_a_id=event_a.id, event_b_id=event_b.id, relationship_type="same_event",
        rationale="looks like a duplicate", confidence=0.7, decided_by="llm", review_status="pending",
    )

    pending = queue.pending_event_relationships(conn, relationship_type="same_event")
    assert len(pending) == 1

    canonical = actions.approve_event_relationship(conn, relationship.id, human_id="reviewer1")

    ce_a = repo.get_canonical_event_for_event(conn, event_a.id)
    ce_b = repo.get_canonical_event_for_event(conn, event_b.id)
    assert ce_a is not None and ce_b is not None
    assert ce_a.id == ce_b.id == canonical.id

    refreshed = repo.list_pending_relationships(conn, relationship_type="same_event")
    assert refreshed == []

    entries = audit.list_audit_entries(conn, table_name="event_relationships", record_id=relationship.id)
    assert len(entries) == 1
    assert entries[0]["actor"] == "human:reviewer1"
    assert entries[0]["action"] == "approve"


def test_reject_event_relationship_leaves_events_unclustered(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")
    event_a = _make_event(conn, company, "NAVER launched Product Y today.", "Product Y", "search", "2025-06-01")
    event_b = _make_event(conn, company, "NAVER launched Product Z today.", "Product Z", "commerce", "2025-06-05")

    relationship = repo.upsert_event_relationship(
        conn, event_a_id=event_a.id, event_b_id=event_b.id, relationship_type="same_event",
        rationale="uncertain", confidence=0.65, decided_by="llm", review_status="pending",
    )
    actions.reject_event_relationship(conn, relationship.id, human_id="reviewer1")

    assert repo.get_canonical_event_for_event(conn, event_a.id) is None
    assert repo.get_canonical_event_for_event(conn, event_b.id) is None
    refreshed = repo.list_pending_relationships(conn, relationship_type="same_event")
    assert refreshed == []


def test_approve_canonical_relationship_creates_thread(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")
    ce1 = repo.create_canonical_event(
        conn, company_id=company.id, event_type="strategy_announcement", subject="NAVER", action="announce",
        canonical_date="2025-01-01", date_precision="day", lifecycle_status="planned", domain="search",
        entity="HyperCLOVA X", title="HyperCLOVA X: announce", summary=None, review_status="auto_applied",
    )
    ce2 = repo.create_canonical_event(
        conn, company_id=company.id, event_type="product_launch", subject="NAVER", action="launch",
        canonical_date="2025-06-01", date_precision="day", lifecycle_status="completed", domain="search",
        entity="HyperCLOVA X", title="HyperCLOVA X: launch", summary=None, review_status="auto_applied",
    )
    relationship = repo.upsert_canonical_event_relationship(
        conn, canonical_event_a_id=ce1.id, canonical_event_b_id=ce2.id, relationship_type="related_distinct",
        rationale="same initiative", confidence=0.7, decided_by="llm", review_status="pending",
    )

    thread = actions.approve_canonical_relationship(conn, relationship.id, human_id="reviewer1")
    thread_events = repo.list_thread_events(conn, thread.id)
    assert {te.canonical_event_id for te in thread_events} == {ce1.id, ce2.id}
    assert [te.sequence_index for te in thread_events] == sorted(te.sequence_index for te in thread_events)


def test_evidence_review_approve_and_reject(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")
    doc, _ = repo.upsert_document(
        conn, company_id=company.id, source_type="press_release", is_official=True,
        title="t", url=None, published_date=None, external_id="ext-evidence", raw_text="Some paraphrased content here.",
    )
    chunks = repo.replace_chunks(conn, doc.id, [{"heading": None, "text": doc.raw_text, "start_offset": 0, "end_offset": len(doc.raw_text)}])
    candidate = EventCandidate(
        event_type="x", subject=None, action=None, event_date=None, date_precision="unknown",
        lifecycle_status="unknown", domain=None, entity=None, raw_quote="Some paraphrased content here.",
    )
    event = repo.insert_event(conn, chunk_id=chunks[0].id, candidate=candidate, extraction_model="mock", prompt_version="v1")
    span = repo.upsert_evidence_span(
        conn, event_id=event.id, chunk_id=chunks[0].id, raw_quote=candidate.raw_quote, matched_text="Some content here",
        start_offset=0, end_offset=17, match_score=0.7, match_method="fuzzy_rapidfuzz",
        is_valid=False, review_status="pending",
    )

    pending = queue.pending_evidence(conn, company.id)
    assert len(pending) == 1

    approved = actions.approve_evidence(conn, span.id, human_id="reviewer1")
    assert approved.is_valid is True
    assert approved.review_status == "approved"

    rejected = actions.reject_evidence(conn, span.id, human_id="reviewer1")
    assert rejected.is_valid is False
    assert rejected.review_status == "rejected"

    entries = audit.list_audit_entries(conn, table_name="evidence_spans", record_id=span.id)
    assert len(entries) == 2
