from __future__ import annotations

from fastapi import HTTPException

from company_analyzer.db import repository as repo
from company_analyzer.db.connection import DBConnection
from company_analyzer.models import Company


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
