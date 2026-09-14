from __future__ import annotations

from company_analyzer.chunking.base import ChunkDraft, find_paragraphs

OVERLAP_CHARS = 80
MIN_PARAGRAPH_LENGTH = 20


def chunk_with_overlap(
    raw_text: str, overlap_chars: int = OVERLAP_CHARS, min_length: int = MIN_PARAGRAPH_LENGTH
) -> list[ChunkDraft]:
    """News articles: paragraph split, each chunk (after the first) extends its
    start backward into the tail of the previous paragraph so short news items
    don't lose cross-paragraph context. Still an exact slice of raw_text."""
    paragraphs = find_paragraphs(raw_text, min_length=min_length)
    drafts: list[ChunkDraft] = []
    for i, (start, end, _text) in enumerate(paragraphs):
        if i > 0:
            prev_start, prev_end, _ = paragraphs[i - 1]
            start = max(prev_start, prev_end - overlap_chars)
        drafts.append({"heading": None, "text": raw_text[start:end], "start_offset": start, "end_offset": end})
    return drafts
