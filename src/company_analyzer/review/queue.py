from __future__ import annotations

from company_analyzer.db.connection import DBConnection

from company_analyzer.db import repository as repo


def pending_evidence(conn: DBConnection, company_id: int) -> list[dict]:
    items = []
    for span in repo.list_pending_evidence(conn, company_id):
        event = repo.get_event(conn, span.event_id)
        items.append({"evidence": span, "event": event})
    return items


def pending_event_relationships(conn: DBConnection, relationship_type: str | None = None) -> list[dict]:
    items = []
    for relationship in repo.list_pending_relationships(conn, relationship_type=relationship_type):
        items.append(
            {
                "relationship": relationship,
                "event_a": repo.get_event(conn, relationship.event_a_id),
                "event_b": repo.get_event(conn, relationship.event_b_id),
            }
        )
    return items


def pending_canonical_relationships(conn: DBConnection, relationship_type: str | None = None) -> list[dict]:
    items = []
    for relationship in repo.list_pending_canonical_relationships(conn, relationship_type=relationship_type):
        items.append(
            {
                "relationship": relationship,
                "canonical_event_a": repo.get_canonical_event(conn, relationship.canonical_event_a_id),
                "canonical_event_b": repo.get_canonical_event(conn, relationship.canonical_event_b_id),
            }
        )
    return items


def review_summary(conn: DBConnection, company_id: int) -> dict:
    return {
        "pending_evidence": len(repo.list_pending_evidence(conn, company_id)),
        "pending_duplicate_relationships": len(
            repo.list_pending_relationships(conn, relationship_type="same_event")
        ),
        "pending_thread_relationships": len(repo.list_pending_canonical_relationships(conn)),
    }
