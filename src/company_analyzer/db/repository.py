"""Thin CRUD/query functions over the schema in schema.sql.

Every function takes an open DBConnection as its first argument (see
connection.get_connection) rather than owning its own connection, so the CLI,
the web app, and tests can all share one transaction when needed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from company_analyzer.db.connection import DBConnection
from company_analyzer.models import (
    CanonicalEvent,
    CanonicalEventRelationship,
    Chunk,
    Company,
    Document,
    DocumentSnapshot,
    Event,
    EventCandidate,
    EventRelationship,
    EvidenceSpan,
    IngestionLogEntry,
    Thread,
    ThreadEvent,
    UserJD,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- companies

def _row_to_company(row: dict) -> Company:
    return Company(
        id=row["id"],
        name=row["name"],
        dart_corp_code=row["dart_corp_code"],
        aliases=json.loads(row["aliases_json"]),
    )


def get_or_create_company(conn: DBConnection, name: str, aliases: list[str] | None = None) -> Company:
    row = conn.execute("SELECT * FROM companies WHERE name = %s", (name,)).fetchone()
    if row is not None:
        return _row_to_company(row)
    cur = conn.execute(
        "INSERT INTO companies (name, aliases_json) VALUES (%s, %s) RETURNING id",
        (name, json.dumps(aliases or [])),
    )
    return get_company_by_id(conn, cur.fetchone()["id"])


def get_company_by_id(conn: DBConnection, company_id: int) -> Company:
    row = conn.execute("SELECT * FROM companies WHERE id = %s", (company_id,)).fetchone()
    if row is None:
        raise KeyError(f"No company with id {company_id}")
    return _row_to_company(row)


def get_company_by_name(conn: DBConnection, name: str) -> Company | None:
    row = conn.execute("SELECT * FROM companies WHERE name = %s", (name,)).fetchone()
    return _row_to_company(row) if row is not None else None


def set_dart_corp_code(conn: DBConnection, company_id: int, corp_code: str) -> None:
    conn.execute("UPDATE companies SET dart_corp_code = %s WHERE id = %s", (corp_code, company_id))


# ---------------------------------------------------------------- documents

def _row_to_document(row: dict) -> Document:
    return Document(
        id=row["id"],
        company_id=row["company_id"],
        source_type=row["source_type"],
        is_official=bool(row["is_official"]),
        title=row["title"],
        url=row["url"],
        published_date=row["published_date"],
        external_id=row["external_id"],
        file_path=row["file_path"],
        raw_text=row["raw_text"],
        content_hash=row["content_hash"],
        version=row["version"],
        fetched_at=row["fetched_at"],
        metadata=json.loads(row["metadata_json"]),
    )


def upsert_document(
    conn: DBConnection,
    *,
    company_id: int,
    source_type: str,
    is_official: bool,
    title: str,
    url: str | None,
    published_date: str | None,
    external_id: str,
    raw_text: str,
    file_path: str | None = None,
    metadata: dict | None = None,
) -> tuple[Document, bool]:
    """Insert a new document, or update it if content changed (versioned).

    Returns (document, changed) where changed is True if this call created a
    new document or produced a new version of an existing one, and False if
    an identical document already existed (safe to call repeatedly / rerun).
    """
    now = _now()
    new_hash = content_hash(raw_text)
    metadata_json = json.dumps(metadata or {})

    existing = conn.execute(
        "SELECT * FROM documents WHERE company_id = %s AND source_type = %s AND external_id = %s",
        (company_id, source_type, external_id),
    ).fetchone()

    if existing is None:
        cur = conn.execute(
            """
            INSERT INTO documents
                (company_id, source_type, is_official, title, url, published_date,
                 external_id, file_path, raw_text, content_hash, version, fetched_at, metadata_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s)
            RETURNING id
            """,
            (
                company_id, source_type, is_official, title, url, published_date,
                external_id, file_path, raw_text, new_hash, now, metadata_json,
            ),
        )
        doc_id = cur.fetchone()["id"]
        conn.execute(
            """
            INSERT INTO document_snapshots (document_id, version, raw_text, content_hash, fetched_at)
            VALUES (%s, 1, %s, %s, %s)
            """,
            (doc_id, raw_text, new_hash, now),
        )
        return get_document(conn, doc_id), True

    if existing["content_hash"] == new_hash:
        return _row_to_document(existing), False

    new_version = existing["version"] + 1
    conn.execute(
        """
        INSERT INTO document_snapshots (document_id, version, raw_text, content_hash, fetched_at)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (existing["id"], new_version, raw_text, new_hash, now),
    )
    conn.execute(
        """
        UPDATE documents
        SET title = %s, url = %s, published_date = %s, raw_text = %s, content_hash = %s,
            version = %s, fetched_at = %s, metadata_json = %s, file_path = %s
        WHERE id = %s
        """,
        (
            title, url, published_date, raw_text, new_hash, new_version, now,
            metadata_json, file_path, existing["id"],
        ),
    )
    return get_document(conn, existing["id"]), True


