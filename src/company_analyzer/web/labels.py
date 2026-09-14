"""Korean display labels for internal English enum values.

The enum values themselves (review_status, stage, source_type, ...) stay in
English in the database and code - they're internal identifiers used for
comparisons and CSS classes. Only the text shown to the user is translated.
"""

from __future__ import annotations

REVIEW_STATUS_LABELS = {
    "auto_applied": "자동 적용됨",
    "auto_valid": "자동 검증됨",
    "pending": "검토 대기",
    "approved": "승인됨",
    "rejected": "거부됨",
}

STAGE_LABELS = {
    "announce": "발표",
    "build": "구축",
    "pilot": "파일럿",
    "launch": "출시",
    "scale": "확장",
}

SOURCE_TYPE_LABELS = {
    "dart": "공시(DART)",
    "ir": "IR 자료",
    "press_release": "보도자료",
    "tech_blog": "기술 블로그",
    "ceo_letter": "CEO 서한",
    "news": "뉴스",
}

MATCH_METHOD_LABELS = {
    "exact": "정확히 일치",
    "fuzzy_rapidfuzz": "유사 일치",
    "rejected": "불일치",
}


def review_status_label(value: str | None) -> str:
    return REVIEW_STATUS_LABELS.get(value or "", value or "")


def stage_label(value: str | None) -> str:
    return STAGE_LABELS.get(value or "", "-")


def source_type_label(value: str | None) -> str:
    return SOURCE_TYPE_LABELS.get(value or "", value or "")


def match_method_label(value: str | None) -> str:
    return MATCH_METHOD_LABELS.get(value or "", value or "")


def format_date(value: str | None, precision: str | None = None) -> str:
    """Render a canonical_date according to how precise the source text
    actually was - two events that both only had *year* precision and got
    normalized to the same Jan 1 default otherwise look like a suspicious
    same-day coincidence when shown as full dates."""
    if not value:
        return "날짜 미상"
    parts = value[:10].split("-")
    if len(parts) != 3:
        return value
    year, month, day = parts
    try:
        month_i, day_i = int(month), int(day)
    except ValueError:
        return value
    if precision == "year":
        return f"{year}년"
    if precision == "quarter":
        quarter = (month_i - 1) // 3 + 1
        return f"{year}년 {quarter}분기"
    if precision == "month":
        return f"{year}년 {month_i}월"
    return f"{year}년 {month_i}월 {day_i}일"
