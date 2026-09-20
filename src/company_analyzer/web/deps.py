from __future__ import annotations

from fastapi import HTTPException

from company_analyzer.db import repository as repo
from company_analyzer.db.connection import DBConnection
from company_analyzer.models import Company
from company_analyzer.timeline.build_timeline import build_timeline


def resolve_company(conn: DBConnection, company_name: str | None) -> Company:
    if company_name:
        company = repo.get_company_by_name(conn, company_name)
        if company is None:
            raise HTTPException(status_code=404, detail=f"'{company_name}' 기업을 찾을 수 없습니다")
        return company
    row = conn.execute("SELECT * FROM companies ORDER BY id LIMIT 1").fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="아직 수집된 기업이 없습니다. 먼저 `cana ingest-manual`을 실행하세요.")
    return repo.get_company_by_id(conn, row["id"])


def list_company_names(conn: DBConnection) -> list[str]:
    rows = conn.execute("SELECT name FROM companies ORDER BY name").fetchall()
    return [r["name"] for r in rows]


def build_timeline_rows(
    conn: DBConnection,
    company_id: int,
    domain: str | None = None,
    official_only: bool = False,
) -> tuple[list[dict], list[str]]:
    """Shared by the timeline page and the JD-match sidebar (which re-renders
    the same rows, annotated with match info, as an HTMX out-of-band swap) -
    kept in one place so the two never drift apart on filtering/threading."""
    events = build_timeline(conn, company_id)

    official_ids = repo.list_official_source_canonical_event_ids(conn, company_id) if official_only else None
    threads_by_event = repo.list_threads_by_canonical_event(conn, company_id)

    rows = []
    for ce in events:
        if domain and (ce.domain or "").lower() != domain.lower():
            continue
        if official_only and ce.id not in official_ids:
            continue
        rows.append({"event": ce, "threads": threads_by_event.get(ce.id, [])})

    domains = sorted({ce.domain for ce in events if ce.domain})
    return rows, domains
