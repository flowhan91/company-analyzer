from __future__ import annotations

from dataclasses import dataclass

from company_analyzer.relationships.candidate_pairs import find_candidate_pairs, find_top_candidates, is_candidate_pair


@dataclass
class FakeEvent:
    event_date: str | None
    entity: str | None
    domain: str | None


def _pair(a: FakeEvent, b: FakeEvent, window_days: int = 30) -> bool:
    return is_candidate_pair(a, b, lambda e: e.event_date, lambda e: e.entity, lambda e: e.domain, window_days)


def test_entity_match_uses_full_window_even_far_apart():
    a = FakeEvent("2025-01-01", "HyperCLOVA X", "AI")
    b = FakeEvent("2025-01-20", "HyperCLOVA X", "AI")
    assert _pair(a, b, window_days=30) is True


def test_entity_match_allowed_even_without_parseable_dates():
    a = FakeEvent(None, "HyperCLOVA X", "AI")
    b = FakeEvent("unparseable", "HyperCLOVA X", "AI")
    assert _pair(a, b) is True


def test_domain_only_match_requires_tight_date_proximity():
    """Regression test: a real clustering run over 379 events, many sharing
    generic domains like 'AI' across a ~6 month window, produced far more LLM
    calls than intended (O(k^2) per domain cluster) and the run never
    finished. Domain-only matches must not bypass a tight date check."""
    close = FakeEvent("2025-06-01", None, "AI")
    close_match = FakeEvent("2025-06-02", None, "AI")
    assert _pair(close, close_match, window_days=30) is True

    far = FakeEvent("2025-06-01", None, "AI")
    far_match = FakeEvent("2025-06-20", None, "AI")
    assert _pair(far, far_match, window_days=30) is False


def test_domain_only_match_requires_parseable_dates_on_both_sides():
    a = FakeEvent(None, None, "AI")
    b = FakeEvent("2025-06-01", None, "AI")
    assert _pair(a, b) is False


def test_no_entity_or_domain_overlap_is_never_a_candidate():
    a = FakeEvent("2025-06-01", "Product X", "search")
    b = FakeEvent("2025-06-01", "Product Y", "commerce")
    assert _pair(a, b) is False


def test_find_top_candidates_caps_generic_entity_matches():
    """Regression test: real data had entities like "NAVER" and "stock
    options" (case variants) shared by 5-11 events each, none capped by the
    date window since entity matches bypass it - a real clustering run kept
    slowing down as the seed pool grew because every one of those matches
    triggered a real LLM call, unbounded. find_top_candidates must cap the
    count regardless of how generic/frequent the matching entity is."""
    target = FakeEvent("2025-06-15", "NAVER", "finance")
    # 30 events sharing the same generic entity, spread across the window.
    candidates = [FakeEvent(f"2025-06-{(i % 28) + 1:02d}", "NAVER", "finance") for i in range(30)]
    top = find_top_candidates(
        target, candidates, lambda e: e.event_date, lambda e: e.entity, lambda e: e.domain,
        window_days=30, max_candidates=10,
    )
    assert len(top) == 10


def test_find_top_candidates_prioritizes_closest_dates():
    target = FakeEvent("2025-06-15", "HyperCLOVA X", "AI")
    near = FakeEvent("2025-06-16", "HyperCLOVA X", "AI")
    far = FakeEvent("2025-06-01", "HyperCLOVA X", "AI")
    top = find_top_candidates(
        target, [far, near], lambda e: e.event_date, lambda e: e.entity, lambda e: e.domain,
        window_days=30, max_candidates=1,
    )
    assert top == [near]


def test_find_candidate_pairs_bounds_domain_cluster_size():
    """20 events sharing one domain, spread one day apart each, should only
    pair up neighbors within DOMAIN_ONLY_MAX_DAYS - not all-pairs."""
    events = [FakeEvent(f"2025-06-{i + 1:02d}", None, "AI") for i in range(20)]
    pairs = find_candidate_pairs(
        events, lambda e: e.event_date, lambda e: e.entity, lambda e: e.domain, window_days=30
    )
    # Each event should only pair with the ~3 neighbors within 3 days, not
    # all 19 others - this is what keeps LLM call volume bounded.
    assert len(pairs) < len(events) * 3
    assert len(pairs) > 0