def get_document(conn: DBConnection, document_id: int) -> Document:
    row = conn.execute("SELECT * FROM documents WHERE id = %s", (document_id,)).fetchone()
    if row is None:
        raise KeyError(f"No document with id {document_id}")
    return _row_to_document(row)


def list_documents(
    conn: DBConnection, company_id: int, source_type: str | None = None
) -> list[Document]:
    if source_type:
        rows = conn.execute(
            "SELECT * FROM documents WHERE company_id = %s AND source_type = %s ORDER BY published_date",
            (company_id, source_type),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM documents WHERE company_id = %s ORDER BY published_date", (company_id,)
        ).fetchall()
    return [_row_to_document(r) for r in rows]


def list_document_snapshots(conn: DBConnection, document_id: int) -> list[DocumentSnapshot]:
    rows = conn.execute(
        "SELECT * FROM document_snapshots WHERE document_id = %s ORDER BY version", (document_id,)
    ).fetchall()
    return [
        DocumentSnapshot(
            id=r["id"], document_id=r["document_id"], version=r["version"],
            raw_text=r["raw_text"], content_hash=r["content_hash"], fetched_at=r["fetched_at"],
        )
        for r in rows
    ]


# ------------------------------------------------------------ ingestion log

def log_ingestion(
    conn: DBConnection,
    *,
    source: str,
    company_id: int,
    status: str,
    detail: str | None = None,
    error_message: str | None = None,
) -> IngestionLogEntry:
    cur = conn.execute(
        """
        INSERT INTO ingestion_log (source, company_id, status, detail, error_message, occurred_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (source, company_id, status, detail, error_message, _now()),
    )
    row = conn.execute("SELECT * FROM ingestion_log WHERE id = %s", (cur.fetchone()["id"],)).fetchone()
    return IngestionLogEntry(
        id=row["id"], source=row["source"], company_id=row["company_id"], status=row["status"],
        detail=row["detail"], error_message=row["error_message"], occurred_at=row["occurred_at"],
    )


# --------------------------------------------------------------------- chunks

def _row_to_chunk(row: dict) -> Chunk:
    return Chunk(
        id=row["id"], document_id=row["document_id"], chunk_index=row["chunk_index"],
        heading=row["heading"], text=row["text"],
        start_offset=row["start_offset"], end_offset=row["end_offset"],
    )


def replace_chunks(conn: DBConnection, document_id: int, drafts: list[dict]) -> list[Chunk]:
    """Delete existing chunks for a document and insert the given drafts.

    Re-chunking a document (e.g. after a content change) should never leave
    stale chunks around, so this is a full replace, not an append.
    """
    conn.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
    chunks = []
    for i, draft in enumerate(drafts):
        cur = conn.execute(
            """
            INSERT INTO chunks (document_id, chunk_index, heading, text, start_offset, end_offset)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (document_id, i, draft.get("heading"), draft["text"], draft["start_offset"], draft["end_offset"]),
        )
        chunks.append(get_chunk(conn, cur.fetchone()["id"]))
    return chunks


def get_chunk(conn: DBConnection, chunk_id: int) -> Chunk:
    row = conn.execute("SELECT * FROM chunks WHERE id = %s", (chunk_id,)).fetchone()
    if row is None:
        raise KeyError(f"No chunk with id {chunk_id}")
    return _row_to_chunk(row)


def list_chunks_for_document(conn: DBConnection, document_id: int) -> list[Chunk]:
    rows = conn.execute(
        "SELECT * FROM chunks WHERE document_id = %s ORDER BY chunk_index", (document_id,)
    ).fetchall()
    return [_row_to_chunk(r) for r in rows]


def list_unchunked_documents(conn: DBConnection, company_id: int) -> list[Document]:
    rows = conn.execute(
        """
        SELECT d.* FROM documents d
        LEFT JOIN chunks c ON c.document_id = d.id
        WHERE d.company_id = %s AND c.id IS NULL
        """,
        (company_id,),
    ).fetchall()
    return [_row_to_document(r) for r in rows]


# --------------------------------------------------------------------- events

def _row_to_event(row: dict) -> Event:
    return Event(
        id=row["id"], chunk_id=row["chunk_id"], event_type=row["event_type"],
        subject=row["subject"], action=row["action"], event_date=row["event_date"],
        date_precision=row["date_precision"], lifecycle_status=row["lifecycle_status"],
        domain=row["domain"], entity=row["entity"], raw_quote=row["raw_quote"],
        extraction_model=row["extraction_model"], prompt_version=row["prompt_version"],
        llm_raw_response_json=row["llm_raw_response_json"], created_at=row["created_at"],
    )


