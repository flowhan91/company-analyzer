from __future__ import annotations

import math
from dataclasses import dataclass

from company_analyzer.db import repository as repo
from company_analyzer.db.connection import DBConnection
from company_analyzer.llm.base import LLMProvider
from company_analyzer.models import UserJD


class NoEmbeddedEvidenceError(RuntimeError):
    """Raised when a company has no evidence embeddings yet - run
    `cana embed-evidence` (after ingesting and clustering) first."""


class EmptyJDError(RuntimeError):
    """Raised when the JD parser extracted no usable tasks to match against."""


@dataclass(frozen=True)
class TaskEvidenceMatch:
    task: str
    evidence_text: str
    canonical_event_id: int
    canonical_event_title: str
    score: float


@dataclass(frozen=True)
class MatchCandidate:
    kind: str  # "thread" | "event"
    id: int
    title: str
    score: float
    matches: list[TaskEvidenceMatch]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def match_jd(
    conn: DBConnection, company_id: int, jd: UserJD, provider: LLMProvider, top_n: int = 3
) -> list[MatchCandidate]:
    """Rank the company's threads/standalone canonical events by relevance to
    a parsed JD's tasks, via cosine similarity between task embeddings and
    already-cached evidence embeddings.

    No LLM classification calls here (unlike clustering/threading) - this is
    pure vector math over cached embeddings, so no candidate pre-filter is
    needed to bound cost the way relationships/candidate_pairs.py bounds LLM
    calls elsewhere; brute-force comparison against every valid evidence span
    is cheap at this data scale.
    """
    if not jd.tasks:
        raise EmptyJDError("This JD had no extractable tasks to match against.")

    evidence_spans = [e for e in repo.list_valid_evidence_for_company(conn, company_id) if e.embedding]
    if not evidence_spans:
        raise NoEmbeddedEvidenceError(
            "No evidence embeddings found for this company - run `cana embed-evidence` first."
        )

    event_to_canonical = repo.list_canonical_event_id_by_event_id(conn, company_id)
    canonical_ids = sorted(set(event_to_canonical.values()))
    canonical_events_by_id = repo.list_canonical_events_by_ids(conn, canonical_ids)
    threads_by_canonical = repo.list_threads_by_canonical_event(conn, company_id)

    task_vectors = provider.embed(jd.tasks)

    best_per_canonical: dict[int, TaskEvidenceMatch] = {}
    for span in evidence_spans:
        canonical_id = event_to_canonical.get(span.event_id)
        if canonical_id is None or canonical_id not in canonical_events_by_id:
            continue  # not yet clustered into a canonical event - nothing to attach the match to
        evidence_text = span.matched_text or span.raw_quote
        for task, task_vector in zip(jd.tasks, task_vectors):
            score = _cosine(span.embedding, task_vector)
            current = best_per_canonical.get(canonical_id)
            if current is None or score > current.score:
                best_per_canonical[canonical_id] = TaskEvidenceMatch(
                    task=task,
                    evidence_text=evidence_text,
                    canonical_event_id=canonical_id,
                    canonical_event_title=canonical_events_by_id[canonical_id].title,
                    score=score,
                )

    thread_matches: dict[int, list[TaskEvidenceMatch]] = {}
    thread_titles: dict[int, str] = {}
    standalone: list[TaskEvidenceMatch] = []
    for canonical_id, match in best_per_canonical.items():
        threads = threads_by_canonical.get(canonical_id, [])
        if not threads:
            standalone.append(match)
            continue
        for thread in threads:
            thread_matches.setdefault(thread.id, []).append(match)
            thread_titles[thread.id] = thread.title

    candidates: list[MatchCandidate] = []
    for thread_id, matches in thread_matches.items():
        matches.sort(key=lambda m: m.score, reverse=True)
        candidates.append(
            MatchCandidate(kind="thread", id=thread_id, title=thread_titles[thread_id],
                            score=matches[0].score, matches=matches[:3])
        )
    for match in standalone:
        candidates.append(
            MatchCandidate(kind="event", id=match.canonical_event_id, title=match.canonical_event_title,
                            score=match.score, matches=[match])
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:top_n]
