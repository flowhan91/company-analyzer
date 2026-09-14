from __future__ import annotations

from company_analyzer.db.connection import DBConnection

from company_analyzer.db import repository as repo
from company_analyzer.evidence.matcher import fuzzy_locate
from company_analyzer.models import EvidenceSpan, Event


def validate_event_evidence(conn: DBConnection, event: Event) -> EvidenceSpan:
    """Locate an event's raw_quote in its source chunk and persist the result.

    Always writes a row (valid, pending-review, or rejected) - evidence
    quality is never silently dropped, only gated from downstream use via
    is_valid / review_status.
    """
    chunk = repo.get_chunk(conn, event.chunk_id)
    match = fuzzy_locate(event.raw_quote, chunk.text)

    if match.is_valid:
        review_status = "auto_valid"
    elif match.method == "rejected":
        review_status = "rejected"
    else:
        review_status = "pending"

    global_start = chunk.start_offset + match.start if match.start is not None else None
    global_end = chunk.start_offset + match.end if match.end is not None else None

    return repo.upsert_evidence_span(
        conn,
        event_id=event.id,
        chunk_id=chunk.id,
        raw_quote=event.raw_quote,
        matched_text=match.matched_text,
        start_offset=global_start,
        end_offset=global_end,
        match_score=match.score,
        match_method=match.method,
        is_valid=match.is_valid,
        review_status=review_status,
    )


def validate_pending_events(conn: DBConnection, company_id: int) -> dict:
    """Validate evidence for every event that doesn't have an evidence_spans row yet."""
    counts = {"auto_valid": 0, "pending": 0, "rejected": 0}
    for event in repo.list_unvalidated_events(conn, company_id):
        span = validate_event_evidence(conn, event)
        counts[span.review_status] = counts.get(span.review_status, 0) + 1
    return counts