def insert_event(
    conn: DBConnection,
    *,
    chunk_id: int,
    candidate: EventCandidate,
    extraction_model: str,
    prompt_version: str,
    llm_raw_response_json: str | None = None,
) -> Event:
    cur = conn.execute(
        """
        INSERT INTO events
            (chunk_id, event_type, subject, action, event_date, date_precision,
             lifecycle_status, domain, entity, raw_quote, extraction_model,
             prompt_version, llm_raw_response_json, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            chunk_id, candidate.event_type, candidate.subject, candidate.action,
            candidate.event_date, candidate.date_precision, candidate.lifecycle_status,
            candidate.domain, candidate.entity, candidate.raw_quote, extraction_model,
            prompt_version, llm_raw_response_json, _now(),
        ),
    )
    return get_event(conn, cur.fetchone()["id"])


def get_event(conn: DBConnection, event_id: int) -> Event:
    row = conn.execute("SELECT * FROM events WHERE id = %s", (event_id,)).fetchone()
    if row is None:
        raise KeyError(f"No event with id {event_id}")
    return _row_to_event(row)


def list_events_for_chunk(conn: DBConnection, chunk_id: int) -> list[Event]:
    rows = conn.execute("SELECT * FROM events WHERE chunk_id = %s", (chunk_id,)).fetchall()
    return [_row_to_event(r) for r in rows]


def list_events_for_company(conn: DBConnection, company_id: int) -> list[Event]:
    rows = conn.execute(
        """
        SELECT e.* FROM events e
        JOIN chunks c ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        WHERE d.company_id = %s
        """,
        (company_id,),
    ).fetchall()
    return [_row_to_event(r) for r in rows]


def is_event_official(conn: DBConnection, event_id: int) -> bool:
    row = conn.execute(
        """
        SELECT d.is_official FROM events e
        JOIN chunks c ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        WHERE e.id = %s
        """,
        (event_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"No event with id {event_id}")
    return bool(row["is_official"])


def get_company_id_for_event(conn: DBConnection, event_id: int) -> int:
    row = conn.execute(
        """
        SELECT d.company_id FROM events e
        JOIN chunks c ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        WHERE e.id = %s
        """,
        (event_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"No event with id {event_id}")
    return row["company_id"]


def list_unextracted_chunks(conn: DBConnection, company_id: int) -> list[Chunk]:
    rows = conn.execute(
        """
        SELECT c.* FROM chunks c
        JOIN documents d ON d.id = c.document_id
        LEFT JOIN events e ON e.chunk_id = c.id
        WHERE d.company_id = %s AND e.id IS NULL
        """,
        (company_id,),
    ).fetchall()
    return [_row_to_chunk(r) for r in rows]


# ------------------------------------------------------------- evidence spans

def _row_to_evidence(row: dict) -> EvidenceSpan:
    embedding_json = row.get("embedding_json")
    return EvidenceSpan(
        id=row["id"], event_id=row["event_id"], chunk_id=row["chunk_id"],
        raw_quote=row["raw_quote"], matched_text=row["matched_text"],
        start_offset=row["start_offset"], end_offset=row["end_offset"],
        match_score=row["match_score"], match_method=row["match_method"],
        is_valid=bool(row["is_valid"]), review_status=row["review_status"],
        validated_at=row["validated_at"],
        embedding=json.loads(embedding_json) if embedding_json else None,
    )


def upsert_evidence_span(
    conn: DBConnection,
    *,
    event_id: int,
    chunk_id: int,
    raw_quote: str,
    matched_text: str | None,
    start_offset: int | None,
    end_offset: int | None,
    match_score: float,
    match_method: str,
    is_valid: bool,
    review_status: str,
) -> EvidenceSpan:
    existing = conn.execute("SELECT id FROM evidence_spans WHERE event_id = %s", (event_id,)).fetchone()
    now = _now()
    if existing is not None:
        conn.execute(
            """
            UPDATE evidence_spans
            SET chunk_id=%s, raw_quote=%s, matched_text=%s, start_offset=%s, end_offset=%s,
                match_score=%s, match_method=%s, is_valid=%s, review_status=%s, validated_at=%s
            WHERE event_id = %s
            """,
            (
                chunk_id, raw_quote, matched_text, start_offset, end_offset, match_score,
                match_method, is_valid, review_status, now, event_id,
            ),
        )
        span_id = existing["id"]
    else:
        cur = conn.execute(
            """
            INSERT INTO evidence_spans
                (event_id, chunk_id, raw_quote, matched_text, start_offset, end_offset,
                 match_score, match_method, is_valid, review_status, validated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                event_id, chunk_id, raw_quote, matched_text, start_offset, end_offset,
                match_score, match_method, is_valid, review_status, now,
            ),
        )
        span_id = cur.fetchone()["id"]
    row = conn.execute("SELECT * FROM evidence_spans WHERE id = %s", (span_id,)).fetchone()
    return _row_to_evidence(row)


