from __future__ import annotations

from company_analyzer.db.connection import DBConnection

from company_analyzer.db import repository as repo
from company_analyzer.llm.base import LLMProvider
from company_analyzer.models import Event
from company_analyzer.relationships.apply import is_auto_apply
from company_analyzer.relationships.candidate_pairs import find_top_candidates
from company_analyzer.relationships.classifier import classify_event_pair

DATE_WINDOW_DAYS = 30


def _title_for(event: Event) -> str:
    label = event.entity or event.subject or event.event_type
    action = event.action or event.event_type
    return f"{label}: {action}" if label and label != action else action


def cluster_new_events(conn: DBConnection, company_id: int, provider: LLMProvider) -> dict:
    """Greedy incremental clustering: process unclustered events oldest-first,
    comparing each against the seed event of every existing canonical event
    (bounded by the date/entity/domain pre-filter). A same_event match at or
    above threshold merges; otherwise the event becomes its own standalone
    canonical event, flagged for review if an uncertain relationship was
    found (a human can later approve a merge via the review workflow).

    Order-dependent by design (documented Phase 1 simplification).

    Commits after every event rather than once for the whole batch: a real
    run over hundreds of events hung on a dropped pooler connection after
    running for 90+ minutes, and losing the entire batch's already-paid-for
    LLM classification work to one rollback is worse than the small risk of
    committing a merge decision the rest of the batch never gets applied on
    top of.
    """
    counts = {"new_canonical": 0, "merged": 0, "flagged_for_review": 0, "deferred_news_event": 0}
    unclustered = repo.list_unclustered_events(conn, company_id)

    for event in unclustered:
        seeds = repo.list_canonical_event_seed_events(conn, company_id)
        canonical_by_seed_event_id = {seed_event.id: canonical_event for canonical_event, seed_event in seeds}
        seed_events = [seed_event for _canonical_event, seed_event in seeds]
        top_seed_events = find_top_candidates(
            event, seed_events, lambda e: e.event_date, lambda e: e.entity, lambda e: e.domain, DATE_WINDOW_DAYS
        )

        best_relationship = None
        best_canonical_event = None
        had_uncertain_match = False

        for seed_event in top_seed_events:
            canonical_event = canonical_by_seed_event_id[seed_event.id]
            relationship = classify_event_pair(conn, provider, event, seed_event)
            if relationship.relationship_type != "same_event":
                continue
            if best_relationship is None or relationship.confidence > best_relationship.confidence:
                best_relationship = relationship
                best_canonical_event = canonical_event
            if not is_auto_apply(relationship.relationship_type, relationship.confidence):
                had_uncertain_match = True

        if best_relationship is not None and is_auto_apply("same_event", best_relationship.confidence):
            repo.set_relationship_review_status(conn, best_relationship.id, "auto_applied")
            repo.add_cluster_member(
                conn, canonical_event_id=best_canonical_event.id, event_id=event.id,
                is_seed=False, relationship_id=best_relationship.id,
            )
            counts["merged"] += 1
            conn.commit()
            continue

        if not repo.is_event_official(conn, event.id):
            # News is context enrichment only: it may join an existing cluster
            # (handled above) but must never seed a new canonical event. Leave
            # it unclustered - a later official event or human review can
            # still pull it in.
            counts["deferred_news_event"] += 1
            conn.commit()
            continue

        review_status = "pending" if had_uncertain_match else "auto_applied"
        canonical_event = repo.create_canonical_event(
            conn, company_id=company_id, event_type=event.event_type, subject=event.subject,
            action=event.action, canonical_date=event.event_date, date_precision=event.date_precision,
            lifecycle_status=event.lifecycle_status, domain=event.domain, entity=event.entity,
            title=_title_for(event), summary=event.raw_quote, review_status=review_status,
        )
        repo.add_cluster_member(conn, canonical_event_id=canonical_event.id, event_id=event.id, is_seed=True)
        counts["new_canonical"] += 1
        if review_status == "pending":
            counts["flagged_for_review"] += 1
        conn.commit()

    return counts
