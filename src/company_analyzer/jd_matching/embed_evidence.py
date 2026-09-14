from __future__ import annotations

from company_analyzer.db import repository as repo
from company_analyzer.db.connection import DBConnection
from company_analyzer.llm.base import LLMProvider

# One request per batch keeps this fast without risking an overlong payload -
# a few hundred short evidence quotes comfortably fits in one call, but this
# caps it so a much larger corpus (e.g. after the 3-year DART extension)
# still makes bounded-size requests.
EMBED_BATCH_SIZE = 100


def backfill_evidence_embeddings(conn: DBConnection, company_id: int, provider: LLMProvider) -> int:
    """Embed every valid evidence span that doesn't have an embedding yet.
    Safe to rerun - already-embedded spans are skipped, so this only ever
    pays for genuinely new evidence (e.g. after the background DART/thread
    pipeline adds more)."""
    spans = repo.list_valid_evidence_missing_embedding(conn, company_id)
    count = 0
    for i in range(0, len(spans), EMBED_BATCH_SIZE):
        batch = spans[i : i + EMBED_BATCH_SIZE]
        texts = [span.matched_text or span.raw_quote for span in batch]
        vectors = provider.embed(texts)
        for span, vector in zip(batch, vectors):
            repo.set_evidence_embedding(conn, span.id, vector)
            count += 1
        conn.commit()
    return count
