from __future__ import annotations

from company_analyzer.db.connection import DBConnection

from fastapi import APIRouter, Depends, Query, Request

from company_analyzer.web.deps import build_timeline_rows, list_company_names, resolve_company
from company_analyzer.web.main import get_db, templates

router = APIRouter()


@router.get("/")
def index(request: Request, conn: DBConnection = Depends(get_db)):
    company = resolve_company(conn, None)
    return templates.TemplateResponse(
        request, "redirect.html", {"to": f"/jd-match?company={company.name}"}
    )


@router.get("/timeline")
def timeline_view(
    request: Request,
    company: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    official_only: bool = Query(default=False),
    conn: DBConnection = Depends(get_db),
):
    company_row = resolve_company(conn, company)
    rows, domains = build_timeline_rows(conn, company_row.id, domain=domain, official_only=official_only)

    return templates.TemplateResponse(
        request,
        "timeline.html",
        {
            "company_name": company_row.name,
            "companies": list_company_names(conn),
            "active_tab": "timeline",
            "rows": rows,
            "domains": domains,
            "selected_domain": domain or "",
            "official_only": official_only,
            "related_ids": None,
            "score_by_id": {},
        },
    )
