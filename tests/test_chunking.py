from __future__ import annotations

import pytest

from company_analyzer.chunking.dispatch import get_chunker
from company_analyzer.chunking.heading_paragraph_chunker import chunk_by_heading_and_paragraph
from company_analyzer.chunking.overlap_paragraph_chunker import chunk_with_overlap
from company_analyzer.chunking.paragraph_chunker import chunk_by_paragraph
from company_analyzer.chunking.section_chunker import chunk_by_section

PRESS_RELEASE = """NAVER announces expansion of its AI search service.

The company plans to increase infrastructure capacity across its Korean data centers.

Contact: press@navercorp.com"""

DART_FILING = """1. 사업의 개요
NAVER Corporation operates a leading Korean internet platform.

2. 주요 제품 및 서비스
The company provides search, commerce, and cloud services.

2.1 AI 사업
NAVER has invested heavily in HyperCLOVA X, its large language model.
"""

DISCLOSURE_FORM = """주요사항보고서(자기주식 처분 결정)
6.2
네이버(주)
정 정 신 고 (보고)
2026년 03월 23일
1. 정정대상 공시서류 :
주요사항보고서(자기주식 처분 결정)
2. 정정대상 공시서류의 최초제출일 :
2022년 03월 02일
3. 정정사항
항  목
정정사유
정 정 전
정 정 후
1. 처분예정주식(주)
상법 개정 내용을 반영한 주식매수선택권지급방식 변경
143,577
100,316
3. 처분예정금액(원)
26,705,322,000
18,658,776,000
"""

_ARCHITECTURE_PARAGRAPHS = "\n\n".join(
    f"Paragraph {i}: this section covers the architecture in detail. " * 4 for i in range(6)
)

TECH_BLOG = f"""# Introduction

We are excited to share our latest work on distributed search infrastructure.

# Architecture

{_ARCHITECTURE_PARAGRAPHS}

# Conclusion

Thanks for reading.
"""

NEWS_ARTICLE = """NAVER launched a new AI-powered search feature today, the company said.

The feature, part of the HyperCLOVA X initiative, will roll out to all users by next quarter."""


def _assert_offsets_reconstruct(raw_text: str, drafts: list[dict]) -> None:
    for draft in drafts:
        assert raw_text[draft["start_offset"]:draft["end_offset"]] == draft["text"]


def test_paragraph_chunker_splits_and_drops_short_fragments():
    drafts = chunk_by_paragraph(PRESS_RELEASE)
    _assert_offsets_reconstruct(PRESS_RELEASE, drafts)
    texts = [d["text"] for d in drafts]
    assert any("expansion of its AI search" in t for t in texts)
    assert any("infrastructure capacity" in t for t in texts)
    # "Contact: press@navercorp.com" is under the 20-char min? it's 29 chars, so it survives;
    # just assert nothing empty/whitespace-only got through.
    assert all(t.strip() for t in texts)


def test_section_chunker_splits_on_numbered_headings():
    drafts = chunk_by_section(DART_FILING)
    _assert_offsets_reconstruct(DART_FILING, drafts)
    headings = [d["heading"] for d in drafts]
    assert any(h and h.startswith("1.") for h in headings)
    assert any(h and h.startswith("2.1") for h in headings)


def test_section_chunker_merges_numbered_form_fields_instead_of_over_splitting():
    """Regression test: a real ~3KB DART treasury-stock disclosure amendment
    produced 30+ one-line chunks (one per numbered form field like
    '1. 처분예정주식수') before this fix, because the heading regex can't tell
    a real narrative heading from a numbered form-field label. Numbered
    fields whose body is just a short value line should merge into one
    coherent chunk instead of fragmenting."""
    drafts = chunk_by_section(DISCLOSURE_FORM)
    _assert_offsets_reconstruct(DISCLOSURE_FORM, drafts)
    assert len(drafts) <= 3, f"expected a handful of merged chunks, got {len(drafts)}: {[d['heading'] for d in drafts]}"


def test_section_chunker_falls_back_to_paragraphs_without_headings():
    plain = "Just a plain paragraph with no headings at all in it whatsoever."
    drafts = chunk_by_section(plain)
    _assert_offsets_reconstruct(plain, drafts)
    assert len(drafts) == 1
    assert drafts[0]["heading"] is None


def test_heading_paragraph_chunker_splits_oversized_sections():
    drafts = chunk_by_heading_and_paragraph(TECH_BLOG, max_section_length=200)
    _assert_offsets_reconstruct(TECH_BLOG, drafts)
    architecture_chunks = [d for d in drafts if d["heading"] == "# Architecture"]
    assert len(architecture_chunks) > 1, "oversized section should be split into multiple paragraph chunks"
    intro_chunks = [d for d in drafts if d["heading"] == "# Introduction"]
    assert len(intro_chunks) == 1


def test_overlap_chunker_prepends_tail_of_previous_paragraph():
    drafts = chunk_with_overlap(NEWS_ARTICLE, overlap_chars=20, min_length=0)
    _assert_offsets_reconstruct(NEWS_ARTICLE, drafts)
    assert len(drafts) == 2
    assert drafts[0]["start_offset"] == 0
    # second chunk's start should reach back into the first paragraph's tail
    assert drafts[1]["start_offset"] < drafts[0]["end_offset"]


def test_dispatch_maps_source_types_to_chunkers():
    assert get_chunker("dart") is chunk_by_section
    assert get_chunker("ir") is chunk_by_section
    assert get_chunker("press_release") is chunk_by_paragraph
    assert get_chunker("tech_blog") is chunk_by_heading_and_paragraph
    assert get_chunker("ceo_letter") is chunk_by_heading_and_paragraph
    assert get_chunker("news") is chunk_with_overlap
    with pytest.raises(ValueError):
        get_chunker("unknown_source")
