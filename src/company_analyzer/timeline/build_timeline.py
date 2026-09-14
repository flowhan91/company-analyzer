from __future__ import annotations

from company_analyzer.db.connection import DBConnection

from company_analyzer.db import repository as repo
from company_analyzer.models import CanonicalEvent


def build_timeline(
    conn: DBConnection,
    company_id: int,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[CanonicalEvent]:
    """Chronological canonical events. Clustering must have already run -
    this is a read/sort layer, not a processing step."""
    return repo.list_canonical_events(conn, company_id, date_from=date_from, date_to=date_to)
