from __future__ import annotations

from company_analyzer.db.connection import DBConnection

from fastapi import APIRouter, Depends, Query, Request

from company_analyzer.db import repository as repo
from company_analyzer.web.deps import list_company_names, resolve_company
from company_analyzer.web.main import get_db, templates

router = APIRouter()


@router.get("/threads")
def threads_list(
    request: Request,
    company: str | None = Query(default=None),
    conn: DBConnection = Depends(get_db),
):
    company_row = resolve_company(conn, company)

    # Bulk-fetched once per request instead of once per thread (and once per
    # event within each thread) - see list_thread_events_for_company's
    # docstring for why the old nested per-thread queries made this page
    # very slow once there were dozens of threads.
    thread_events_by_thread = repo.list_thread_events_for_company(conn, company_row.id)
    all_canonical_event_ids = [
        te.canonical_event_id for tes in thread_events_by_thread.values() for te in tes
    ]
    canonical_events_by_id = repo.list_canonical_events_by_ids(conn, all_canonical_event_ids)

    threads = []
    for thread in repo.list_threads(conn, company_row.id):
        thread_events = thread_events_by_thread.get(thread.id, [])
        events = [canonical_events_by_id[te.canonical_event_id] for te in thread_events]
        dated = sorted((e for e in events if e.canonical_date), key=lambda e: e.canonical_date)
        span_start = dated[0] if dated else None
        span_end = dated[-1] if dated else None
        threads.append(
            {"thread": thread, "count": len(thread_events), "span_start": span_start, "span_end": span_end}
        )

    return templates.TemplateResponse(
        request,
        "threads.html",
        {
            "company_name": company_row.name,
            "companies": list_company_names(conn),
            "active_tab": "threads",
            "threads": threads,
        },
    )


@router.get("/threads/{thread_id}")
def thread_detail(request: Request, thread_id: int, conn: DBConnection = Depends(get_db)):
    thread = repo.get_thread(conn, thread_id)
    thread_events = repo.list_thread_events(conn, thread_id)
    canonical_events_by_id = repo.list_canonical_events_by_ids(
        conn, [te.canonical_event_id for te in thread_events]
    )
    members = [
        {"thread_event": te, "canonical_event": canonical_events_by_id[te.canonical_event_id]}
        for te in thread_events
    ]

    company = repo.get_company_by_id(conn, thread.company_id)
    return templates.TemplateResponse(
        request,
        "thread_detail.html",
        {
            "company_name": company.name,
            "companies": list_company_names(conn),
            "active_tab": "threads",
            "thread": thread,
            "members": members,
        },
    )
