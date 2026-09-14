from __future__ import annotations

from company_analyzer.db.connection import DBConnection

from company_analyzer.db import repository as repo
from company_analyzer.llm.base import LLMProvider
from company_analyzer.models import CanonicalEvent
from company_analyzer.relationships.apply import is_auto_apply
from company_analyzer.relationships.candidate_pairs import find_top_candidates, is_candidate_pair
from company_analyzer.relationships.classifier import classify_canonical_event_pair
from company_analyzer.threading.stage import infer_stage

DATE_WINDOW_DAYS = 180


def _thread_title(entity: str | None, domain: str | None) -> str:
    label = entity or domain or "이니셔티브"
    return f"{label} 확장" if entity else f"{label} 이니셔티브"


def _last_event_in_thread(conn: DBConnection, thread_id: int) -> CanonicalEvent | None:
    thread_events = repo.list_thread_events(conn, thread_id)
    if not thread_events:
        return None
    return repo.get_canonical_event(conn, thread_events[-1].canonical_event_id)


def _is_candidate(a: CanonicalEvent, b: CanonicalEvent) -> bool:
    return is_candidate_pair(
        a, b, lambda e: e.canonical_date, lambda e: e.entity, lambda e: e.domain, DATE_WINDOW_DAYS
    )


def assign_event_to_threads(
    conn: DBConnection, company_id: int, canonical_event: CanonicalEvent, provider: LLMProvider
) -> dict:
    """Incremental: called once per new (or still-unthreaded) canonical event.

    Tries existing threads first (comparing against each thread's most recent
    member), then falls back to lazily pairing with another orphan event to
    retroactively create a new thread - avoids one-event "threads" cluttering
    output. A canonical event only joins a thread on a high-confidence
    'related_distinct' classification; otherwise it stays standalone.
    """
    # rebuild_threads' caller takes one snapshot of unthreaded events up
    # front - an event in that snapshot can get threaded mid-batch as
    # another event's orphan match, then hit its own turn later in the same
    # run. Re-check rather than let a duplicate insert crash the batch.
    if repo.list_threads_for_canonical_event(conn, canonical_event.id):
        return {"action": "already_threaded"}

    stage = infer_stage(canonical_event.action, canonical_event.event_type)
    repo.set_canonical_event_stage(conn, canonical_event.id, stage)

    for thread in repo.list_threads(conn, company_id):
        last_event = _last_event_in_thread(conn, thread.id)
        if last_event is None or last_event.id == canonical_event.id:
            continue
        if not _is_candidate(canonical_event, last_event):
            continue
        relationship = classify_canonical_event_pair(conn, provider, last_event, canonical_event)
        if relationship.relationship_type == "related_distinct" and is_auto_apply(
            relationship.relationship_type, relationship.confidence
        ):
            repo.set_canonical_relationship_review_status(conn, relationship.id, "auto_applied")
            existing = repo.list_thread_events(conn, thread.id)
            repo.add_thread_event(
                conn, thread_id=thread.id, canonical_event_id=canonical_event.id,
                sequence_index=len(existing), stage=stage, relationship_id=relationship.id,
            )
            return {"action": "appended_to_thread", "thread_id": thread.id}

    orphans = [
        ce for ce in repo.list_unthreaded_canonical_events(conn, company_id) if ce.id != canonical_event.id
    ]
    # Bounded like cluster_new_events' seed comparisons - an unbounded scan
    # over every orphan sharing a generic entity/domain hit the same
    # unbounded-LLM-call pathology during a real run.
    top_orphans = find_top_candidates(
        canonical_event, orphans, lambda e: e.canonical_date, lambda e: e.entity, lambda e: e.domain,
        DATE_WINDOW_DAYS,
    )
    for orphan in top_orphans:
        relationship = classify_canonical_event_pair(conn, provider, orphan, canonical_event)
        if relationship.relationship_type == "related_distinct" and is_auto_apply(
            relationship.relationship_type, relationship.confidence
        ):
            repo.set_canonical_relationship_review_status(conn, relationship.id, "auto_applied")
            thread = repo.create_thread(
                conn, company_id=company_id, title=_thread_title(canonical_event.entity, canonical_event.domain),
                domain=canonical_event.domain, entity=canonical_event.entity, review_status="auto_applied",
            )
            ordered = sorted([orphan, canonical_event], key=lambda e: e.canonical_date or "")
            for i, ce in enumerate(ordered):
                ce_stage = infer_stage(ce.action, ce.event_type)
                repo.set_canonical_event_stage(conn, ce.id, ce_stage)
                repo.add_thread_event(
                    conn, thread_id=thread.id, canonical_event_id=ce.id, sequence_index=i,
                    stage=ce_stage, relationship_id=relationship.id,
                )
            return {"action": "created_thread", "thread_id": thread.id}

    return {"action": "standalone"}


def rebuild_threads(conn: DBConnection, company_id: int, provider: LLMProvider) -> dict:
    """Batch backfill over every unthreaded canonical event, chronologically -
    the incremental function called N times, not a separate algorithm.

    Commits after every event (see cluster_new_events for why) rather than
    once for the whole batch.
    """
    counts = {"appended_to_thread": 0, "created_thread": 0, "standalone": 0, "already_threaded": 0}
    for canonical_event in repo.list_unthreaded_canonical_events(conn, company_id):
        result = assign_event_to_threads(conn, company_id, canonical_event, provider)
        counts[result["action"]] += 1
        conn.commit()
    return counts
