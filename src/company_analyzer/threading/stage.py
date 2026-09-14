from __future__ import annotations

_STAGE_KEYWORDS: dict[str, list[str]] = {
    "announce": ["announce", "unveil", "reveal", "plan to", "strategy_announcement"],
    "build": ["develop", "build", "invest", "product_development"],
    "pilot": ["pilot", "trial", "test with", "pilot_program"],
    "launch": ["launch", "release", "roll out", "open to the public", "open to public", "product_launch"],
    "scale": ["expand", "scale", "global rollout", "reach", "expansion"],
}

STAGE_ORDER = ["announce", "build", "pilot", "launch", "scale"]


def infer_stage(action: str | None, event_type: str | None = None) -> str | None:
    """Keyword-family lookup. Actions that match no family get no stage
    (documented Phase 1 limitation - reduces threading recall for real
    extraction output whose vocabulary doesn't match these families)."""
    text = " ".join(filter(None, [action, event_type])).lower()
    if not text:
        return None
    for stage, keywords in _STAGE_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return stage
    return None


def stage_index(stage: str | None) -> int | None:
    return STAGE_ORDER.index(stage) if stage in STAGE_ORDER else None


def is_forward_progression(stage_a: str | None, stage_b: str | None) -> bool:
    ia, ib = stage_index(stage_a), stage_index(stage_b)
    if ia is None or ib is None:
        return False
    return ib > ia
