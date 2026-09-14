from __future__ import annotations

import json
from company_analyzer.db.connection import DBConnection

from company_analyzer.db import repository as repo
from company_analyzer.llm.base import PROMPT_VERSION, LLMProvider
from company_analyzer.models import Chunk, Event


def run_extraction(conn: DBConnection, chunk: Chunk, provider: LLMProvider, metadata: dict) -> list[Event]:
    candidates = provider.extract_events(chunk.text, metadata)
    events = []
    for candidate in candidates:
        event = repo.insert_event(
            conn,
            chunk_id=chunk.id,
            candidate=candidate,
            extraction_model=provider.name,
            prompt_version=PROMPT_VERSION,
            llm_raw_response_json=json.dumps(candidate.__dict__),
        )
        events.append(event)
    return events


def extract_pending_chunks(conn: DBConnection, company_id: int, provider: LLMProvider) -> int:
    """Run extraction on every chunk for this company that has no events yet.

    Commits after every chunk rather than once for the whole batch - the same
    incremental-commit pattern clustering/threading already use, for the same
    reason: a real run over hundreds of chunks each requiring a live GPT call
    holds a single transaction open for a long time otherwise, which both
    risks losing an entire batch's already-paid-for extraction work to one
    failure/rollback, and (found in practice) can hold locks long enough to
    make other concurrent commands' schema-init DDL time out.
    """
    chunks = repo.list_unextracted_chunks(conn, company_id)
    total = 0
    for chunk in chunks:
        document = repo.get_document(conn, chunk.document_id)
        metadata = {
            "company": repo.get_company_by_id(conn, company_id).name,
            "source_type": document.source_type,
            "published_date": document.published_date,
            "heading": chunk.heading,
        }
        events = run_extraction(conn, chunk, provider, metadata)
        total += len(events)
        conn.commit()
    return total