def get_evidence_for_event(conn: DBConnection, event_id: int) -> EvidenceSpan | None:
    row = conn.execute("SELECT * FROM evidence_spans WHERE event_id = %s", (event_id,)).fetchone()
    return _row_to_evidence(row) if row is not None else None


def list_unvalidated_events(conn: DBConnection, company_id: int) -> list[Event]:
    rows = conn.execute(
        """
        SELECT e.* FROM events e
        JOIN chunks c ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        LEFT JOIN evidence_spans ev ON ev.event_id = e.id
        WHERE d.company_id = %s AND ev.id IS NULL
        """,
        (company_id,),
    ).fetchall()
    return [_row_to_event(r) for r in rows]


def list_pending_evidence(conn: DBConnection, company_id: int) -> list[EvidenceSpan]:
    rows = conn.execute(
        """
        SELECT ev.* FROM evidence_spans ev
        JOIN events e ON e.id = ev.event_id
        JOIN chunks c ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        WHERE d.company_id = %s AND ev.review_status = 'pending'
        """,
        (company_id,),
    ).fetchall()
    return [_row_to_evidence(r) for r in rows]


def list_valid_evidence_for_company(conn: DBConnection, company_id: int) -> list[EvidenceSpan]:
    """Every valid evidence span for a company (JD matching's candidate pool)."""
    rows = conn.execute(
        """
        SELECT ev.* FROM evidence_spans ev
        JOIN events e ON e.id = ev.event_id
        JOIN chunks c ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        WHERE d.company_id = %s AND ev.is_valid = TRUE
        """,
        (company_id,),
    ).fetchall()
    return [_row_to_evidence(r) for r in rows]


def list_valid_evidence_missing_embedding(conn: DBConnection, company_id: int) -> list[EvidenceSpan]:
    rows = conn.execute(
        """
        SELECT ev.* FROM evidence_spans ev
        JOIN events e ON e.id = ev.event_id
        JOIN chunks c ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        WHERE d.company_id = %s AND ev.is_valid = TRUE AND ev.embedding_json IS NULL
        """,
        (company_id,),
    ).fetchall()
    return [_row_to_evidence(r) for r in rows]


def set_evidence_embedding(conn: DBConnection, evidence_span_id: int, embedding: list[float]) -> None:
    conn.execute(
        "UPDATE evidence_spans SET embedding_json = %s WHERE id = %s",
        (json.dumps(embedding), evidence_span_id),
    )


def list_canonical_event_id_by_event_id(conn: DBConnection, company_id: int) -> dict[int, int]:
    """Bulk event_id -> canonical_event_id lookup for a whole company, one query."""
    rows = conn.execute(
        """
        SELECT m.event_id, m.canonical_event_id FROM event_cluster_members m
        JOIN canonical_events ce ON ce.id = m.canonical_event_id
        WHERE ce.company_id = %s
        """,
        (company_id,),
    ).fetchall()
    return {row["event_id"]: row["canonical_event_id"] for row in rows}


# --------------------------------------------------------- event relationships

def _row_to_relationship(row: dict) -> EventRelationship:
    return EventRelationship(
        id=row["id"], event_a_id=row["event_a_id"], event_b_id=row["event_b_id"],
        relationship_type=row["relationship_type"], rationale=row["rationale"],
        confidence=row["confidence"], decided_by=row["decided_by"],
        review_status=row["review_status"], created_at=row["created_at"],
    )


