from __future__ import annotations

from datetime import date
from typing import Callable, TypeVar

T = TypeVar("T")

# A domain-only match (e.g. both events tagged "AI") is a weak signal on its
# own - a real clustering run over 379 events from documents spanning ~6
# months, many sharing generic domains, produced far more LLM-classification
# calls than intended and the run never finished. Domain-only matches are
# only worth an LLM call when the events are also very close in time; a
# shared, specific entity ("HyperCLOVA X") is a strong enough signal to use
# the full window on its own.
DOMAIN_ONLY_MAX_DAYS = 3

# Even entity matches aren't always specific: real extracted entity values
# included "NAVER" (the company's own name) and multiple casing variants of
# "stock options" - each shared by 5-11 events, none capped by the date
# window since an entity match bypasses it. As the canonical-event seed pool
# grew across a real run, comparisons against one generic entity value kept
# growing without bound and the run kept slowing down. This hard cap makes
# LLM call volume bounded per event regardless of how generic or frequent
# any single entity/domain value turns out to be in real data.
MAX_CANDIDATES_PER_ITEM = 10


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _date_proximity_days(date_a: str | None, date_b: str | None) -> int | None:
    da, db = _parse_date(date_a), _parse_date(date_b)
    if da is None or db is None:
        return None
    return abs((da - db).days)


def is_candidate_pair(
    item_a: T,
    item_b: T,
    get_date: Callable[[T], str | None],
    get_entity: Callable[[T], str | None],
    get_domain: Callable[[T], str | None],
    window_days: int,
) -> bool:
    entity_a, entity_b = get_entity(item_a), get_entity(item_b)
    domain_a, domain_b = get_domain(item_a), get_domain(item_b)
    entity_match = bool(entity_a) and bool(entity_b) and entity_a.strip().lower() == entity_b.strip().lower()
    domain_match = bool(domain_a) and bool(domain_b) and domain_a.strip().lower() == domain_b.strip().lower()

    if not entity_match and not domain_match:
        return False

    days = _date_proximity_days(get_date(item_a), get_date(item_b))

    if entity_match:
        # A specific shared entity is worth an LLM call even without a
        # parseable date on either side.
        return days is None or days <= window_days

    # Domain-only match: never bypass the date check, and use the tighter of
    # the two windows regardless of what the caller passed in.
    return days is not None and days <= min(window_days, DOMAIN_ONLY_MAX_DAYS)


def find_top_candidates(
    item: T,
    candidates: list[T],
    get_date: Callable[[T], str | None],
    get_entity: Callable[[T], str | None],
    get_domain: Callable[[T], str | None],
    window_days: int,
    max_candidates: int = MAX_CANDIDATES_PER_ITEM,
) -> list[T]:
    """Like is_candidate_pair, but bounds how many candidates come back for a
    single item, closest-in-time first. Use this (not a raw is_candidate_pair
    loop) wherever one item gets checked against a growing pool of others -
    an unbounded loop is what let a handful of generic/repeated entity or
    domain values silently balloon LLM call volume in real data."""
    passing: list[tuple[int, T]] = []
    item_date = get_date(item)
    for candidate in candidates:
        if not is_candidate_pair(item, candidate, get_date, get_entity, get_domain, window_days):
            continue
        days = _date_proximity_days(item_date, get_date(candidate))
        sort_key = days if days is not None else 10**9
        passing.append((sort_key, candidate))
    passing.sort(key=lambda pair: pair[0])
    return [candidate for _, candidate in passing[:max_candidates]]


def find_candidate_pairs(
    items: list[T],
    get_date: Callable[[T], str | None],
    get_entity: Callable[[T], str | None],
    get_domain: Callable[[T], str | None],
    window_days: int,
) -> list[tuple[T, T]]:
    """Cheap rule-based pre-filter: only pairs within a date window AND sharing
    an entity or domain get sent on to the (expensive) LLM classifier. Never
    all-pairs - this is what bounds LLM call volume."""
    pairs: list[tuple[T, T]] = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if is_candidate_pair(a, b, get_date, get_entity, get_domain, window_days):
                pairs.append((a, b))
    return pairs


def find_candidate_event_pairs(events: list, window_days: int = 30) -> list[tuple]:
    """Duplicate-detection window: tight, since duplicates of the same event
    are reported close together in time."""
    return find_candidate_pairs(
        events, lambda e: e.event_date, lambda e: e.entity, lambda e: e.domain, window_days
    )


def find_candidate_canonical_event_pairs(canonical_events: list, window_days: int = 180) -> list[tuple]:
    """Threading window: wide, since a thread's stages can span months."""
    return find_candidate_pairs(
        canonical_events, lambda e: e.canonical_date, lambda e: e.entity, lambda e: e.domain, window_days
    )
