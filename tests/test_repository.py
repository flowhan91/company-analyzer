from __future__ import annotations

from company_analyzer.db.connection import DBConnection

from company_analyzer.db import repository as repo
from company_analyzer.models import EventCandidate


def test_get_or_create_company_is_idempotent(conn: DBConnection):
    c1 = repo.get_or_create_company(conn, "NAVER", aliases=["네이버"])
    c2 = repo.get_or_create_company(conn, "NAVER")
    assert c1.id == c2.id
    assert c2.aliases == ["네이버"]


def test_upsert_document_versions_on_content_change(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")
    doc1, changed1 = repo.upsert_document(
        conn, company_id=company.id, source_type="press_release", is_official=True,
        title="v1", url=None, published_date="2025-01-01", external_id="ext-1",
        raw_text="Original text.",
    )
    assert changed1 is True
    assert doc1.version == 1

    doc2, changed2 = repo.upsert_document(
        conn, company_id=company.id, source_type="press_release", is_official=True,
        title="v1", url=None, published_date="2025-01-01", external_id="ext-1",
        raw_text="Original text.",
    )
    assert changed2 is False
    assert doc2.version == 1

    doc3, changed3 = repo.upsert_document(
        conn, company_id=company.id, source_type="press_release", is_official=True,
        title="v1 updated", url=None, published_date="2025-01-02", external_id="ext-1",
        raw_text="Changed text.",
    )
    assert changed3 is True
    assert doc3.version == 2
    assert doc3.id == doc1.id

    snapshots = repo.list_document_snapshots(conn, doc1.id)
    assert [s.version for s in snapshots] == [1, 2]
    assert snapshots[0].raw_text == "Original text."
    assert snapshots[1].raw_text == "Changed text."


def test_chunk_offsets_reconstruct_document_text(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")
    raw_text = "Paragraph one.\n\nParagraph two."
    doc, _ = repo.upsert_document(
        conn, company_id=company.id, source_type="press_release", is_official=True,
        title="t", url=None, published_date=None, external_id="ext-2", raw_text=raw_text,
    )
    drafts = [
        {"heading": None, "text": "Paragraph one.", "start_offset": 0, "end_offset": 14},
        {"heading": None, "text": "Paragraph two.", "start_offset": 16, "end_offset": 30},
    ]
    chunks = repo.replace_chunks(conn, doc.id, drafts)
    for chunk in chunks:
        assert raw_text[chunk.start_offset:chunk.end_offset] == chunk.text


def test_event_evidence_and_relationship_flow(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")
    doc, _ = repo.upsert_document(
        conn, company_id=company.id, source_type="press_release", is_official=True,
        title="t", url=None, published_date="2025-06-01", external_id="ext-3",
        raw_text="NAVER launched HyperCLOVA X search today.",
    )
    chunks = repo.replace_chunks(
        conn, doc.id,
        [{"heading": None, "text": doc.raw_text, "start_offset": 0, "end_offset": len(doc.raw_text)}],
    )
    chunk = chunks[0]

    candidate = EventCandidate(
        event_type="product_launch", subject="NAVER", action="launch",
        event_date="2025-06-01", date_precision="day", lifecycle_status="completed",
        domain="search", entity="HyperCLOVA X", raw_quote="NAVER launched HyperCLOVA X search today.",
    )
    event = repo.insert_event(
        conn, chunk_id=chunk.id, candidate=candidate,
        extraction_model="mock", prompt_version="v1",
    )
    assert event.entity == "HyperCLOVA X"

    span = repo.upsert_evidence_span(
        conn, event_id=event.id, chunk_id=chunk.id, raw_quote=candidate.raw_quote,
        matched_text=candidate.raw_quote, start_offset=0, end_offset=len(candidate.raw_quote),
        match_score=1.0, match_method="exact", is_valid=True, review_status="auto_valid",
    )
    assert span.is_valid is True

    canonical = repo.create_canonical_event(
        conn, company_id=company.id, event_type=event.event_type, subject=event.subject,
        action=event.action, canonical_date=event.event_date, date_precision=event.date_precision,
        lifecycle_status=event.lifecycle_status, domain=event.domain, entity=event.entity,
        title="HyperCLOVA X: launch", summary=None, review_status="auto_applied",
    )
    repo.add_cluster_member(conn, canonical_event_id=canonical.id, event_id=event.id, is_seed=True)

    fetched = repo.get_canonical_event_for_event(conn, event.id)
    assert fetched is not None
    assert fetched.id == canonical.id

    thread = repo.create_thread(
        conn, company_id=company.id, title="HyperCLOVA X Expansion",
        domain="search", entity="HyperCLOVA X", review_status="auto_applied",
    )
    repo.add_thread_event(conn, thread_id=thread.id, canonical_event_id=canonical.id, sequence_index=0, stage="launch")

    thread_events = repo.list_thread_events(conn, thread.id)
    assert len(thread_events) == 1
    assert thread_events[0].stage == "launch"

    threads_for_event = repo.list_threads_for_canonical_event(conn, canonical.id)
    assert len(threads_for_event) == 1


def test_bulk_lookup_functions_match_their_per_item_equivalents(conn: DBConnection):
    """The timeline/threads pages used to call the single-item versions of
    these lookups once per row, which was an N+1 query pattern that made the
    pages very slow against a remote (Supabase) connection. The bulk
    versions must return exactly the same information."""
    company = repo.get_or_create_company(conn, "NAVER")

    official_doc, _ = repo.upsert_document(
        conn, company_id=company.id, source_type="press_release", is_official=True,
        title="t", url=None, published_date="2025-06-01", external_id="ext-official",
        raw_text="NAVER launched Product X today.",
    )
    news_doc, _ = repo.upsert_document(
        conn, company_id=company.id, source_type="news", is_official=False,
        title="t", url=None, published_date="2025-06-02", external_id="ext-news",
        raw_text="NAVER reportedly launched Product Y.",
    )
    official_chunks = repo.replace_chunks(
        conn, official_doc.id, [{"heading": None, "text": official_doc.raw_text, "start_offset": 0, "end_offset": len(official_doc.raw_text)}]
    )
    news_chunks = repo.replace_chunks(
        conn, news_doc.id, [{"heading": None, "text": news_doc.raw_text, "start_offset": 0, "end_offset": len(news_doc.raw_text)}]
    )

    candidate = EventCandidate(
        event_type="product_launch", subject="NAVER", action="launch", event_date="2025-06-01",
        date_precision="day", lifecycle_status="completed", domain="search", entity="Product X",
        raw_quote=official_doc.raw_text,
    )
    official_event = repo.insert_event(conn, chunk_id=official_chunks[0].id, candidate=candidate, extraction_model="mock", prompt_version="v1")
    news_event = repo.insert_event(conn, chunk_id=news_chunks[0].id, candidate=candidate, extraction_model="mock", prompt_version="v1")

    ce_official = repo.create_canonical_event(
        conn, company_id=company.id, event_type="product_launch", subject="NAVER", action="launch",
        canonical_date="2025-06-01", date_precision="day", lifecycle_status="completed", domain="search",
        entity="Product X", title="Product X: launch", summary=None, review_status="auto_applied",
    )
    repo.add_cluster_member(conn, canonical_event_id=ce_official.id, event_id=official_event.id, is_seed=True)

    ce_news_only = repo.create_canonical_event(
        conn, company_id=company.id, event_type="product_launch", subject="NAVER", action="launch",
        canonical_date="2025-06-02", date_precision="day", lifecycle_status="completed", domain="search",
        entity="Product Y", title="Product Y: launch", summary=None, review_status="auto_applied",
    )
    repo.add_cluster_member(conn, canonical_event_id=ce_news_only.id, event_id=news_event.id, is_seed=True)

    # list_official_source_canonical_event_ids vs canonical_event_has_official_source
    official_ids = repo.list_official_source_canonical_event_ids(conn, company.id)
    assert official_ids == {ce_official.id}
    assert repo.canonical_event_has_official_source(conn, ce_official.id) is True
    assert repo.canonical_event_has_official_source(conn, ce_news_only.id) is False

    # list_threads_by_canonical_event vs list_threads_for_canonical_event
    thread = repo.create_thread(
        conn, company_id=company.id, title="Product X Expansion", domain="search",
        entity="Product X", review_status="auto_applied",
    )
    repo.add_thread_event(conn, thread_id=thread.id, canonical_event_id=ce_official.id, sequence_index=0, stage="launch")

    threads_by_event = repo.list_threads_by_canonical_event(conn, company.id)
    assert [t.id for t in threads_by_event.get(ce_official.id, [])] == [
        t.id for t in repo.list_threads_for_canonical_event(conn, ce_official.id)
    ]
    assert ce_news_only.id not in threads_by_event

    # list_thread_events_for_company vs list_thread_events
    bulk_thread_events = repo.list_thread_events_for_company(conn, company.id)
    assert [te.id for te in bulk_thread_events[thread.id]] == [
        te.id for te in repo.list_thread_events(conn, thread.id)
    ]

    # list_canonical_events_by_ids vs get_canonical_event
    by_id = repo.list_canonical_events_by_ids(conn, [ce_official.id, ce_news_only.id])
    assert by_id[ce_official.id].title == repo.get_canonical_event(conn, ce_official.id).title
    assert by_id[ce_news_only.id].title == repo.get_canonical_event(conn, ce_news_only.id).title
    assert repo.list_canonical_events_by_ids(conn, []) == {}


def test_relationship_upsert_normalizes_pair_order(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")
    doc, _ = repo.upsert_document(
        conn, company_id=company.id, source_type="press_release", is_official=True,
        title="t", url=None, published_date=None, external_id="ext-4", raw_text="A. B.",
    )
    chunks = repo.replace_chunks(conn, doc.id, [{"heading": None, "text": "A. B.", "start_offset": 0, "end_offset": 5}])
    chunk = chunks[0]
    candidate = EventCandidate(
        event_type="x", subject=None, action=None, event_date=None, date_precision="unknown",
        lifecycle_status="unknown", domain=None, entity=None, raw_quote="A.",
    )
    event_a = repo.insert_event(conn, chunk_id=chunk.id, candidate=candidate, extraction_model="mock", prompt_version="v1")
    event_b = repo.insert_event(conn, chunk_id=chunk.id, candidate=candidate, extraction_model="mock", prompt_version="v1")

    rel1 = repo.upsert_event_relationship(
        conn, event_a_id=event_a.id, event_b_id=event_b.id, relationship_type="same_event",
        rationale="r", confidence=0.9, decided_by="llm", review_status="pending",
    )
    rel2 = repo.upsert_event_relationship(
        conn, event_a_id=event_b.id, event_b_id=event_a.id, relationship_type="same_event",
        rationale="r2", confidence=0.95, decided_by="human", review_status="approved",
    )
    assert rel1.id == rel2.id
    assert rel2.review_status == "approved"

    pending = repo.list_pending_relationships(conn)
    assert pending == []
