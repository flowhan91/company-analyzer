from __future__ import annotations

from company_analyzer.clustering.build_canonical_events import _title_for
from company_analyzer.db import repository as repo
from company_analyzer.db.connection import DBConnection
from company_analyzer.models import CanonicalEvent, EvidenceSpan, Thread
from company_analyzer.threading.build_threads import _thread_title
from company_analyzer.threading.stage import infer_stage


class ReviewActionError(ValueError):
    pass


def _actor(human_id: str) -> str:
    return f"human:{human_id}"


# --------------------------------------------------------------------- evidence

def approve_evidence(
    conn: DBConnection,
    evidence_span_id: int,
    human_id: str,
    matched_text: str | None = None,
    start_offset: int | None = None,
    end_offset: int | None = None,
) -> EvidenceSpan:
    row = conn.execute("SELECT * FROM evidence_spans WHERE id = %s", (evidence_span_id,)).fetchone()
    if row is None:
        raise ReviewActionError(f"No evidence_span with id {evidence_span_id}")
    before = dict(row)
    updated = repo.upsert_evidence_span(
        conn, event_id=row["event_id"], chunk_id=row["chunk_id"], raw_quote=row["raw_quote"],
        matched_text=matched_text if matched_text is not None else row["matched_text"],
        start_offset=start_offset if start_offset is not None else row["start_offset"],
        end_offset=end_offset if end_offset is not None else row["end_offset"],
        match_score=row["match_score"], match_method=row["match_method"],
        is_valid=True, review_status="approved",
    )
    repo.write_audit(
        conn, table_name="evidence_spans", record_id=updated.id, action="approve",
        actor=_actor(human_id), before=before, after=updated.__dict__,
    )
    return updated


def reject_evidence(conn: DBConnection, evidence_span_id: int, human_id: str) -> EvidenceSpan:
    row = conn.execute("SELECT * FROM evidence_spans WHERE id = %s", (evidence_span_id,)).fetchone()
    if row is None:
        raise ReviewActionError(f"No evidence_span with id {evidence_span_id}")
    before = dict(row)
    updated = repo.upsert_evidence_span(
        conn, event_id=row["event_id"], chunk_id=row["chunk_id"], raw_quote=row["raw_quote"],
        matched_text=row["matched_text"], start_offset=row["start_offset"], end_offset=row["end_offset"],
        match_score=row["match_score"], match_method=row["match_method"],
        is_valid=False, review_status="rejected",
    )
    repo.write_audit(
        conn, table_name="evidence_spans", record_id=updated.id, action="reject",
        actor=_actor(human_id), before=before, after=updated.__dict__,
    )
    return updated


# -------------------------------------------------------- duplicate relationships

def approve_event_relationship(conn: DBConnection, relationship_id: int, human_id: str) -> CanonicalEvent:
    """Approve a same_event proposal: perform the merge a human confirmed."""
    row = conn.execute("SELECT * FROM event_relationships WHERE id = %s", (relationship_id,)).fetchone()
    if row is None:
        raise ReviewActionError(f"No event_relationship with id {relationship_id}")
    if row["relationship_type"] != "same_event":
        raise ReviewActionError("approve_event_relationship only applies to 'same_event' relationships")
    before = dict(row)

    event_a = repo.get_event(conn, row["event_a_id"])
    event_b = repo.get_event(conn, row["event_b_id"])
    ce_a = repo.get_canonical_event_for_event(conn, event_a.id)
    ce_b = repo.get_canonical_event_for_event(conn, event_b.id)

    if ce_a is not None:
        target, other_event = ce_a, event_b
    elif ce_b is not None:
        target, other_event = ce_b, event_a
    else:
        company_id = repo.get_company_id_for_event(conn, event_a.id)
        target = repo.create_canonical_event(
            conn, company_id=company_id, event_type=event_a.event_type, subject=event_a.subject,
            action=event_a.action, canonical_date=event_a.event_date, date_precision=event_a.date_precision,
            lifecycle_status=event_a.lifecycle_status, domain=event_a.domain, entity=event_a.entity,
            title=_title_for(event_a), summary=event_a.raw_quote, review_status="approved",
        )
        repo.add_cluster_member(conn, canonical_event_id=target.id, event_id=event_a.id, is_seed=True, relationship_id=relationship_id)
        other_event = event_b

    if repo.get_canonical_event_for_event(conn, other_event.id) is None:
        repo.add_cluster_member(
            conn, canonical_event_id=target.id, event_id=other_event.id, is_seed=False, relationship_id=relationship_id
        )

    repo.set_relationship_review_status(conn, relationship_id, "approved")
    repo.write_audit(
        conn, table_name="event_relationships", record_id=relationship_id, action="approve",
        actor=_actor(human_id), before=before, after={"review_status": "approved", "merged_into": target.id},
    )
    return target


