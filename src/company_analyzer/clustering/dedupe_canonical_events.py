from __future__ import annotations

from datetime import date

from rapidfuzz import fuzz

from company_analyzer.db.connection import DBConnection
from company_analyzer.db import repository as repo
from company_analyzer.llm.base import LLMProvider
from company_analyzer.models import CanonicalEvent
from company_analyzer.relationships.apply import is_auto_apply
from company_analyzer.relationships.classifier import classify_canonical_event_pair

# rapidfuzz token_sort_ratio, 0-100. The original clustering pass only
# compares a new raw event against existing canonical seeds sharing an
# entity or domain value (relationships/candidate_pairs.py) - two events
# describing the same real thing but tagged with different entity/domain
# text (e.g. "카카오" vs "KOSDAQ" for the same 1999 listing) never get
# compared at all, so the duplicate never even reaches the LLM. This module
# re-checks every canonical event against every other one using title/summary
# text similarity instead, which catches exactly that failure mode.
TITLE_SIMILARITY_THRESHOLD = 55
DATE_WINDOW_DAYS = 3


def _dates_close(a: str | None, b: str | None, window_days: int) -> bool:
    if a is None or b is None:
        return a == b
    try:
        da, db = date.fromisoformat(a[:10]), date.fromisoformat(b[:10])
    except ValueError:
        return a[:10] == b[:10]
    return abs((da - db).days) <= window_days


def find_duplicate_candidates(events: list[CanonicalEvent]) -> list[tuple[CanonicalEvent, CanonicalEvent]]:
    """Cheap, LLM-free prefilter: pure string similarity + a loose date
    window. Quadratic in event count, but rapidfuzz over short titles is fast
    enough at this data scale (hundreds, not millions) - the expensive part
    (the LLM call) only runs for pairs this returns."""
    pairs = []
    for i in range(len(events)):
        for j in range(i + 1, len(events)):
            a, b = events[i], events[j]
            if not _dates_close(a.canonical_date, b.canonical_date, DATE_WINDOW_DAYS):
                continue
            title_score = fuzz.token_sort_ratio(a.title or "", b.title or "")
            summary_score = fuzz.token_sort_ratio(a.summary or "", b.summary or "")
            if max(title_score, summary_score) >= TITLE_SIMILARITY_THRESHOLD:
                pairs.append((a, b))
    return pairs


def dedupe_canonical_events(conn: DBConnection, company_id: int, provider: LLMProvider) -> dict:
    """One-off cleanup pass over *already-created* canonical events, for
    duplicates the original clustering pass's entity/domain prefilter missed.
    Safe to re-run - candidates are always re-derived from current data."""
    counts = {"candidates": 0, "checked": 0, "merged": 0}
    events = repo.list_canonical_events(conn, company_id)
    candidates = find_duplicate_candidates(events)
    counts["candidates"] = len(candidates)

    removed: set[int] = set()
    for a, b in candidates:
        if a.id in removed or b.id in removed:
            continue
        counts["checked"] += 1
        relationship = classify_canonical_event_pair(conn, provider, a, b)
        if relationship.relationship_type != "same_event" or not is_auto_apply("same_event", relationship.confidence):
            conn.commit()
            continue

        keep, remove = (a, b) if a.id < b.id else (b, a)
        repo.merge_canonical_events(conn, keep_id=keep.id, remove_id=remove.id, relationship_id=relationship.id)
        removed.add(remove.id)
        counts["merged"] += 1
        conn.commit()

    return counts
