from __future__ import annotations

from company_analyzer.db.connection import DBConnection

from company_analyzer.db import repository as repo
from company_analyzer.llm.base import LLMProvider
from company_analyzer.models import CanonicalEvent, CanonicalEventRelationship, Event, EventRelationship


def _event_to_dict(conn: DBConnection, event: Event) -> dict:
    evidence = repo.get_evidence_for_event(conn, event.id)
    return {
        "event_type": event.event_type,
        "subject": event.subject,
        "action": event.action,
        "event_date": event.event_date,
        "domain": event.domain,
        "entity": event.entity,
        "lifecycle_status": event.lifecycle_status,
        "evidence_text": evidence.matched_text if evidence and evidence.is_valid else event.raw_quote,
    }


def classify_event_pair(conn: DBConnection, provider: LLMProvider, event_a: Event, event_b: Event) -> EventRelationship:
    result = provider.classify_relationship(_event_to_dict(conn, event_a), _event_to_dict(conn, event_b))
    return repo.upsert_event_relationship(
        conn,
        event_a_id=event_a.id,
        event_b_id=event_b.id,
        relationship_type=result["relationship_type"],
        rationale=result.get("rationale"),
        confidence=float(result["confidence"]),
        decided_by="llm",
        review_status="pending",
    )


def _canonical_event_to_dict(ce: CanonicalEvent) -> dict:
    return {
        "event_type": ce.event_type,
        "subject": ce.subject,
        "action": ce.action,
        "event_date": ce.canonical_date,
        "domain": ce.domain,
        "entity": ce.entity,
        "lifecycle_status": ce.lifecycle_status,
        "evidence_text": ce.summary or ce.title,
    }


def classify_canonical_event_pair(
    conn: DBConnection, provider: LLMProvider, ce_a: CanonicalEvent, ce_b: CanonicalEvent
) -> CanonicalEventRelationship:
    result = provider.classify_relationship(_canonical_event_to_dict(ce_a), _canonical_event_to_dict(ce_b))
    return repo.upsert_canonical_event_relationship(
        conn,
        canonical_event_a_id=ce_a.id,
        canonical_event_b_id=ce_b.id,
        relationship_type=result["relationship_type"],
        rationale=result.get("rationale"),
        confidence=float(result["confidence"]),
        decided_by="llm",
        review_status="pending",
    )
