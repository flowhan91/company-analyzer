from __future__ import annotations

from company_analyzer.web.labels import format_date


def test_format_date_missing_value():
    assert format_date(None) == "날짜 미상"


def test_format_date_year_precision():
    assert format_date("2020-01-01", "year") == "2020년"


def test_format_date_quarter_precision():
    assert format_date("2025-04-01", "quarter") == "2025년 2분기"


def test_format_date_month_precision():
    assert format_date("2025-07-01", "month") == "2025년 7월"


def test_format_date_day_precision():
    assert format_date("2025-07-15", "day") == "2025년 7월 15일"


def test_format_date_unknown_precision_falls_back_to_full_date():
    assert format_date("2025-07-15", "unknown") == "2025년 7월 15일"


def test_format_date_distinguishes_year_precision_same_default_date():
    """Regression: two events that both only had year precision in the
    source normalize to the same Jan 1 default date - shown as full dates
    they look like a suspicious same-day coincidence. Both still render
    identically here (both are genuinely year-only), which is correct; the
    point is they no longer claim a false day-level precision."""
    a = format_date("2020-01-01", "year")
    b = format_date("2020-01-01", "year")
    assert a == b == "2020년"
