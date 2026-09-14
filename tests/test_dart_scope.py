from __future__ import annotations

from company_analyzer.chunking.dart_scope import is_periodic_report, scope_to_business_section
from company_analyzer.chunking.dispatch import chunk_document

QUARTERLY_REPORT = """I. 회사의 개요
1. 회사의 개요
회사의 개요는 기업공시서식 작성기준에 따라 분기보고서에 기재하지 않습니다.

II. 사업의 내용
1. 사업의 개요
NAVER는 검색, 커머스, 클라우드 사업을 영위하고 있으며 AI 검색 서비스를 확대하고 있습니다.

2. 주요 제품 및 서비스
HyperCLOVA X 기반 검색 서비스를 전체 사용자에게 제공하기 시작했습니다.

III. 재무에 관한 사항
1. 요약재무정보
자산총계 100,000,000,000원
부채총계 50,000,000,000원
"""


def test_is_periodic_report_matches_known_titles():
    assert is_periodic_report("분기보고서 (2026.03)")
    assert is_periodic_report("사업보고서 (2025.12)")
    assert is_periodic_report("반기보고서 (2026.06)")
    assert not is_periodic_report("주요사항보고서(유상증자결정)")
    assert not is_periodic_report("[기재정정]주요사항보고서(자기주식처분결정)")


def test_scope_to_business_section_bounds_on_next_top_level_heading():
    scoped, offset = scope_to_business_section(QUARTERLY_REPORT)
    assert scoped.startswith("II. 사업의 내용")
    assert "HyperCLOVA X" in scoped
    assert "재무에 관한 사항" not in scoped
    assert "자산총계" not in scoped
    assert QUARTERLY_REPORT[offset:offset + len(scoped)] == scoped


def test_scope_to_business_section_falls_back_when_heading_not_found():
    text = "Just some plain text with no headings at all."
    scoped, offset = scope_to_business_section(text)
    assert scoped == text
    assert offset == 0


def test_chunk_document_scopes_periodic_reports_and_keeps_offsets_correct():
    drafts = chunk_document("dart", "분기보고서 (2026.03)", QUARTERLY_REPORT)
    assert drafts, "expected at least one chunk from the business section"
    for draft in drafts:
        assert QUARTERLY_REPORT[draft["start_offset"]:draft["end_offset"]] == draft["text"]
    combined = " ".join(d["text"] for d in drafts)
    assert "HyperCLOVA X" in combined
    assert "재무에 관한 사항" not in combined
    assert "자산총계" not in combined


def test_chunk_document_does_not_scope_non_periodic_dart_filings():
    text = "주요사항보고서(유상증자결정)\n1. 신주의 종류와 수\n보통주식 7,241,564주 발행을 통해 대규모 자금을 조달합니다."
    drafts = chunk_document("dart", "주요사항보고서(유상증자결정)", text)
    combined = " ".join(d["text"] for d in drafts)
    assert "신주의 종류와 수" in combined or "보통주식" in combined
    for draft in drafts:
        assert text[draft["start_offset"]:draft["end_offset"]] == draft["text"]
