from __future__ import annotations

import re

from company_analyzer.chunking.base import ChunkDraft, make_draft
from company_analyzer.chunking.paragraph_chunker import chunk_by_paragraph

# DART/IR headings: markdown headings, roman/arabic numbered headings, Korean
# lettered headings ("가.", "나."), or bracketed section markers ("【사업의 내용】").
_HEADING_RE = re.compile(
    r"^(?:#{1,6}\s+.+"
    r"|[IVXLCDM]+\.\s+.+"
    r"|\d+(?:\.\d+)*\.?\s+.+"
    r"|[가-힣]\.\s+.+"
    r"|【.+?】.*)$",
    re.MULTILINE,
)

# Numbered disclosure-form fields ("1. 처분예정주식수\n143,577") match the same
# heading pattern as real narrative headings ("1. 사업의 개요") but their body
# is just a short value line, not a paragraph. Real DART filings ingested
# without this filter produced 30+ chunks for a ~3KB disclosure form (one per
# field) instead of a handful of coherent chunks - a span whose body is
# shorter than this is folded forward into the next one instead of standing
# alone.
MIN_SECTION_BODY_LENGTH = 40


def chunk_by_section(raw_text: str) -> list[ChunkDraft]:
    """DART filings / IR materials: split on numbered/lettered/markdown headings.

    Falls back to paragraph chunking for documents with no detectable
    headings, rather than emitting one giant chunk.
    """
    matches = list(_HEADING_RE.finditer(raw_text))
    if not matches:
        return chunk_by_paragraph(raw_text, min_length=0)

    raw_spans: list[tuple[int, int, str]] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw_text)
        raw_spans.append((start, end, match.group().strip()))

    merged_spans = _merge_tiny_spans(raw_spans)

    drafts: list[ChunkDraft] = []
    for start, end, heading in merged_spans:
        draft = make_draft(raw_text, start, end, heading=heading)
        if draft is not None:
            drafts.append(draft)
    return drafts


def _merge_tiny_spans(raw_spans: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    merged: list[tuple[int, int, str]] = []
    carry_start: int | None = None
    carry_heading: str | None = None

    for start, end, heading in raw_spans:
        span_start = carry_start if carry_start is not None else start
        span_heading = carry_heading if carry_heading is not None else heading
        body_len = (end - start) - len(heading)
        if body_len < MIN_SECTION_BODY_LENGTH:
            carry_start, carry_heading = span_start, span_heading
            continue
        merged.append((span_start, end, span_heading))
        carry_start, carry_heading = None, None

    if carry_start is not None:
        if merged:
            prev_start, _prev_end, prev_heading = merged[-1]
            merged[-1] = (prev_start, raw_spans[-1][1], prev_heading)
        else:
            merged.append((carry_start, raw_spans[-1][1], carry_heading))

    return merged
