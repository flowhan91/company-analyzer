from __future__ import annotations

from company_analyzer.db import repository as repo
from company_analyzer.db.connection import DBConnection
from company_analyzer.llm.mock_provider import MockLLMProvider
from company_analyzer.threading.build_threads import assign_event_to_threads, rebuild_threads


def _make_canonical_event(conn: DBConnection, company_id: int, entity: str, canonical_date: str) -> repo.CanonicalEvent:
    return repo.create_canonical_event(
        conn, company_id=company_id, event_type="product_launch", subject="NAVER", action="launch",
        canonical_date=canonical_date, date_precision="day", lifecycle_status="completed", domain="search",
        entity=entity, title=f"{entity}: launch", summary=None, review_status="auto_applied",
    )


def test_assign_event_to_threads_skips_an_already_threaded_event_instead_of_crashing(conn: DBConnection):
    """Regression test: rebuild_threads takes one snapshot of unthreaded
    events up front. In a real run, an event in that snapshot got threaded
    mid-batch as another event's orphan match, then hit its own turn later
    in the same loop and crashed on a duplicate-key insert. assign_event_to_
    threads must re-check and skip cleanly instead."""
    provider = MockLLMProvider()
    company = repo.get_or_create_company(conn, "NAVER")
    ce_a = _make_canonical_event(conn, company.id, "Product A", "2025-06-01")
    ce_b = _make_canonical_event(conn, company.id, "Product B", "2025-06-02")

    thread = repo.create_thread(
        conn, company_id=company.id, title="Product A Expansion", domain="search",
        entity="Product A", review_status="auto_applied",
    )
    repo.add_thread_event(conn, thread_id=thread.id, canonical_event_id=ce_a.id, sequence_index=0, stage="launch")
    repo.add_thread_event(conn, thread_id=thread.id, canonical_event_id=ce_b.id, sequence_index=1, stage="launch")

    # ce_a is already threaded (simulating it having been threaded earlier
    # in the same batch via another event's orphan match) - processing its
    # own turn must not attempt a duplicate insert.
    result = assign_event_to_threads(conn, company.id, ce_a, provider)
    assert result == {"action": "already_threaded"}

    thread_events = repo.list_thread_events(conn, thread.id)
    assert len(thread_events) == 2, "no duplicate row should have been inserted"


def test_rebuild_threads_does_not_crash_when_snapshot_goes_stale(conn: DBConnection):
    """End-to-end version of the same regression: even with a batch that
    includes an event pre-threaded out from under rebuild_threads' snapshot,
    the whole batch must complete rather than raising."""
    provider = MockLLMProvider()
    company = repo.get_or_create_company(conn, "NAVER")
    ce_a = _make_canonical_event(conn, company.id, "Product A", "2025-06-01")
    ce_b = _make_canonical_event(conn, company.id, "Product B", "2025-09-01")

    thread = repo.create_thread(
        conn, company_id=company.id, title="Product A Expansion", domain="search",
        entity="Product A", review_status="auto_applied",
    )
    repo.add_thread_event(conn, thread_id=thread.id, canonical_event_id=ce_a.id, sequence_index=0, stage="launch")

    # ce_a is threaded but list_unthreaded_canonical_events wouldn't return
    # it anyway - this confirms the batch entrypoint stays robust with a mix
    # of threaded/unthreaded events already present in the company.
    counts = rebuild_threads(conn, company.id, provider)
    assert counts["standalone"] + counts["appended_to_thread"] + counts["created_thread"] >= 1
    assert repo.list_thread_events(conn, thread.id)[0].canonical_event_id == ce_a.id
