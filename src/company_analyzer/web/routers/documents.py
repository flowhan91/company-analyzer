from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from company_analyzer.db import repository as repo
from company_analyzer.db.connection import DBConnection
from company_analyzer.web.deps import list_company_names
from company_analyzer.web.main import get_db, templates

router = APIRouter()


@router.get("/documents/for-event/{canonical_event_id}")
def evidence_for_canonical_event(request: Request, canonical_event_id: int, conn: DBConnection = Depends(get_db)):
    canonical_event = repo.get_canonical_event(conn, canonical_event_id)
    company = repo.get_company_by_id(conn, canonical_event.company_id)

    members = conn.execute(
        "SELECT event_id, is_seed FROM event_cluster_members WHERE canonical_event_id = %s",
        (canonical_event_id,),
    ).fetchall()

    evidence_items = []
    for row in members:
        event = repo.get_event(conn, row["event_id"])
        span = repo.get_evidence_for_event(conn, event.id)
        chunk = repo.get_chunk(conn, event.chunk_id)
        document = repo.get_document(conn, chunk.document_id)
        evidence_items.append(
            {
                "is_seed": bool(row["is_seed"]),
                "event": event,
                "evidence": span,
                "document": document,
            }
        )

    return templates.TemplateResponse(
        request,
        "document.html",
        {
            "company_name": company.name,
            "companies": list_company_names(conn),
            "active_tab": "timeline",
            "canonical_event": canonical_event,
            "evidence_items": evidence_items,
        },
    )
