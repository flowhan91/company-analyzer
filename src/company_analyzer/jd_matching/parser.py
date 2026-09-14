from __future__ import annotations

from company_analyzer.db import repository as repo
from company_analyzer.db.connection import DBConnection
from company_analyzer.llm.base import LLMProvider
from company_analyzer.models import UserJD


def parse_and_store_jd(conn: DBConnection, company_id: int, raw_text: str, provider: LLMProvider) -> UserJD:
    """One LLM call: pasted JD text -> role/domain/tasks/entities, stored as
    a user_jds row. `entities` and `skills` are merged (dedup, order-preserving)
    into the single entities_json column - the schema doesn't need a separate
    column just to distinguish "mentioned" from "required" technologies."""
    parsed = provider.parse_job_description(raw_text)
    tasks = [t for t in parsed.get("tasks", []) if t and t.strip()]

    seen: set[str] = set()
    entities: list[str] = []
    for value in [*parsed.get("entities", []), *parsed.get("skills", [])]:
        if not value or not value.strip():
            continue
        key = value.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        entities.append(value.strip())

    return repo.create_user_jd(
        conn,
        company_id=company_id,
        raw_text=raw_text,
        role=parsed.get("role"),
        role_subtype=parsed.get("role_subtype"),
        domain=parsed.get("domain"),
        entities=entities,
        tasks=tasks,
    )