def upsert_event_relationship(
    conn: DBConnection,
    *,
    event_a_id: int,
    event_b_id: int,
    relationship_type: str,
    rationale: str | None,
    confidence: float,
    decided_by: str,
    review_status: str,
) -> EventRelationship:
    # Normalize order so (a, b) and (b, a) always map to the same row.
    a, b = sorted((event_a_id, event_b_id))
    existing = conn.execute(
        "SELECT id FROM event_relationships WHERE event_a_id = %s AND event_b_id = %s", (a, b)
    ).fetchone()
    if existing is not None:
        conn.execute(
            """
            UPDATE event_relationships
            SET relationship_type=%s, rationale=%s, confidence=%s, decided_by=%s, review_status=%s
            WHERE id = %s
            """,
            (relationship_type, rationale, confidence, decided_by, review_status, existing["id"]),
        )
        rel_id = existing["id"]
    else:
        cur = conn.execute(
            """
            INSERT INTO event_relationships
                (event_a_id, event_b_id, relationship_type, rationale, confidence,
                 decided_by, review_status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (a, b, relationship_type, rationale, confidence, decided_by, review_status, _now()),
        )
        rel_id = cur.fetchone()["id"]
    row = conn.execute("SELECT * FROM event_relationships WHERE id = %s", (rel_id,)).fetchone()
    return _row_to_relationship(row)


def list_pending_relationships(conn: DBConnection, relationship_type: str | None = None) -> list[EventRelationship]:
    if relationship_type:
        rows = conn.execute(
            "SELECT * FROM event_relationships WHERE review_status = 'pending' AND relationship_type = %s",
            (relationship_type,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM event_relationships WHERE review_status = 'pending'"
        ).fetchall()
    return [_row_to_relationship(r) for r in rows]


def set_relationship_review_status(conn: DBConnection, relationship_id: int, review_status: str) -> None:
    conn.execute(
        "UPDATE event_relationships SET review_status = %s WHERE id = %s", (review_status, relationship_id)
    )


# ------------------------------------------------------ canonical event relationships

def _row_to_canonical_relationship(row: dict) -> CanonicalEventRelationship:
    return CanonicalEventRelationship(
        id=row["id"], canonical_event_a_id=row["canonical_event_a_id"],
        canonical_event_b_id=row["canonical_event_b_id"], relationship_type=row["relationship_type"],
        rationale=row["rationale"], confidence=row["confidence"], decided_by=row["decided_by"],
        review_status=row["review_status"], created_at=row["created_at"],
    )


def upsert_canonical_event_relationship(
    conn: DBConnection,
    *,
    canonical_event_a_id: int,
    canonical_event_b_id: int,
    relationship_type: str,
    rationale: str | None,
    confidence: float,
    decided_by: str,
    review_status: str,
) -> CanonicalEventRelationship:
    a, b = sorted((canonical_event_a_id, canonical_event_b_id))
    existing = conn.execute(
        "SELECT id FROM canonical_event_relationships WHERE canonical_event_a_id = %s AND canonical_event_b_id = %s",
        (a, b),
    ).fetchone()
    if existing is not None:
        conn.execute(
            """
            UPDATE canonical_event_relationships
            SET relationship_type=%s, rationale=%s, confidence=%s, decided_by=%s, review_status=%s
            WHERE id = %s
            """,
            (relationship_type, rationale, confidence, decided_by, review_status, existing["id"]),
        )
        rel_id = existing["id"]
    else:
        cur = conn.execute(
            """
            INSERT INTO canonical_event_relationships
                (canonical_event_a_id, canonical_event_b_id, relationship_type, rationale,
                 confidence, decided_by, review_status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (a, b, relationship_type, rationale, confidence, decided_by, review_status, _now()),
        )
        rel_id = cur.fetchone()["id"]
    row = conn.execute("SELECT * FROM canonical_event_relationships WHERE id = %s", (rel_id,)).fetchone()
    return _row_to_canonical_relationship(row)


def list_pending_canonical_relationships(
    conn: DBConnection, relationship_type: str | None = None
) -> list[CanonicalEventRelationship]:
    if relationship_type:
        rows = conn.execute(
            "SELECT * FROM canonical_event_relationships WHERE review_status = 'pending' AND relationship_type = %s",
            (relationship_type,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM canonical_event_relationships WHERE review_status = 'pending'"
        ).fetchall()
    return [_row_to_canonical_relationship(r) for r in rows]


def set_canonical_relationship_review_status(conn: DBConnection, relationship_id: int, review_status: str) -> None:
    conn.execute(
        "UPDATE canonical_event_relationships SET review_status = %s WHERE id = %s", (review_status, relationship_id)
    )


# ------------------------------------------------------------- canonical events

def _row_to_canonical_event(row: dict) -> CanonicalEvent:
    return CanonicalEvent(
        id=row["id"], company_id=row["company_id"], event_type=row["event_type"],
        subject=row["subject"], action=row["action"], canonical_date=row["canonical_date"],
        date_precision=row["date_precision"], lifecycle_status=row["lifecycle_status"],
        domain=row["domain"], entity=row["entity"], title=row["title"], summary=row["summary"],
        stage=row["stage"], review_status=row["review_status"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def create_canonical_event(
    conn: DBConnection,
    *,
    company_id: int,
    event_type: str,
    subject: str | None,
    action: str | None,
    canonical_date: str | None,
    date_precision: str,
    lifecycle_status: str,
    domain: str | None,
    entity: str | None,
    title: str,
    summary: str | None,
    review_status: str,
) -> CanonicalEvent:
    now = _now()
    cur = conn.execute(
        """
        INSERT INTO canonical_events
            (company_id, event_type, subject, action, canonical_date, date_precision,
             lifecycle_status, domain, entity, title, summary, stage, review_status,
             created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, %s)
        RETURNING id
        """,
        (
            company_id, event_type, subject, action, canonical_date, date_precision,
            lifecycle_status, domain, entity, title, summary, review_status, now, now,
        ),
    )
    return get_canonical_event(conn, cur.fetchone()["id"])


def get_canonical_event(conn: DBConnection, canonical_event_id: int) -> CanonicalEvent:
    row = conn.execute("SELECT * FROM canonical_events WHERE id = %s", (canonical_event_id,)).fetchone()
    if row is None:
        raise KeyError(f"No canonical_event with id {canonical_event_id}")
    return _row_to_canonical_event(row)


def set_canonical_event_stage(conn: DBConnection, canonical_event_id: int, stage: str | None) -> None:
    conn.execute(
        "UPDATE canonical_events SET stage = %s, updated_at = %s WHERE id = %s",
        (stage, _now(), canonical_event_id),
    )


def update_canonical_event_title(conn: DBConnection, canonical_event_id: int, title: str) -> None:
    conn.execute(
        "UPDATE canonical_events SET title = %s, updated_at = %s WHERE id = %s",
        (title, _now(), canonical_event_id),
    )


def merge_canonical_events(conn: DBConnection, keep_id: int, remove_id: int, relationship_id: int | None = None) -> None:
    """Fold `remove_id` into `keep_id` after a same_event decision made
    *between two already-created canonical events* - a case the original
    clustering pass never checked, since it only compares a new raw event
    against existing canonical seeds (see dedupe_canonical_events.py for why
    that misses duplicates tagged with different entity/domain values).

    Moves raw-event membership and thread membership over to `keep_id`, drops
    now-redundant relationship rows, and deletes `remove_id`.
    """
    conn.execute(
        "UPDATE event_cluster_members SET canonical_event_id = %s WHERE canonical_event_id = %s",
        (keep_id, remove_id),
    )
    # Both events may already sit in the same thread - drop remove_id's row
    # there first so re-pointing the rest doesn't violate the
    # UNIQUE(thread_id, canonical_event_id) constraint.
    conn.execute(
        """
        DELETE FROM thread_events te
        WHERE te.canonical_event_id = %s
          AND EXISTS (
            SELECT 1 FROM thread_events te2
            WHERE te2.thread_id = te.thread_id AND te2.canonical_event_id = %s
          )
        """,
        (remove_id, keep_id),
    )
    conn.execute(
        "UPDATE thread_events SET canonical_event_id = %s WHERE canonical_event_id = %s",
        (keep_id, remove_id),
    )
    # Relationship rows are per-pair LLM decision logs, not load-bearing after
    # a merge - simplest to drop any referencing the removed id rather than
    # risk a UNIQUE(canonical_event_a_id, canonical_event_b_id) collision.
    # thread_events.relationship_id can point at one of these rows, so null
    # that out first or the delete below hits a foreign-key violation.
    conn.execute(
        """
        UPDATE thread_events SET relationship_id = NULL
        WHERE relationship_id IN (
            SELECT id FROM canonical_event_relationships
            WHERE canonical_event_a_id = %s OR canonical_event_b_id = %s
        )
        """,
        (remove_id, remove_id),
    )
    conn.execute("DELETE FROM canonical_event_relationships WHERE canonical_event_a_id = %s OR canonical_event_b_id = %s", (remove_id, remove_id))
    conn.execute("DELETE FROM canonical_events WHERE id = %s", (remove_id,))
    write_audit(
        conn, table_name="canonical_events", record_id=remove_id, action="merge",
        actor="system:dedupe", before={"id": remove_id},
        after={"merged_into": keep_id, "relationship_id": relationship_id},
    )


def list_canonical_events(
    conn: DBConnection,
    company_id: int,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[CanonicalEvent]:
    query = "SELECT * FROM canonical_events WHERE company_id = %s"
    params: list = [company_id]
    if date_from:
        query += " AND (canonical_date IS NULL OR canonical_date >= %s)"
        params.append(date_from)
    if date_to:
        query += " AND (canonical_date IS NULL OR canonical_date <= %s)"
        params.append(date_to)
    query += " ORDER BY canonical_date"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_canonical_event(r) for r in rows]


def add_cluster_member(
    conn: DBConnection,
    *,
    canonical_event_id: int,
    event_id: int,
    is_seed: bool,
    relationship_id: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO event_cluster_members (canonical_event_id, event_id, is_seed, relationship_id)
        VALUES (%s, %s, %s, %s)
        """,
        (canonical_event_id, event_id, is_seed, relationship_id),
    )


def get_canonical_event_for_event(conn: DBConnection, event_id: int) -> CanonicalEvent | None:
    row = conn.execute(
        """
        SELECT ce.* FROM canonical_events ce
        JOIN event_cluster_members m ON m.canonical_event_id = ce.id
        WHERE m.event_id = %s
        """,
        (event_id,),
    ).fetchone()
    return _row_to_canonical_event(row) if row is not None else None


def list_unclustered_events(conn: DBConnection, company_id: int) -> list[Event]:
    rows = conn.execute(
        """
        SELECT e.* FROM events e
        JOIN chunks c ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        JOIN evidence_spans ev ON ev.event_id = e.id
        LEFT JOIN event_cluster_members m ON m.event_id = e.id
        WHERE d.company_id = %s AND ev.is_valid = TRUE AND m.id IS NULL
        ORDER BY e.event_date
        """,
        (company_id,),
    ).fetchall()
    return [_row_to_event(r) for r in rows]


def canonical_event_has_official_source(conn: DBConnection, canonical_event_id: int) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM event_cluster_members m
        JOIN events e ON e.id = m.event_id
        JOIN chunks c ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        WHERE m.canonical_event_id = %s AND d.is_official = TRUE
        LIMIT 1
        """,
        (canonical_event_id,),
    ).fetchone()
    return row is not None


def list_official_source_canonical_event_ids(conn: DBConnection, company_id: int) -> set[int]:
    """Bulk version of canonical_event_has_official_source - one query for
    the whole company instead of one query per canonical event. The timeline
    page's "official sources only" filter calling the single-id version in a
    per-row loop was the N+1 query pattern that made it take forever with a
    remote (Supabase) connection once there were hundreds of events."""
    rows = conn.execute(
        """
        SELECT DISTINCT m.canonical_event_id FROM event_cluster_members m
        JOIN events e ON e.id = m.event_id
        JOIN chunks c ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        JOIN canonical_events ce ON ce.id = m.canonical_event_id
        WHERE ce.company_id = %s AND d.is_official = TRUE
        """,
        (company_id,),
    ).fetchall()
    return {row["canonical_event_id"] for row in rows}


def list_threads_by_canonical_event(conn: DBConnection, company_id: int) -> dict[int, list[Thread]]:
    """Bulk version of list_threads_for_canonical_event - one query for the
    whole company instead of one query per row on the timeline page."""
    rows = conn.execute(
        """
        SELECT te.canonical_event_id AS _canonical_event_id, t.* FROM thread_events te
        JOIN threads t ON t.id = te.thread_id
        WHERE t.company_id = %s
        """,
        (company_id,),
    ).fetchall()
    result: dict[int, list[Thread]] = {}
    for row in rows:
        result.setdefault(row["_canonical_event_id"], []).append(_row_to_thread(row))
    return result


def list_canonical_event_seed_events(conn: DBConnection, company_id: int) -> list[tuple[CanonicalEvent, Event]]:
    rows = conn.execute(
        """
        SELECT ce.*, e.id as event_id_dup FROM canonical_events ce
        JOIN event_cluster_members m ON m.canonical_event_id = ce.id AND m.is_seed = TRUE
        JOIN events e ON e.id = m.event_id
        WHERE ce.company_id = %s
        """,
        (company_id,),
    ).fetchall()
    result = []
    for row in rows:
        ce = _row_to_canonical_event(row)
        event = get_event(conn, row["event_id_dup"])
        result.append((ce, event))
    return result


# --------------------------------------------------------------------- threads

def _row_to_thread(row: dict) -> Thread:
    return Thread(
        id=row["id"], company_id=row["company_id"], title=row["title"],
        domain=row["domain"], entity=row["entity"], review_status=row["review_status"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_thread_event(row: dict) -> ThreadEvent:
    return ThreadEvent(
        id=row["id"], thread_id=row["thread_id"], canonical_event_id=row["canonical_event_id"],
        sequence_index=row["sequence_index"], stage=row["stage"], relationship_id=row["relationship_id"],
    )


def create_thread(
    conn: DBConnection,
    *,
    company_id: int,
    title: str,
    domain: str | None,
    entity: str | None,
    review_status: str,
) -> Thread:
    now = _now()
    cur = conn.execute(
        """
        INSERT INTO threads (company_id, title, domain, entity, review_status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (company_id, title, domain, entity, review_status, now, now),
    )
    row = conn.execute("SELECT * FROM threads WHERE id = %s", (cur.fetchone()["id"],)).fetchone()
    return _row_to_thread(row)


def get_thread(conn: DBConnection, thread_id: int) -> Thread:
    row = conn.execute("SELECT * FROM threads WHERE id = %s", (thread_id,)).fetchone()
    if row is None:
        raise KeyError(f"No thread with id {thread_id}")
    return _row_to_thread(row)


def list_threads(conn: DBConnection, company_id: int) -> list[Thread]:
    rows = conn.execute("SELECT * FROM threads WHERE company_id = %s", (company_id,)).fetchall()
    return [_row_to_thread(r) for r in rows]


def update_thread_title(conn: DBConnection, thread_id: int, title: str) -> None:
    conn.execute(
        "UPDATE threads SET title = %s, updated_at = %s WHERE id = %s", (title, _now(), thread_id)
    )


def add_thread_event(
    conn: DBConnection,
    *,
    thread_id: int,
    canonical_event_id: int,
    sequence_index: int,
    stage: str | None,
    relationship_id: int | None = None,
) -> ThreadEvent:
    cur = conn.execute(
        """
        INSERT INTO thread_events (thread_id, canonical_event_id, sequence_index, stage, relationship_id)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (thread_id, canonical_event_id, sequence_index, stage, relationship_id),
    )
    conn.execute("UPDATE threads SET updated_at = %s WHERE id = %s", (_now(), thread_id))
    row = conn.execute("SELECT * FROM thread_events WHERE id = %s", (cur.fetchone()["id"],)).fetchone()
    return _row_to_thread_event(row)


def list_thread_events(conn: DBConnection, thread_id: int) -> list[ThreadEvent]:
    rows = conn.execute(
        "SELECT * FROM thread_events WHERE thread_id = %s ORDER BY sequence_index", (thread_id,)
    ).fetchall()
    return [_row_to_thread_event(r) for r in rows]


def list_thread_events_for_company(conn: DBConnection, company_id: int) -> dict[int, list[ThreadEvent]]:
    """Bulk version of list_thread_events - one query for every thread the
    company has, instead of one query per thread. The threads list page
    calling list_thread_events + get_canonical_event in a per-thread,
    per-event loop was an N+1 (nested) query pattern that made it very slow
    once there were dozens of threads with a remote (Supabase) connection."""
    rows = conn.execute(
        """
        SELECT te.* FROM thread_events te
        JOIN threads t ON t.id = te.thread_id
        WHERE t.company_id = %s
        ORDER BY te.thread_id, te.sequence_index
        """,
        (company_id,),
    ).fetchall()
    result: dict[int, list[ThreadEvent]] = {}
    for row in rows:
        result.setdefault(row["thread_id"], []).append(_row_to_thread_event(row))
    return result


def list_canonical_events_by_ids(conn: DBConnection, canonical_event_ids: list[int]) -> dict[int, CanonicalEvent]:
    """Bulk-fetch canonical events by id, keyed by id, in one query."""
    if not canonical_event_ids:
        return {}
    rows = conn.execute(
        "SELECT * FROM canonical_events WHERE id = ANY(%s)", (canonical_event_ids,)
    ).fetchall()
    return {row["id"]: _row_to_canonical_event(row) for row in rows}


def list_threads_for_canonical_event(conn: DBConnection, canonical_event_id: int) -> list[Thread]:
    rows = conn.execute(
        """
        SELECT t.* FROM threads t
        JOIN thread_events te ON te.thread_id = t.id
        WHERE te.canonical_event_id = %s
        """,
        (canonical_event_id,),
    ).fetchall()
    return [_row_to_thread(r) for r in rows]


def list_unthreaded_canonical_events(conn: DBConnection, company_id: int) -> list[CanonicalEvent]:
    rows = conn.execute(
        """
        SELECT ce.* FROM canonical_events ce
        LEFT JOIN thread_events te ON te.canonical_event_id = ce.id
        WHERE ce.company_id = %s AND te.id IS NULL
        ORDER BY ce.canonical_date
        """,
        (company_id,),
    ).fetchall()
    return [_row_to_canonical_event(r) for r in rows]


# --------------------------------------------------------------------- user JDs

def _row_to_user_jd(row: dict) -> UserJD:
    return UserJD(
        id=row["id"], company_id=row["company_id"], raw_text=row["raw_text"],
        role=row["role"], role_subtype=row["role_subtype"], domain=row["domain"],
        entities=json.loads(row["entities_json"]), tasks=json.loads(row["tasks_json"]),
        created_at=row["created_at"],
    )


def create_user_jd(
    conn: DBConnection,
    *,
    company_id: int,
    raw_text: str,
    role: str | None,
    role_subtype: str | None,
    domain: str | None,
    entities: list[str],
    tasks: list[str],
) -> UserJD:
    cur = conn.execute(
        """
        INSERT INTO user_jds
            (company_id, raw_text, role, role_subtype, domain, entities_json, tasks_json, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            company_id, raw_text, role, role_subtype, domain,
            json.dumps(entities), json.dumps(tasks), _now(),
        ),
    )
    return get_user_jd(conn, cur.fetchone()["id"])


def get_user_jd(conn: DBConnection, user_jd_id: int) -> UserJD:
    row = conn.execute("SELECT * FROM user_jds WHERE id = %s", (user_jd_id,)).fetchone()
    if row is None:
        raise KeyError(f"No user_jd with id {user_jd_id}")
    return _row_to_user_jd(row)


# ----------------------------------------------------------------- audit log

def write_audit(
    conn: DBConnection,
    *,
    table_name: str,
    record_id: int,
    action: str,
    actor: str,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_log (table_name, record_id, action, actor, before_json, after_json, occurred_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            table_name, record_id, action, actor,
            json.dumps(before) if before is not None else None,
            json.dumps(after) if after is not None else None,
            _now(),
        ),
    )
