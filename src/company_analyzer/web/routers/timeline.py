from __future__ import annotations

from company_analyzer.db.connection import DBConnection

from fastapi import APIRouter, Depends, Query, Request

from company_analyzer.db import repository as repo
from company_analyzer.timeline.build_timeline import build_timeline
from company_analyzer.web.deps import list_company_names, resolve_company
from company_analyzer.web.main import get_db, templates
from company_analyzer.web.routers.jd_match import SAMPLE_JDS

router = APIRouter()


@router.get("/")
def index(request: Request, conn: DBConnection = Depends(get_db)):
    company = resolve_company(conn, None)
    return templates.TemplateResponse(
        request, "redirect.html", {"to": f"/timeline?company={company.name}"}
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
    events = build_timeline(conn, company_row.id)

    # Bulk-fetched once per request instead of once per row - see
    # list_official_source_canonical_event_ids/list_threads_by_canonical_event
    # docstrings for why the old per-row queries made this page very slow.
    official_ids = repo.list_official_source_canonical_event_ids(conn, company_row.id) if official_only else None
    threads_by_event = repo.list_threads_by_canonical_event(conn, company_row.id)

    rows = []
    for ce in events:
        if domain and (ce.domain or "").lower() != domain.lower():
            continue
        if official_only and ce.id not in official_ids:
            continue
        rows.append({"event": ce, "threads": threads_by_event.get(ce.id, [])})

    domains = sorted({ce.domain for ce in events if ce.domain})

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
            "presets": SAMPLE_JDS,
            "active_preset": None,
            "jd": None,
            "candidates": None,
            "error": None,
        },
    )
