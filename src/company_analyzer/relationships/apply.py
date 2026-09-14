from __future__ import annotations

# Conservative by design (per plan: "favor review queue over silent
# auto-apply, loosen once the reference-dataset score justifies it").
AUTO_APPLY_SAME_EVENT_THRESHOLD = 0.85
AUTO_APPLY_RELATED_THRESHOLD = 0.75


def is_auto_apply(relationship_type: str, confidence: float) -> bool:
    if relationship_type == "same_event":
        return confidence >= AUTO_APPLY_SAME_EVENT_THRESHOLD
    if relationship_type == "related_distinct":
        return confidence >= AUTO_APPLY_RELATED_THRESHOLD
    return False