def reject_event_relationship(conn: DBConnection, relationship_id: int, human_id: str) -> None:
    row = conn.execute("SELECT * FROM event_relationships WHERE id = %s", (relationship_id,)).fetchone()
    if row is None:
        raise ReviewActionError(f"No event_relationship with id {relationship_id}")
    before = dict(row)
    repo.set_relationship_review_status(conn, relationship_id, "rejected")
    repo.write_audit(
        conn, table_name="event_relationships", record_id=relationship_id, action="reject",
        actor=_actor(human_id), before=before, after={"review_status": "rejected"},
    )


# ----------------------------------------------------------- thread relationships

def approve_canonical_relationship(conn: DBConnection, relationship_id: int, human_id: str) -> Thread:
    """Approve a related_distinct proposal: perform the thread membership a
    human confirmed (append to an existing thread, or create a new one)."""
    row = conn.execute("SELECT * FROM canonical_event_relationships WHERE id = %s", (relationship_id,)).fetchone()
    if row is None:
        raise ReviewActionError(f"No canonical_event_relationship with id {relationship_id}")
    if row["relationship_type"] != "related_distinct":
        raise ReviewActionError("approve_canonical_relationship only applies to 'related_distinct' relationships")
    before = dict(row)

    ce_a = repo.get_canonical_event(conn, row["canonical_event_a_id"])
    ce_b = repo.get_canonical_event(conn, row["canonical_event_b_id"])
    threads_a = repo.list_threads_for_canonical_event(conn, ce_a.id)
    threads_b = repo.list_threads_for_canonical_event(conn, ce_b.id)

    if threads_a:
        thread, new_member = threads_a[0], ce_b
    elif threads_b:
        thread, new_member = threads_b[0], ce_a
    else:
        thread = repo.create_thread(
            conn, company_id=ce_a.company_id, title=_thread_title(ce_a.entity, ce_a.domain),
            domain=ce_a.domain, entity=ce_a.entity, review_status="approved",
        )
        first, second = sorted([ce_a, ce_b], key=lambda e: e.canonical_date or "")
        for i, ce in enumerate([first, second]):
            stage = infer_stage(ce.action, ce.event_type)
            repo.set_canonical_event_stage(conn, ce.id, stage)
            repo.add_thread_event(
                conn, thread_id=thread.id, canonical_event_id=ce.id, sequence_index=i,
                stage=stage, relationship_id=relationship_id,
            )
        repo.set_canonical_relationship_review_status(conn, relationship_id, "approved")
        repo.write_audit(
            conn, table_name="canonical_event_relationships", record_id=relationship_id, action="approve",
            actor=_actor(human_id), before=before, after={"review_status": "approved", "thread_id": thread.id},
        )
        return thread

    if new_member.id not in {te.canonical_event_id for te in repo.list_thread_events(conn, thread.id)}:
        existing = repo.list_thread_events(conn, thread.id)
        stage = infer_stage(new_member.action, new_member.event_type)
        repo.set_canonical_event_stage(conn, new_member.id, stage)
        repo.add_thread_event(
            conn, thread_id=thread.id, canonical_event_id=new_member.id, sequence_index=len(existing),
            stage=stage, relationship_id=relationship_id,
        )

    repo.set_canonical_relationship_review_status(conn, relationship_id, "approved")
    repo.write_audit(
        conn, table_name="canonical_event_relationships", record_id=relationship_id, action="approve",
        actor=_actor(human_id), before=before, after={"review_status": "approved", "thread_id": thread.id},
    )
    return thread


def reject_canonical_relationship(conn: DBConnection, relationship_id: int, human_id: str) -> None:
    row = conn.execute("SELECT * FROM canonical_event_relationships WHERE id = %s", (relationship_id,)).fetchone()
    if row is None:
        raise ReviewActionError(f"No canonical_event_relationship with id {relationship_id}")
    before = dict(row)
    repo.set_canonical_relationship_review_status(conn, relationship_id, "rejected")
    repo.write_audit(
        conn, table_name="canonical_event_relationships", record_id=relationship_id, action="reject",
        actor=_actor(human_id), before=before, after={"review_status": "rejected"},
    )
