from __future__ import annotations

from company_analyzer.db.connection import DBConnection


def list_audit_entries(conn: DBConnection, table_name: str | None = None, record_id: int | None = None) -> list[dict]:
    query = "SELECT * FROM audit_log"
    params: list = []
    clauses = []
    if table_name:
        clauses.append("table_name = %s")
        params.append(table_name)
    if record_id is not None:
        clauses.append("record_id = %s")
        params.append(record_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY occurred_at DESC"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]
