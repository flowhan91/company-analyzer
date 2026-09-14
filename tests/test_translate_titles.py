from __future__ import annotations

from company_analyzer.db import repository as repo
from company_analyzer.db.connection import DBConnection
from company_analyzer.llm.mock_provider import MockLLMProvider
from company_analyzer.translation.translate_titles import (
    contains_korean,
    needs_translation,
    translate_canonical_event_titles,
    translate_thread_titles,
)


def test_contains_korean():
    assert contains_korean("HyperCLOVA X 확장") is True
    assert contains_korean("HyperCLOVA X: launch") is False


def test_needs_translation_catches_korean_entity_with_leftover_english_action():
    """Regression: a title built from a Korean entity (extracted before the
    Korean-action prompt fix) plus an untranslated English action, e.g.
    "ADVoost 쇼핑: launched" - contains_korean() alone says this is already
    Korean because the entity half is, silently leaving the action in
    English forever on every rerun."""
    assert needs_translation("ADVoost 쇼핑: launched") is True
    assert needs_translation("네이버쇼핑: launched") is True


def test_needs_translation_catches_leftover_english_thread_suffix():
    """Regression: the pre-fix _thread_title() always appended a literal
    English "Expansion"/"Initiative" even onto a Korean entity name."""
    assert needs_translation("스토어팜/스마트스토어 Expansion") is True
    assert needs_translation("이니셔티브 Initiative") is True


def test_needs_translation_leaves_fully_translated_titles_alone():
    assert needs_translation("HyperCLOVA X 확장") is False
    assert needs_translation("NAVER Cloud Platform 출시하였습니다") is False


def test_translate_canonical_event_titles_rewrites_non_korean_titles(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")
    english = repo.create_canonical_event(
        conn, company_id=company.id, event_type="product_launch", subject="NAVER",
        action="launched", canonical_date="2025-06-01", date_precision="day",
        lifecycle_status="completed", domain="search", entity="HyperCLOVA X",
        title="Launch of HyperCLOVA X", summary=None, review_status="auto_applied",
    )
    already_korean = repo.create_canonical_event(
        conn, company_id=company.id, event_type="product_launch", subject="NAVER",
        action="출시함", canonical_date="2025-06-02", date_precision="day",
        lifecycle_status="completed", domain="search", entity="AI Tab",
        title="AI Tab: 출시함", summary=None, review_status="auto_applied",
    )

    provider = MockLLMProvider()
    count = translate_canonical_event_titles(conn, company.id, provider)

    assert count == 1
    updated = repo.get_canonical_event(conn, english.id)
    assert updated.title == "HyperCLOVA X: launched"
    unchanged = repo.get_canonical_event(conn, already_korean.id)
    assert unchanged.title == "AI Tab: 출시함"


def test_translate_thread_titles_rewrites_non_korean_titles(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")
    english = repo.create_thread(
        conn, company_id=company.id, title="HyperCLOVA X Expansion",
        domain="search", entity="HyperCLOVA X", review_status="auto_applied",
    )
    already_korean = repo.create_thread(
        conn, company_id=company.id, title="HyperCLOVA X 확장",
        domain="search", entity="HyperCLOVA X", review_status="auto_applied",
    )

    provider = MockLLMProvider()
    count = translate_thread_titles(conn, company.id, provider)

    assert count == 1
    assert repo.get_thread(conn, english.id).title != "HyperCLOVA X Expansion"
    assert repo.get_thread(conn, already_korean.id).title == "HyperCLOVA X 확장"


class _KoreanStubProvider(MockLLMProvider):
    """MockLLMProvider's own generate_title deliberately doesn't produce
    Korean (nothing to prove about translation quality there) - this stub
    does, so the idempotency ("skip already-Korean titles") behavior can
    actually be exercised."""

    def generate_title(self, fields: dict) -> str:
        return "하이퍼클로바 엑스 출시"


def test_translate_titles_is_idempotent(conn: DBConnection):
    company = repo.get_or_create_company(conn, "NAVER")
    repo.create_canonical_event(
        conn, company_id=company.id, event_type="product_launch", subject="NAVER",
        action="launched", canonical_date="2025-06-01", date_precision="day",
        lifecycle_status="completed", domain="search", entity="HyperCLOVA X",
        title="HyperCLOVA X: launched", summary=None, review_status="auto_applied",
    )
    provider = _KoreanStubProvider()
    first = translate_canonical_event_titles(conn, company.id, provider)
    second = translate_canonical_event_titles(conn, company.id, provider)
    assert first == 1
    assert second == 0
