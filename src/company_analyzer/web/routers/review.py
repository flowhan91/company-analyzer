from __future__ import annotations

from company_analyzer.db.connection import DBConnection

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from company_analyzer.review import actions, queue
from company_analyzer.web.deps import list_company_names, resolve_company
from company_analyzer.web.main import get_db, templates

router = APIRouter()

WEB_ACTOR = "web-user"


@router.get("/review")
def review_view(
    request: Request,
    company: str | None = Query(default=None),
    conn: DBConnection = Depends(get_db),
):
    company_row = resolve_company(conn, company)
    return templates.TemplateResponse(
        request,
        "review_queue.html",
        {
            "company_name": company_row.name,
            "companies": list_company_names(conn),
            "active_tab": "review",
            "evidence_items": queue.pending_evidence(conn, company_row.id),
            "duplicate_items": queue.pending_event_relationships(conn, relationship_type="same_event"),
            "thread_items": queue.pending_canonical_relationships(conn, relationship_type="related_distinct"),
        },
    )


def _done(message: str) -> HTMLResponse:
    return HTMLResponse(f'<div class="review-item"><span class="badge approved">{message}</span></div>')


@router.post("/review/evidence/{evidence_id}/approve")
def approve_evidence(evidence_id: int, conn: DBConnection = Depends(get_db)) -> HTMLResponse:
    actions.approve_evidence(conn, evidence_id, WEB_ACTOR)
    return _done("근거가 승인되었습니다")


@router.post("/review/evidence/{evidence_id}/reject")
def reject_evidence(evidence_id: int, conn: DBConnection = Depends(get_db)) -> HTMLResponse:
    actions.reject_evidence(conn, evidence_id, WEB_ACTOR)
    return _done("근거가 거부되었습니다")


@router.post("/review/duplicates/{relationship_id}/approve")
def approve_duplicate(relationship_id: int, conn: DBConnection = Depends(get_db)) -> HTMLResponse:
    canonical = actions.approve_event_relationship(conn, relationship_id, WEB_ACTOR)
    return _done(f"'{canonical.title}'(으)로 병합되었습니다")


@router.post("/review/duplicates/{relationship_id}/reject")
def reject_duplicate(relationship_id: int, conn: DBConnection = Depends(get_db)) -> HTMLResponse:
    actions.reject_event_relationship(conn, relationship_id, WEB_ACTOR)
    return _done("별개 이벤트로 유지되었습니다")


@router.post("/review/threads/{relationship_id}/approve")
def approve_thread(relationship_id: int, conn: DBConnection = Depends(get_db)) -> HTMLResponse:
    thread = actions.approve_canonical_relationship(conn, relationship_id, WEB_ACTOR)
    return _done(f"'{thread.title}' 스레드에 추가되었습니다")


@router.post("/review/threads/{relationship_id}/reject")
def reject_thread(relationship_id: int, conn: DBConnection = Depends(get_db)) -> HTMLResponse:
    actions.reject_canonical_relationship(conn, relationship_id, WEB_ACTOR)
    return _done("독립 이벤트로 유지되었습니다")
