from __future__ import annotations

from company_analyzer.db.connection import DBConnection
from pathlib import Path

from company_analyzer.chunking.dispatch import chunk_document
from company_analyzer.clustering.build_canonical_events import cluster_new_events
from company_analyzer.db import repository as repo
from company_analyzer.evidence.validator import validate_pending_events
from company_analyzer.extraction.extractor import extract_pending_chunks
from company_analyzer.ingestion.manual_loader import ingest_manual_documents
from company_analyzer.llm.mock_provider import MockLLMProvider
from company_analyzer.threading.build_threads import rebuild_threads
from company_analyzer.timeline.build_timeline import build_timeline

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "naver"


def _chunk_all_documents(conn: DBConnection, company_id: int) -> None:
    for document in repo.list_unchunked_documents(conn, company_id):
        drafts = chunk_document(document.source_type, document.title, document.raw_text)
        repo.replace_chunks(conn, document.id, drafts)


def test_full_pipeline_runs_end_to_end_with_mock_provider(conn: DBConnection):
    provider = MockLLMProvider()
    company = repo.get_or_create_company(conn, "NAVER", aliases=["네이버"])

    ingest_summary = ingest_manual_documents(conn, company.id, FIXTURES_DIR)
    assert ingest_summary["ingested"] == 3
    assert ingest_summary["failed"] == []

    _chunk_all_documents(conn, company.id)
    chunks = []
    for document in repo.list_documents(conn, company.id):
        chunks.extend(repo.list_chunks_for_document(conn, document.id))
    assert len(chunks) > 0
    for document in repo.list_documents(conn, company.id):
        for chunk in repo.list_chunks_for_document(conn, document.id):
            assert document.raw_text[chunk.start_offset:chunk.end_offset] == chunk.text

    extracted_count = extract_pending_chunks(conn, company.id, provider)
    assert extracted_count > 0
    events = repo.list_events_for_company(conn, company.id)
    assert len(events) == extracted_count

    validation_counts = validate_pending_events(conn, company.id)
    assert validation_counts["auto_valid"] > 0, "mock provider's quotes are copied verbatim, so they must validate"
    assert sum(validation_counts.values()) == len(events)

    cluster_counts = cluster_new_events(conn, company.id, provider)
    assert cluster_counts["new_canonical"] > 0

    timeline = build_timeline(conn, company.id)
    assert len(timeline) > 0
    assert all(ce.title for ce in timeline)
    dates = [ce.canonical_date for ce in timeline if ce.canonical_date]
    assert dates == sorted(dates)

    thread_counts = rebuild_threads(conn, company.id, provider)
    assert sum(thread_counts.values()) == len(timeline)

    threads = repo.list_threads(conn, company.id)
    for thread in threads:
        thread_events = repo.list_thread_events(conn, thread.id)
        assert len(thread_events) >= 2, "a thread should only exist once at least two events are linked"
        sequence = [te.sequence_index for te in thread_events]
        assert sequence == sorted(sequence)


def test_rerunning_pipeline_does_not_duplicate_records(conn: DBConnection):
    provider = MockLLMProvider()
    company = repo.get_or_create_company(conn, "NAVER")

    def run_once():
        ingest_manual_documents(conn, company.id, FIXTURES_DIR)
        _chunk_all_documents(conn, company.id)
        extract_pending_chunks(conn, company.id, provider)
        validate_pending_events(conn, company.id)
        cluster_new_events(conn, company.id, provider)
        rebuild_threads(conn, company.id, provider)

    run_once()
    events_after_first = len(repo.list_events_for_company(conn, company.id))
    timeline_after_first = len(build_timeline(conn, company.id))

    run_once()
    events_after_second = len(repo.list_events_for_company(conn, company.id))
    timeline_after_second = len(build_timeline(conn, company.id))

    assert events_after_second == events_after_first
    assert timeline_after_second == timeline_after_first
